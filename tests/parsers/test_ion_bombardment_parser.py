import hashlib
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext
from nomad.utils import get_logger

from nomad_age.parsers.ion_bombardment_parser import (
    IonBombardmentParser,
    bombardment_mode,
    detect_format_version,
    parse_point,
    read_v1,
)
from nomad_age.schema_packages.age_schema import AGE_RawFile
from nomad_age.schema_packages.ion_bombardment_schema import ION_BOMBARDMENT_METHOD
from nomad_age.utils import utils
from nomad_age.utils.utils import get_entry_id, get_hash_ref, get_reference

DATA = Path(__file__).parent.parent / 'data/isa'
LOG_2026 = '20260819_114439_logger.txt'
LOG_2025 = '20250514_121010_logger.txt'
SAMPLES_UPLOAD = 'age_samples_upload'


def chip_ref(lab_id):
    return f'{get_reference(SAMPLES_UPLOAD, "chip_" + lab_id)}#data'


@pytest.fixture
def searches(monkeypatch):
    calls, missing = [], set()

    def search(lab_id, user_id=None):
        calls.append(lab_id)
        if lab_id in missing:
            return SimpleNamespace(data=[])
        return SimpleNamespace(
            data=[{'upload_id': SAMPLES_UPLOAD, 'entry_id': 'chip_' + lab_id}]
        )

    monkeypatch.setattr(utils, 'find_existing_AGE_sample', search)
    return SimpleNamespace(calls=calls, missing=missing)


def make_upload(tmp_path, log, lmoke=('2024_0250',)):
    for name in lmoke:
        (tmp_path / f'{name}_LMOKE_2026-08-19_10-00-00.txt').write_text(
            '# Meas. type\n'
        )
    shutil.copy(DATA / log, tmp_path / log)
    return tmp_path


def parse(upload, log, logger=None) -> EntryArchive:
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(upload)),
        metadata=EntryMetadata(mainfile=log, upload_id='test_upload'),
    )
    logger = logger or get_logger(__name__)
    IonBombardmentParser().parse(str(upload / log), archive, logger)
    archive.data.normalize(archive, logger)
    return archive


def entry_data(upload, log) -> dict:
    with open(upload / f'{log}.archive.yaml') as f:
        return yaml.safe_load(f)['data']


def test_version_detection():
    v1 = (DATA / LOG_2026).read_text(encoding='latin1').splitlines()
    assert detect_format_version(v1) == '1'
    assert detect_format_version(['Version: 2', '...']) == '2'
    assert detect_format_version(['# ISA logger version = 2.1']) == '2.1'
    assert detect_format_version(['something else', 'entirely']) is None


def test_point_lines():
    p = parse_point("Point14: [[1.142,0.480],0.0,True,True,1.0043,['1.86e13']]")
    assert p == {
        'name': 'Point14',
        'number': 14,
        'x': 1.142,
        'y': 0.48,
        'dose_wanted': 0.0,
        'assigned': True,
        'bombarded': True,
        'bombardment_time': 1.0043,
        'dose_bombarded': 1.86e13,
        'dose_record': '1.86e13',
        'reference_spot': True,
    }
    p = parse_point("Point6: [[0.300,0.250],3.5e15,True,True,179.8547,['3.5e15']]")
    assert (p['reference_spot'], p['dose_bombarded']) == (False, 3.5e15)
    # not bombarded: the log writes the wanted dose instead of a list
    p = parse_point('Point19: [[-1.299,-0.600],5.0e15,True,False,0.0000,5.0e15]')
    assert (p['bombarded'], p['dose_bombarded'], p['reference_spot']) == (
        False,
        0.0,
        False,
    )
    assert parse_point('Positions Dictionary:') is None


def test_device_errors_and_broken_lines(caplog, kwargs_logger):
    lines = (DATA / LOG_2026).read_text(encoding='latin1').splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith('11:49'))
    cells = lines[first].split('\t')
    cells[5] = 'error'  # BeamCurrent read failed
    lines[first] = '\t'.join(cells)
    lines.insert(first + 1, '15:18:33\t4.660\t0')
    lines.insert(first + 1, '15:18:34\t4.660\t0')
    with caplog.at_level(logging.WARNING):
        r = read_v1(lines, None, kwargs_logger)
    assert len(r['seconds']) == 60
    assert np.isnan(r['columns']['BeamCurrent'][0])
    warnings = [m.getMessage() for m in caplog.records if 'Skipped' in m.getMessage()]
    assert len(warnings) == 1 and 'Skipped 2 ' in warnings[0]


def test_dose_list_last_entry_is_applied():
    # one entry per dose check; after a pause the first one was never applied
    p = parse_point("Point3: [[0.0,0.0],1.0e15,True,True,5.2,['5.0e14', '1.0e15']]")
    assert p['dose_bombarded'] == 1e15
    assert p['dose_record'] == '5.0e14, 1.0e15'


@pytest.mark.parametrize(
    'log, mode, velocity',
    [
        ('20231122_112137_logger.txt', 'area', 0.0105),
        ('20230308_144525_logger.txt', 'line or gradient', 0.0499),
        (LOG_2026, 'multi point', None),
    ],
)
def test_bombardment_mode(log, mode, velocity):
    lines = (DATA / log).read_text(encoding='latin1').splitlines()
    points = read_v1(lines, None, get_logger(__name__))['points']
    assert bombardment_mode(points) == mode
    assert points[0].get('velocity') == velocity
    if mode == 'area':
        assert [(p['x'], p['y']) for p in points] == [(0.0, 0.0), (1.7, 1.7)]
        assert points[0]['dose_bombarded'] == 8e14


