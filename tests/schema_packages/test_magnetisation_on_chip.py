import logging

import pytest
import yaml

from nomad_age.schema_packages.age_schema import MAGNETISATION_FIGURE_LABEL
from nomad_age.utils.chip_refresh import workflow_id
from nomad_age.utils.utils import AGE_MAGNETISATION_SCHEMA, as_utc, parse_reference

UPLOAD_ID = 'test_upload'  # of the chip, see process_entry
MOKE_UPLOAD = 'moke_upload'
CHIP = 'chip'
CHIP_FILE = 'chip.archive.yaml'
LMOKE = 'nomad_age.schema_packages.LMOKEandVMOKESchema.LMOKEandVMOKESchema'
FIELD_COOLING = 'nomad_age.schema_packages.field_cooling_schema.AGE_FieldCooling'

MEASUREMENTS = {
    'old': {
        'measurement_time': '2026-02-16T10:11:20+00:00',
        'sample_state': 'as made',
        'magnetic_field': [-10.0, 0.0, 10.0],
        'magnetization': [-1.0, 0.1, 1.0],
    },
    'new': {
        'measurement_time': '2026-03-02T08:30:00+00:00',
        'sample_state': 'after FC',
        'magnetic_field': [-20.0, 0.0, 20.0],
        'magnetization': [-1.0, -0.5, 1.0],
    },
}


def measurement_archives() -> dict:
    return {
        (MOKE_UPLOAD, entry_id): {'m_def': LMOKE, 'technique': 'L-MOKE', **data}
        for entry_id, data in MEASUREMENTS.items()
    }


def index_doc(entry_id, schemas, target=CHIP, **search_values) -> dict:
    """Search index document of an entry of the moke upload that references
    `target`, with the data of a magnetisation measurement in `search_values`."""
    return {
        'entry_id': entry_id,
        'upload_id': MOKE_UPLOAD,
        'entry_references': [{'target_entry_id': target}],
        'section_defs': [{'definition_qualified_name': s} for s in schemas],
        'search_quantities': [
            {
                'definition': f'{AGE_MAGNETISATION_SCHEMA}.{name}',
                'path_archive': f'data.{name}',
                key: value,
            }
            for name, key, value in (
                ('measurement_time', 'datetime_value', search_values.get('time')),
                ('technique', 'str_value', search_values.get('technique')),
            )
            if value is not None
        ],
    }


@pytest.fixture
def index(fake_index):
    """Two L-MOKE measurements and a field cooling reference the chip; an L-MOKE
    measurement of another chip is newer."""
    lmoke = [LMOKE, AGE_MAGNETISATION_SCHEMA]
    fake_index.docs = [
        index_doc(
            entry_id,
            lmoke,
            time=data['measurement_time'],
            technique='L-MOKE',
        )
        for entry_id, data in MEASUREMENTS.items()
    ]
    fake_index.docs += [
        index_doc('cooling', [FIELD_COOLING]),
        index_doc('other', lmoke, target='other_chip', time='2026-05-01T00:00:00Z'),
    ]
    return fake_index


def write_chip(directory, **data):
    chip = {
        'm_def': 'nomad_age.schema_packages.age_schema.AGE_Sample',
        'name': '2023_0418_1',
        'lab_id': '2023_0418_1',
        **data,
    }
    with open(directory / CHIP_FILE, 'w') as f:
        yaml.dump({'data': chip}, f)


def save_in_eln(directory, chip):
    """Write the chip back to its file, as the ELN saves it, with all values."""
    with open(directory / CHIP_FILE, 'w') as f:
        yaml.dump({'data': chip.m_to_dict(with_root_def=True)}, f)


@pytest.fixture
def process_chip(tmp_path, process_entry, stored_archives_context):
    context = stored_archives_context(tmp_path, measurement_archives())

    def process(logger=None):
        return process_entry(
            tmp_path, CHIP_FILE, logger=logger, context=context, entry_id=CHIP
        ).data

    return process


def magnetisation_figures(chip) -> list:
    return [f for f in chip.figures if f.label == MAGNETISATION_FIGURE_LABEL]


def test_chip_shows_its_newest_magnetisation_measurement(tmp_path, index, process_chip):
    write_chip(tmp_path)

    chip = process_chip()

    (figure,) = chip.figures
    assert figure.label == MAGNETISATION_FIGURE_LABEL
    (trace,) = figure.figure['data']
    assert list(trace['x']) == MEASUREMENTS['new']['magnetic_field']
    assert list(trace['y']) == MEASUREMENTS['new']['magnetization']
    # in lab time
    assert figure.figure['layout']['title']['text'] == (
        'L-MOKE, 2026-03-02 09:30, after FC'
    )
    shown = parse_reference(chip.latest_magnetisation_measurement)
    assert shown == (MOKE_UPLOAD, 'new')
    assert chip.latest_magnetisation_time == as_utc(
        MEASUREMENTS['new']['measurement_time']
    )
    assert chip.latest_magnetisation_technique == 'L-MOKE'


def test_processing_a_saved_chip_replaces_its_magnetisation_plot(
    tmp_path, index, process_chip
):
    write_chip(tmp_path)
    chip = process_chip()
    chip.figures.append(type(chip.figures[0])(label='Microscope image', figure={}))
    save_in_eln(tmp_path, chip)

    chip = process_chip()
    save_in_eln(tmp_path, chip)
    chip = process_chip()

    assert [f.label for f in chip.figures] == [
        'Microscope image',
        MAGNETISATION_FIGURE_LABEL,
    ]
    assert parse_reference(chip.latest_magnetisation_measurement)[1] == 'new'


def test_chip_without_measurements_shows_none(tmp_path, index, process_chip):
    write_chip(tmp_path)
    chip = process_chip()
    save_in_eln(tmp_path, chip)
    # all measurements deleted
    index.docs = [d for d in index.docs if d['entry_id'] not in MEASUREMENTS]

    chip = process_chip()

    assert not chip.figures
    assert chip.latest_magnetisation_measurement is None
    assert chip.latest_magnetisation_time is None
    assert chip.latest_magnetisation_technique is None


def test_unloadable_measurement_keeps_the_plot(
    tmp_path, index, process_chip, caplog, kwargs_logger
):
    write_chip(tmp_path)
    save_in_eln(tmp_path, process_chip())
    index.docs.append(
        index_doc('lost', [LMOKE, AGE_MAGNETISATION_SCHEMA], time='2026-04-01T00:00Z')
    )

    with caplog.at_level(logging.WARNING):
        chip = process_chip(logger=kwargs_logger)

    assert len(magnetisation_figures(chip)) == 1
    assert parse_reference(chip.latest_magnetisation_measurement)[1] == 'new'
    (warning,) = [r.getMessage() for r in caplog.records]
    assert 'newest magnetisation plot' in warning


def test_refresh_waits_for_its_upload(tmp_path, index, process_chip, temporal):
    write_chip(tmp_path)
    temporal.workflow_id = workflow_id(CHIP, MOKE_UPLOAD)
    temporal.busy_uploads.add(MOKE_UPLOAD)

    process_chip()

    (started,) = temporal.started
    assert started['id'] == workflow_id(CHIP, MOKE_UPLOAD, wait=1)
    assert started['start_delay'].total_seconds() == 30
    assert (started['arg'].upload_id, started['arg'].entry_id) == (UPLOAD_ID, CHIP)

    # the upload is done (and indexed)
    temporal.workflow_id = started['id']
    temporal.busy_uploads.clear()
    process_chip()
    assert len(temporal.started) == 1
