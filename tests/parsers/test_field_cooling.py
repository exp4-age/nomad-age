import hashlib
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata, User
from nomad.datamodel.context import ClientContext
from nomad.utils import get_logger

from nomad_age.parsers.field_cooling_parser import FieldCoolingParser
from nomad_age.schema_packages.age_schema import AGE_RawFile
from nomad_age.utils import utils
from nomad_age.utils.utils import get_entry_id, get_hash_ref, get_reference

LOG = (
    Path(__file__).parent.parent
    / 'data/fieldcooling/2024.09.17-2024_0290, 2024_0286.DAT'
)
MAINFILE = 'cooling/log.DAT'
ENTRY_FILE = 'log.DAT.archive.yaml'  # the parser writes it to the upload root
SAMPLES_UPLOAD = 'age_samples_upload'


def chip_entry_id(lab_id):
    return f'chip_{lab_id}'


def chip_ref(lab_id):
    return f'{get_reference(SAMPLES_UPLOAD, chip_entry_id(lab_id))}#data'


@pytest.fixture
def searches(monkeypatch):
    """(lab id, user id) of the sample searches; each finds the chip in the AGE
    Samples upload, unless its lab id is in `searches.missing`."""
    calls = []
    missing = set()

    def search(lab_id, user_id=None):
        calls.append((lab_id, user_id))
        if lab_id in missing:
            return SimpleNamespace(data=[])
        hit = {'upload_id': SAMPLES_UPLOAD, 'entry_id': chip_entry_id(lab_id)}
        return SimpleNamespace(data=[hit])

    monkeypatch.setattr(utils, 'find_existing_AGE_sample', search)
    return SimpleNamespace(calls=calls, missing=missing)


@pytest.fixture
def upload(tmp_path, searches):
    """Upload in `tmp_path` with the start of a field cooling log whose samples
    exist."""
    (tmp_path / 'cooling').mkdir()
    lines = LOG.read_bytes().splitlines(keepends=True)
    (tmp_path / MAINFILE).write_bytes(b''.join(lines[:40]))
    return tmp_path


def set_sample_line(upload, samples: str) -> None:
    log = upload / MAINFILE
    lines = log.read_bytes().splitlines(keepends=True)
    lines[3] = f'Probenname: {samples}\r\n'.encode('latin1')
    log.write_bytes(b''.join(lines))


def parse(upload, logger=None, main_author=None) -> EntryArchive:
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(upload)),
        metadata=EntryMetadata(
            mainfile=MAINFILE, upload_id='test_upload', main_author=main_author
        ),
    )
    logger = logger or get_logger(__name__)
    FieldCoolingParser().parse(str(upload / MAINFILE), archive, logger)
    archive.data.normalize(archive, logger)
    return archive


def entry_data(upload) -> dict:
    with open(upload / ENTRY_FILE) as f:
        return yaml.safe_load(f)['data']


def sample_refs(upload) -> list:
    """The sample references of the entry file, without their section type."""
    samples = entry_data(upload).get('samples', [])
    return [{k: v for k, v in s.items() if k != 'm_def'} for s in samples]


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


def test_samples_link_chips_of_the_samples_upload(upload, searches):
    set_sample_line(upload, '2023_0418, 2023_0419')
    author = User(user_id='author_id')

    parse(upload, main_author=author)

    assert sample_refs(upload) == [
        {'name': lab_id, 'lab_id': lab_id, 'reference': chip_ref(lab_id)}
        for lab_id in ('2023_0418_1', '2023_0419_1')
    ]
    # unpublished chips are only found with the user id of the main author
    assert searches.calls == [
        ('2023_0418_1', 'author_id'),
        ('2023_0419_1', 'author_id'),
    ]


def test_broken_chips_keep_their_ids(upload, searches):
    set_sample_line(upload, '2023_0418_1_2, 2023_0418_1, 2023_0418')

    parse(upload)

    samples = entry_data(upload)['samples']
    assert [sample['lab_id'] for sample in samples] == ['2023_0418_1_2', '2023_0418_1']
    assert 'description' not in entry_data(upload)


def test_missing_chips_are_reported_not_created(upload, searches, caplog):
    set_sample_line(upload, '2026_0167')
    searches.missing.add('2026_0167_1')

    with caplog.at_level(logging.WARNING):
        parse(upload, logger=logging.getLogger(__name__))

    assert sample_refs(upload) == [{'name': '2026_0167_1', 'lab_id': '2026_0167_1'}]
    entry_files = {path.name for path in upload.glob('*.archive.yaml')}
    assert entry_files == {ENTRY_FILE}
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert '2026_0167_1' in warning.getMessage()
    assert 'AGE Samples upload' in warning.getMessage()


def test_reparse_replaces_old_sample_references(upload, stored_archives):
    parse(upload)
    old = entry_data(upload)
    # as older versions wrote it: chips created in the data upload
    old['samples'] = [
        {'reference': get_hash_ref('test_upload', f'{lab_id}.archive.yaml')}
        for lab_id in ('2024_0290', '2024_0286')
    ]
    with open(upload / ENTRY_FILE, 'w') as f:
        yaml.dump({'data': old}, f)
    stored_archives({get_entry_id('test_upload', ENTRY_FILE): old})

    parse(upload)

    assert sample_refs(upload) == [
        {'name': lab_id, 'lab_id': lab_id, 'reference': chip_ref(lab_id)}
        for lab_id in ('2024_0290_1', '2024_0286_1')
    ]
