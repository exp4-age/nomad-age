import logging
import sys
import types
from types import SimpleNamespace

import nomad
import pytest
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext
from nomad.metainfo import MetainfoReferenceError
from nomad.parsing.parser import ArchiveParser

UPLOAD_ID = 'test_upload'


class _NoEntries:
    def count(self):
        return 0

    def first(self):
        return None


@pytest.fixture
def process_entry(monkeypatch):
    """Process an entry file of the upload in a directory as NOMAD does: parse it,
    normalize its data and collect its metadata, above all the entry references.

    NOMAD collects entry references only with MongoDB, where it looks up the
    mainfiles of the referenced entries; the lookup finds none here.
    """
    from nomad.datamodel import datamodel

    monkeypatch.setattr(datamodel, 'has_mongo', True)
    monkeypatch.setattr(datamodel, '_check_mongo_connection', lambda: None)
    processing = types.ModuleType('nomad.processing')
    processing.Entry = types.SimpleNamespace(objects=lambda **_: _NoEntries())
    monkeypatch.setitem(sys.modules, 'nomad.processing', processing)

    def process(directory, entry_file, logger=None, context=None):
        logger = logger or logging.getLogger(__name__)
        archive = EntryArchive(
            m_context=context or ClientContext(local_dir=str(directory)),
            metadata=EntryMetadata(mainfile=entry_file, upload_id=UPLOAD_ID),
        )
        ArchiveParser().parse(str(directory / entry_file), archive, logger)
        archive.data.normalize(archive, logger)
        archive.metadata.apply_archive_metadata(archive)
        return archive

    return process


@pytest.fixture
def entry_references():
    """(source path, target entry id) of the entry references of an archive."""

    def references(archive) -> set:
        return {
            (reference.source_path, reference.target_entry_id)
            for reference in archive.metadata.entry_references
        }

    return references


@pytest.fixture
def stored_archives(monkeypatch):
    """Stand-in for nomad.files: store(entries) makes `entries`, a dict by entry id,
    the data of the processed archives of the upload."""

    def store(entries: dict) -> None:
        class StoredArchive:
            def __init__(self, entry_id):
                self.entry_id = entry_id

            def __enter__(self):
                return {self.entry_id: {'data': dict(entries[self.entry_id])}}

            def __exit__(self, *exc):
                return False

        upload_files = SimpleNamespace(
            read_archive=lambda entry_id: StoredArchive(entry_id)
        )
        files = types.ModuleType('nomad.files')
        files.UploadFiles = SimpleNamespace(get=lambda upload_id: upload_files)
        monkeypatch.setitem(sys.modules, 'nomad.files', files)
        monkeypatch.setattr(nomad, 'files', files, raising=False)

    return store


class StoredArchivesContext(ClientContext):
    """Stand-in for the server context of processing: references load the
    processed archives of entries of any upload; other entries fail to load."""

    def __init__(self, local_dir, archives: dict):
        super().__init__(local_dir=str(local_dir), upload_id=UPLOAD_ID)
        self.stored = archives

    def load_archive(self, entry_id, upload_id, installation_url):
        try:
            data = self.stored[(upload_id, entry_id)]
        except KeyError:
            raise MetainfoReferenceError(f'Could not load {entry_id}.')
        archive = {'metadata': {'upload_id': upload_id, 'entry_id': entry_id}}
        return EntryArchive.m_from_dict({**archive, 'data': data}, m_context=self)


@pytest.fixture
def stored_archives_context():
    """Context of a processed entry in a directory whose references load the
    data of `archives`, a dict by (upload id, entry id)."""
    return StoredArchivesContext
