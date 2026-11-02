import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext

from nomad_age.parsers.vsm_parser import VSMParser, parse_vsm_file
from nomad_age.schema_packages.age_schema import AGE_RawFile
from nomad_age.schema_packages.vsm_schema import AGE_VSM, branch_split
from nomad_age.utils import utils
from nomad_age.utils.utils import get_entry_id, get_hash_ref, get_reference

DATA = Path(__file__).parent.parent / 'data/vsm'
AS_MADE = '188225_VSM_2019_0333_1.asc'
AFTER_FC = '189171_VSM_2019_0333_1.asc'
AFTER_IB = '243514_VSM_2019_0333_1.asc'
COMMENTED = '284425_VSM_2020_0503_1.asc'
SAMPLES_UPLOAD = 'age_samples_upload'


def berlin_midnight(year, month, day):
    return utils.lab_time_to_utc(datetime(year, month, day))


@pytest.fixture
def searches(monkeypatch):
    """Lab ids of the sample searches; each finds the chip in the AGE Samples
    upload, unless its lab id is in `searches.missing`."""
    calls = []
    missing = set()

    def search(lab_id, user_id=None):
        calls.append(lab_id)
        if lab_id in missing:
            return SimpleNamespace(data=[])
        return SimpleNamespace(
            data=[{'upload_id': SAMPLES_UPLOAD, 'entry_id': f'chip_{lab_id}'}]
        )

    monkeypatch.setattr(utils, 'find_existing_AGE_sample', search)
    return SimpleNamespace(calls=calls, missing=missing)


def parse(upload, name, logger) -> EntryArchive:
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(upload)),
        metadata=EntryMetadata(mainfile=name, upload_id='test_upload'),
    )
    VSMParser().parse(str(upload / name), archive, logger)
    return archive


def entry_data(upload, name) -> dict:
    with open(upload / f'{name}.archive.yaml') as f:
        return yaml.safe_load(f)['data']


def warnings(caplog) -> list:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    'name,expected',
    [
        (
            AS_MADE,
            dict(
                db_charge_id=2669,
                db_chip_number=1,
                sample_state='as made',
                db_instrument_id=3,
                measurement_time=berlin_midnight(2019, 10, 22),
                user_id=26,
                sample_angle=0.0,
                comment=None,
                measurement_number=188225,
                sample='2019_0333_1',
            ),
        ),
        (
            AFTER_FC,
            dict(
                sample_state='after FC',
                measurement_time=berlin_midnight(2019, 10, 24),
                user_id=26,
                comment=None,
                measurement_number=189171,
            ),
        ),
        (
            AFTER_IB,
            dict(
                sample_state='after IB',
                measurement_time=berlin_midnight(2020, 9, 24),
                comment=None,
                measurement_number=243514,
            ),
        ),
        (
            COMMENTED,
            dict(
                db_charge_id=3237,
                db_chip_number=1,
                sample_state='as made',
                db_instrument_id=3,
                measurement_time=berlin_midnight(2021, 1, 28),
                comment='3 mum ps particles\nSample position: 7.9\n0 phase',
                user_id=31,
                sample_angle=0.0,
                measurement_number=284425,
                sample='2020_0503_1',
            ),
        ),
    ],
)
def test_header_values(name, expected, kwargs_logger):
    values = parse_vsm_file(str(DATA / name), kwargs_logger)

    assert {key: values.get(key) for key in expected} == expected


@pytest.mark.parametrize(
    'name,left,right',
    [
        (AS_MADE, (-7.004036, 3.836177), None),
        (AFTER_FC, (-12.308475, 3.519975), None),
        (AFTER_IB, (-9.644881, 2.903511), (6.621968, 2.513025)),
    ],
)
def test_fits_give_loop_shift_hc_and_exchange_bias(name, left, right, kwargs_logger):
    values = parse_vsm_file(str(DATA / name), kwargs_logger)

    for side, fit in (('left', left), ('right', right)):
        found = [values.get(f'{q}_{side}') for q in ('loop_shift', 'HC', 'HEB')]
        if fit is None:  # single-loop fit: right slot 0, 0 means not fitted
            assert found == [None, None, None]
        else:
            shift, hc = fit
            assert found == [shift, hc, pytest.approx(-shift)]


@pytest.mark.parametrize(
    'name,rows', [(AS_MADE, 200), (AFTER_FC, 200), (AFTER_IB, 80), (COMMENTED, 322)]
)
def test_data_rows_and_branch_split(name, rows, kwargs_logger):
    values = parse_vsm_file(str(DATA / name), kwargs_logger)

    columns = [values[q] for q in ('field_voltage', 'signal', 'magnetic_field')]
    assert [len(column) for column in columns] == [rows] * 3
    field = np.array(values['magnetic_field'])
    split = branch_split(field)
    assert field[split] == field.min()
    # the loop starts at +Hmax and comes back there
    assert field[0] > 0 > field[split] and field[-1] > 0


def test_first_data_row():
    values = parse_vsm_file(str(DATA / AS_MADE), logging.getLogger())
    first = [values[q][0] for q in ('field_voltage', 'signal', 'magnetic_field')]
    assert first == [0.057, 5.548, 45.705]


