import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext
from nomad.utils import get_logger

from nomad_age.parsers import field_cooling_parser
from nomad_age.parsers.field_cooling_parser import FieldCoolingParser
from nomad_age.schema_packages.age_schema import AGE_RawFile
from nomad_age.utils.utils import get_entry_id, get_hash_ref

LOG = (
    Path(__file__).parent.parent
    / 'data/fieldcooling/2024.09.17-2024_0290, 2024_0286.DAT'
)
MAINFILE = 'cooling/log.DAT'
ENTRY_FILE = 'log.DAT.archive.yaml'  # the parser writes it to the upload root


@pytest.fixture
def upload(tmp_path, monkeypatch):
    """Upload in `tmp_path` with the start of a field cooling log whose samples
    exist."""
    monkeypatch.setattr(
        field_cooling_parser,
        'find_existing_AGE_sample',
        lambda lab_id: SimpleNamespace(data=[{'lab_id': lab_id}]),
    )
    (tmp_path / 'cooling').mkdir()
    lines = LOG.read_bytes().splitlines(keepends=True)
    (tmp_path / MAINFILE).write_bytes(b''.join(lines[:40]))
    return tmp_path


def parse(upload) -> EntryArchive:
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(upload)),
        metadata=EntryMetadata(mainfile=MAINFILE, upload_id='test_upload'),
    )
    logger = get_logger(__name__)
    FieldCoolingParser().parse(str(upload / MAINFILE), archive, logger)
    archive.data.normalize(archive, logger)
    return archive


def entry_data(upload) -> dict:
    with open(upload / ENTRY_FILE) as f:
        return yaml.safe_load(f)['data']


def test_raw_file_entry_fingerprints_the_log(upload, process_entry, entry_references):
    raw = parse(upload).data

    assert isinstance(raw, AGE_RawFile)
    assert (raw.name, raw.file_name) == ('log.DAT', MAINFILE)
    assert raw.file_type == 'field cooling log'
    content = (upload / MAINFILE).read_bytes()
    assert raw.file_size.to('byte').magnitude == len(content)
    assert raw.sha256 == hashlib.sha256(content).hexdigest()
    assert raw.modified.tzinfo is not None
    assert raw.m_to_dict()['processed_archive'] == get_hash_ref(
        'test_upload', ENTRY_FILE
    )
    assert entry_data(upload)['raw_file'] == get_hash_ref('test_upload', MAINFILE)
    entry = process_entry(upload, ENTRY_FILE)
    raw_id = get_entry_id('test_upload', MAINFILE)
    assert ('data.raw_file', raw_id) in entry_references(entry)


def test_old_entry_gains_raw_file_once_and_keeps_user_edits(upload, stored_archives):
    parse(upload)
    old = entry_data(upload)
    # as older versions wrote it, then edited in the GUI
    del old['raw_file']
    old['blocking_temperature'] = 360.0
    with open(upload / ENTRY_FILE, 'w') as f:
        yaml.dump({'data': old}, f)
    eid = get_entry_id('test_upload', ENTRY_FILE)
    stored_archives({eid: old})

    parse(upload)

    migrated = entry_data(upload)
    assert migrated['raw_file'] == get_hash_ref('test_upload', MAINFILE)
    assert migrated['blocking_temperature'] == 360.0
    assert migrated == {**old, 'raw_file': migrated['raw_file']}

    # the next reprocessing finds the entry file up to date and leaves it alone
    text = (upload / ENTRY_FILE).read_text()
    mtime = (upload / ENTRY_FILE).stat().st_mtime_ns
    stored_archives({eid: migrated})
    parse(upload)
    assert (upload / ENTRY_FILE).read_text() == text
    assert (upload / ENTRY_FILE).stat().st_mtime_ns == mtime
