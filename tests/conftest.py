import logging
import sys
import types

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext
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
