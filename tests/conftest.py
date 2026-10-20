import asyncio
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

    def process(directory, entry_file, logger=None, context=None, entry_id=None):
        logger = logger or logging.getLogger(__name__)
        archive = EntryArchive(
            m_context=context or ClientContext(local_dir=str(directory)),
            metadata=EntryMetadata(
                mainfile=entry_file, upload_id=UPLOAD_ID, entry_id=entry_id
            ),
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


class KwargsLogger:
    """stdlib logger that accepts structlog-style keyword arguments like NOMAD's."""

    def __init__(self, logger):
        self._logger = logger

    def __getattr__(self, level):
        log = getattr(self._logger, level)
        return lambda msg, *args, **kwargs: log(msg, *args)


@pytest.fixture
def kwargs_logger():
    return KwargsLogger(logging.getLogger('nomad_age.tests'))


class FakeIndex:
    """Stand-in for the search index (nomad.search): `docs` are the indexed
    entries; queries match all of their keys, as NOMAD's do."""

    FIELDS = {
        'entry_references.target_entry_id': lambda doc: [
            ref['target_entry_id'] for ref in doc.get('entry_references', [])
        ],
        'section_defs.definition_qualified_name': lambda doc: [
            sd['definition_qualified_name'] for sd in doc.get('section_defs', [])
        ],
    }

    def __init__(self):
        self.docs = []
        self.calls = []

    def matches(self, doc, query) -> bool:
        for key, value in query.items():
            values = self.FIELDS[key.split(':')[0]](doc)
            wanted = value if isinstance(value, list) else [value]
            if not all(v in values for v in wanted):
                return False
        return True

    def search(self, owner=None, query=None, required=None, pagination=None, **kw):
        self.calls.append({'owner': owner, 'query': query, **kw})
        hits = [dict(doc) for doc in self.docs if self.matches(doc, query or {})]
        return SimpleNamespace(
            data=hits,
            pagination=SimpleNamespace(total=len(hits), next_page_after_value=None),
        )


@pytest.fixture
def fake_index(monkeypatch):
    index = FakeIndex()
    module = types.ModuleType('nomad.search')
    module.search = index.search
    module.MetadataRequired = SimpleNamespace
    module.MetadataPagination = SimpleNamespace
    monkeypatch.setitem(sys.modules, 'nomad.search', module)
    monkeypatch.setattr(nomad, 'search', module, raising=False)
    return index


class FakeTemporal:
    """Stand-in for the Temporal client and the NOMAD processing API that
    nomad_age.utils.chip_refresh uses. `started` lists the started workflows;
    a workflow id that is still pending cannot start again."""

    class AlreadyStarted(Exception):
        pass

    def __init__(self):
        self.started = []
        self.busy_uploads = set()
        self.published_uploads = set()
        self.in_activity = True
        self.workflow_id = 'process-upload-moke_upload'
        temporal = self

        class Client:
            async def start_workflow(self, workflow, arg, **kwargs):
                if any(kwargs['id'] == s['id'] for s in temporal.started):
                    raise FakeTemporal.AlreadyStarted(kwargs['id'])
                temporal.started.append({'workflow': workflow, 'arg': arg, **kwargs})

        async def get_client():
            return Client()

        def get_upload(upload_id):
            busy = upload_id in temporal.busy_uploads
            return SimpleNamespace(
                process_running=busy,
                workflow_ids=[],
                published=upload_id in temporal.published_uploads,
            )

        self.api = SimpleNamespace(
            temporal_enabled=True,
            activity=SimpleNamespace(
                in_activity=lambda: temporal.in_activity,
                info=lambda: SimpleNamespace(workflow_id=temporal.workflow_id),
            ),
            get_client=get_client,
            run_async=asyncio.run,
            Upload=SimpleNamespace(get=get_upload),
            ProcessEntryActivityInput=SimpleNamespace,
            TaskQueue=SimpleNamespace(
                NOMAD_INTERNAL_WORKFLOWS=SimpleNamespace(value='nomad-internal')
            ),
            RetryPolicy=SimpleNamespace,
            WorkflowAlreadyStartedError=FakeTemporal.AlreadyStarted,
        )

    @property
    def started_ids(self) -> list:
        return [s['id'] for s in self.started]


@pytest.fixture
def temporal(monkeypatch):
    """Processing in an activity of a Temporal worker, see FakeTemporal."""
    from nomad_age.utils import chip_refresh

    fake = FakeTemporal()
    monkeypatch.setattr(chip_refresh, '_load_api', lambda: fake.api)
    return fake