def test_entry_of_2026_log(tmp_path, searches):
    upload = make_upload(tmp_path, LOG_2026)
    raw = parse(upload, LOG_2026).data

    assert isinstance(raw, AGE_RawFile)
    assert raw.file_type == 'ion bombardment log'
    content = (upload / LOG_2026).read_bytes()
    assert raw.sha256 == hashlib.sha256(content).hexdigest()

    data = entry_data(upload, LOG_2026)
    assert data['raw_file'] == get_hash_ref('test_upload', LOG_2026)
    assert data['log_format_version'] == '1'
    assert data['name'] == 'IB_2026-08-19 11:49:28'
    assert data['datetime'].startswith('2026-08-19T09:49:28')  # CEST -> UTC
    assert data['number_of_points'] == 20
    assert data['number_bombarded'] == 20
    assert data['number_reference_spots'] == 2  # Point14, Point20
    assert data['bombardment_mode'] == 'multi point'
    assert data['min_dose'] == pytest.approx(2e14)  # reference spots excluded
    assert data['max_dose'] == pytest.approx(1e17)
    points = data['points']
    assert points[12]['name'] == 'Point13'
    assert points[12]['dose_wanted'] == pytest.approx(1e17)
    assert (points[0]['x'], points[0]['y']) == (0.32, 0.0)
    assert len(data['time']) == len(data['beam_current']) == 60
    assert data['time'][0] == 0 and data['time'][1] == 5
    labels = [f['label'] for f in data['figures']]
    assert labels == ['Bombarded positions', 'Beam current and pressure']
    assert data['samples'] == [
        {
            'm_def': data['samples'][0]['m_def'],
            'name': '2024_0250_1',
            'lab_id': '2024_0250_1',
            'reference': chip_ref('2024_0250_1'),
        }
    ]


def test_normalize_sets_method_for_chip_state(tmp_path, searches):
    from nomad_age.schema_packages.ion_bombardment_schema import AGE_IonBombardment

    upload = make_upload(tmp_path, LOG_2026)
    parse(upload, LOG_2026)
    entry = AGE_IonBombardment.m_from_dict(entry_data(upload, LOG_2026))
    archive = EntryArchive(data=entry, metadata=EntryMetadata())
    entry.normalize(archive, get_logger(__name__))
    assert entry.method == ION_BOMBARDMENT_METHOD == 'Helium Ion Bombardment'


def test_not_bombarded_point_and_2025_log(tmp_path, searches):
    upload = make_upload(tmp_path, LOG_2025, lmoke=('2024_0248_1',))
    parse(upload, LOG_2025)
    data = entry_data(upload, LOG_2025)
    assert data['number_of_points'] == 19
    assert data['number_bombarded'] == 18
    assert data['points'][-1]['bombarded'] is False
    assert data['number_reference_spots'] == 0
    assert data['min_dose'] == pytest.approx(1e14)
    assert data['max_dose'] == pytest.approx(1e16)
    assert data['samples'][0]['lab_id'] == '2024_0248_1'


def test_no_or_several_chips_link_nothing(tmp_path, searches, caplog, kwargs_logger):
    upload = make_upload(tmp_path, LOG_2026, lmoke=('2024_0250', '2024_0248_1'))
    with caplog.at_level(logging.WARNING):
        parse(upload, LOG_2026, logger=kwargs_logger)
    assert 'samples' not in entry_data(upload, LOG_2026)
    assert any('2 chips' in r.getMessage() for r in caplog.records)
    assert searches.calls == []


def test_missing_chip_is_reported_not_created(
    tmp_path, searches, caplog, kwargs_logger
):
    upload = make_upload(tmp_path, LOG_2026)
    searches.missing.add('2024_0250_1')
    with caplog.at_level(logging.WARNING):
        parse(upload, LOG_2026, logger=kwargs_logger)
    (sample,) = entry_data(upload, LOG_2026)['samples']
    assert 'reference' not in sample
    assert {p.name for p in upload.glob('*.archive.yaml')} == {
        f'{LOG_2026}.archive.yaml'
    }


def test_chip_chosen_in_gui_wins(tmp_path, searches, stored_archives):
    upload = make_upload(tmp_path, LOG_2026)
    parse(upload, LOG_2026)
    stored = entry_data(upload, LOG_2026)
    stored['samples'] = [
        {'name': '2024_0251_1', 'lab_id': '2024_0251_1', 'reference': chip_ref('x')}
    ]
    stored['ion_energy'] = 30.0
    with open(upload / f'{LOG_2026}.archive.yaml', 'w') as f:
        yaml.dump({'data': stored}, f)
    stored_archives({get_entry_id('test_upload', f'{LOG_2026}.archive.yaml'): stored})

    parse(upload, LOG_2026)

    data = entry_data(upload, LOG_2026)
    assert data['samples'][0]['lab_id'] == '2024_0251_1'
    assert data['ion_energy'] == 30.0


def test_unknown_version_keeps_raw_file_and_date(
    tmp_path, searches, caplog, kwargs_logger
):
    log = '20270101_090000_logger.txt'
    (tmp_path / log).write_text('Version: 2\nBeamCurrent; whatever\n')
    with caplog.at_level(logging.ERROR):
        archive = parse(tmp_path, log, logger=kwargs_logger)
    assert isinstance(archive.data, AGE_RawFile)
    data = entry_data(tmp_path, log)
    assert data['log_format_version'] == '2'
    assert data['name'] == 'IB_2027-01-01 09:00:00'
    assert 'points' not in data
    assert any('Unknown ISA log format' in r.getMessage() for r in caplog.records)
