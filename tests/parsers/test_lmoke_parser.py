import logging
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext

from nomad_age.parsers.LMOKEparser import LMOKEParser
from nomad_age.schema_packages.age_schema import AGE_MagnetisationMeasurement
from nomad_age.utils import utils
from nomad_age.utils.utils import get_reference

MAINFILE = (
    Path(__file__).parent.parent / 'data/2023_0325_1_LMOKE_2023-11-07_14-09-15.txt'
)
SAMPLES_UPLOAD = 'age_samples_upload'


@pytest.fixture
def searches(monkeypatch):
    """Sample searches find the chip in the AGE Samples upload, unless its lab id
    is in `searches.missing`."""
    missing = set()

    def search(lab_id, user_id=None):
        if lab_id in missing:
            return SimpleNamespace(data=[])
        hit = {'upload_id': SAMPLES_UPLOAD, 'entry_id': f'chip_{lab_id}'}
        return SimpleNamespace(data=[hit])

    monkeypatch.setattr(utils, 'find_existing_AGE_sample', search)
    return SimpleNamespace(missing=missing)


@pytest.fixture
def upload(tmp_path, monkeypatch):
    """Upload directory with the LMOKE file; the parser writes a temporary data
    file to the working directory."""
    shutil.copy(MAINFILE, tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def parse(upload, logger=None) -> EntryArchive:
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(upload)),
        metadata=EntryMetadata(mainfile=MAINFILE.name, upload_id='moke_upload'),
    )
    LMOKEParser().parse(
        str(upload / MAINFILE.name), archive, logger or logging.getLogger()
    )
    return archive


def test_lmoke_parser(upload, searches):
    data = parse(upload).data

    assert data.user == 'Arne Vereijken'
    assert data.sample == '2023_0325_1'
    assert data.device == 'LMOKE'


def test_measurement_links_its_chip_of_the_samples_upload(upload, searches):
    data = parse(upload).data

    assert isinstance(data, AGE_MagnetisationMeasurement)
    assert [sample.m_to_dict() for sample in data.samples] == [
        {
            'name': '2023_0325_1',
            'lab_id': '2023_0325_1',
            'reference': f'{get_reference(SAMPLES_UPLOAD, "chip_2023_0325_1")}#data',
        }
    ]
    # the file name holds the lab time
    assert data.measurement_time.utcoffset() is not None
    assert data.measurement_time == datetime(
        2023, 11, 7, 14, 9, 15, tzinfo=ZoneInfo('Europe/Berlin')
    )
    assert data.technique == 'L-MOKE'


def test_missing_chip_is_reported_not_created(upload, searches, caplog, kwargs_logger):
    searches.missing.add('2023_0325_1')

    with caplog.at_level(logging.WARNING):
        data = parse(upload, logger=kwargs_logger).data

    assert [sample.m_to_dict() for sample in data.samples] == [
        {'name': '2023_0325_1', 'lab_id': '2023_0325_1'}
    ]
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert '2023_0325_1' in warning.getMessage()
    assert {path.name for path in upload.iterdir()} == {
        MAINFILE.name,
        'tmp_data_file.txt',  # the parser's temporary data file
    }


def test_fields_are_stored_in_ka_per_m(upload, searches):
    """The L-MOKE log gives H in kA/m; the stored values keep these numbers."""
    data = parse(upload).data
    raw = [
        float(line.split()[0])
        for line in MAINFILE.read_text().splitlines()
        if line.strip() and not line.startswith('#')
    ]

    assert str(data.magnetic_field.units) == 'kiloampere / meter'
    assert data.magnetic_field.magnitude[0] == pytest.approx(raw[0])
    assert data.H_start.to('kA/m').magnitude == pytest.approx(data.H_start.magnitude)
    figure = data.magnetisation_figure()
    assert figure['layout']['xaxis']['title']['text'] == 'H [kA/m]'
    assert figure['data'][0]['x'][0] == pytest.approx(raw[0])