def test_figure_has_descending_and_ascending_branch():
    values = parse_vsm_file(str(DATA / AS_MADE), logging.getLogger())
    entry = AGE_VSM(technique='VSM', **values)

    figure = entry.magnetisation_figure()

    descending, ascending = figure['data']
    split = branch_split(values['magnetic_field']) + 1
    assert descending['x'] == values['magnetic_field'][:split]
    assert ascending['x'] == values['magnetic_field'][split:]
    assert descending['y'] == values['signal'][:split]
    assert figure['layout']['title']['text'] == 'VSM, 2019-10-22, as made'
    assert figure['layout']['yaxis']['title']['text'] == 'Signal [V]'


@pytest.fixture
def upload(tmp_path, searches):
    for name in (AS_MADE, AFTER_IB):
        shutil.copy(DATA / name, tmp_path / name)
    return tmp_path


def test_processed_entry_is_a_vsm_measurement_of_its_chip(
    upload, process_entry, kwargs_logger
):
    raw = parse(upload, AS_MADE, kwargs_logger).data

    assert isinstance(raw, AGE_RawFile)
    assert raw.file_type == 'VSM measurement'
    data = entry_data(upload, AS_MADE)
    assert data['raw_file'] == get_hash_ref('test_upload', AS_MADE)
    chip_ref = f'{get_reference(SAMPLES_UPLOAD, "chip_2019_0333_1")}#data'
    samples = [{k: v for k, v in s.items() if k != 'm_def'} for s in data['samples']]
    assert samples == [
        {'name': '2019_0333_1', 'lab_id': '2019_0333_1', 'reference': chip_ref}
    ]

    entry = process_entry(upload, f'{AS_MADE}.archive.yaml', logger=kwargs_logger)
    vsm = entry.data
    assert vsm.technique == 'VSM'
    assert vsm.name == 'VSM 188225 2019_0333_1 as made'
    assert vsm.measurement_time == datetime(2019, 10, 21, 22, tzinfo=timezone.utc)
    assert vsm.HEB_left.to('kA/m').magnitude == pytest.approx(7.004036)
    assert vsm.HC_right is None
    (figure,) = vsm.figures
    assert len(figure.figure['data']) == 2


def test_missing_chip_is_reported_not_created(
    upload, searches, process_entry, caplog, kwargs_logger
):
    searches.missing.add('2019_0333_1')

    with caplog.at_level(logging.WARNING):
        parse(upload, AFTER_IB, kwargs_logger)
        entry = process_entry(upload, f'{AFTER_IB}.archive.yaml', logger=kwargs_logger)

    assert entry.data.samples[0].lab_id == '2019_0333_1'
    assert entry.data.samples[0].reference is None
    assert entry.data.figures
    assert {p.name for p in upload.glob('*.archive.yaml')} == {
        f'{AFTER_IB}.archive.yaml'
    }
    (warning,) = warnings(caplog)
    assert '2019_0333_1' in warning and 'AGE Samples upload' in warning


def test_reparse_keeps_the_entry_file(
    upload, process_entry, stored_archives, kwargs_logger
):
    parse(upload, AS_MADE, kwargs_logger)
    entry_file = upload / f'{AS_MADE}.archive.yaml'
    text = entry_file.read_text()
    processed = process_entry(upload, entry_file.name).data.m_to_dict()
    assert processed['figures'] and processed['technique'] == 'VSM'
    stored_archives({get_entry_id('test_upload', entry_file.name): processed})

    parse(upload, AS_MADE, kwargs_logger)

    # the plot is made on processing; a stored one is not written back
    assert entry_file.read_text() == text


def test_bad_numbers_and_short_data_warn(tmp_path, caplog, kwargs_logger):
    lines = (DATA / AS_MADE).read_bytes().split(b'\r\n')
    lines[10] = b'-7,0x4036\t\t\t'  # Hys_HEB_links
    lines[14] = b'abc\t\t\t'  # Hys_Winkel
    name = '1_VSM_2019_0333_1.asc'
    (tmp_path / name).write_bytes(b'\r\n'.join(lines[:20]))

    with caplog.at_level(logging.WARNING):
        values = parse_vsm_file(str(tmp_path / name), kwargs_logger)

    assert values.get('loop_shift_left') is None
    assert values.get('HEB_left') is None
    assert values['HC_left'] == 3.836177
    assert values.get('sample_angle') is None
    assert values['user_id'] == 26
    assert len(values['magnetic_field']) == 2
    assert AGE_VSM(**values).magnetisation_figure() is None
    found = warnings(caplog)
    assert any('Hys_HEB_links' in w for w in found)
    assert any('Hys_Winkel' in w for w in found)
    assert any('only 2 data rows' in w for w in found)


def test_comment_zero_means_no_comment(tmp_path, kwargs_logger):
    lines = (DATA / AS_MADE).read_bytes().split(b'\r\n')
    lines[12] = b'0\t\t\t'  # Hys_Kom as older program versions write it
    name = '2_VSM_2019_0333_1.asc'
    (tmp_path / name).write_bytes(b'\r\n'.join(lines))

    values = parse_vsm_file(str(tmp_path / name), kwargs_logger)

    assert 'comment' not in values
    assert values['user_id'] == 26
