import logging

import pytest
import yaml

UPLOAD_ID = 'test_upload'  # of the entry that process_entry processes
PARTICLES_UPLOAD_ID = 'particles_upload'
SCHEMA = 'nomad_age.schema_packages'


def reference(upload_id, entry_id):
    return f'../uploads/{upload_id}/archive/{entry_id}#data'


ARCHIVES = {
    (PARTICLES_UPLOAD_ID, 'm270'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_Particles',
        'name': 'M270 batch 3',
        'lab_id': 'M270-2024-03',
    },
    (UPLOAD_ID, 'chip'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_Sample',
        'name': '2023_0418',
        'lab_id': '2023_0418',
    },
    (UPLOAD_ID, 'unnamed_chip'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_Sample',
        'lab_id': '2023_0325_1',
    },
    (UPLOAD_ID, 'objective'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_Objective',
        'name': 'Objective 20x',
    },
    # coated chips are made in another upload than their chip
    (PARTICLES_UPLOAD_ID, 'pmma2'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_CoatedSample',
        'name': '2023_0418 PMMA 2',
        'lab_id': '2023_0418_PMMA2',
        'chip': reference(UPLOAD_ID, 'chip'),
        'spacer_thickness': 3369.25,
        'spacer_thickness_uncertainty': 36.9,
    },
    (PARTICLES_UPLOAD_ID, 'pmma3'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_CoatedSample',
        'lab_id': '2023_0418_PMMA3',
        'chip': reference(UPLOAD_ID, 'chip'),
        'spacer_thickness': 1210.0,
    },
    (PARTICLES_UPLOAD_ID, 'lost_chip'): {
        'm_def': f'{SCHEMA}.age_schema.AGE_CoatedSample',
        'lab_id': '2023_0325_1_PMMA1',
        'chip': reference(UPLOAD_ID, 'deleted'),
        'spacer_thickness': 980.0,
    },
}

SAMPLES = [
    # particles in another upload of the user
    {'lab_id': 'M270-2024-03', 'reference': reference(PARTICLES_UPLOAD_ID, 'm270')},
    {'lab_id': '2023_0418', 'reference': reference(UPLOAD_ID, 'chip')},
    {'lab_id': '2023_0325_1', 'reference': reference(UPLOAD_ID, 'unnamed_chip')},
    # the same particles twice
    {'name': 'beads', 'reference': reference(PARTICLES_UPLOAD_ID, 'm270')},
    # neither particles nor chip
    {'lab_id': 'OBJ-20x', 'reference': reference(UPLOAD_ID, 'objective')},
]

COATED_CHIP = {
    'lab_id': '2023_0418_PMMA2',
    'reference': reference(PARTICLES_UPLOAD_ID, 'pmma2'),
}

RECORDINGS = ['AGE_ParticleTracking', 'AGE_ParticleTransportVideo', 'AGE_FocusSweep']


def write_entry(directory, entry_file, entry_type, **data):
    data = {'m_def': f'{SCHEMA}.particle_tracking_schema.{entry_type}', **data}
    with open(directory / entry_file, 'w') as f:
        yaml.dump({'data': data}, f)


def names(samples) -> list:
    return [sample.name for sample in samples]


def warnings(caplog) -> list:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def errors(caplog) -> list:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize('entry_type', RECORDINGS)
def test_samples_are_listed_as_particles_and_chips(
    tmp_path, process_entry, stored_archives_context, caplog, entry_type
):
    write_entry(tmp_path, 'rec.archive.yaml', entry_type, name='rec', samples=SAMPLES)
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'rec.archive.yaml', context=context).data

    assert names(data.particles) == ['M270 batch 3']  # the name of the entry
    assert names(data.chips) == ['2023_0418', '2023_0325_1']  # lab_id if unnamed
    assert data.spacer_thickness is None  # no coated chip
    assert not warnings(caplog)


@pytest.mark.parametrize('entry_type', RECORDINGS)
def test_coated_chip_lists_its_chip_and_spacer_thickness(
    tmp_path, process_entry, stored_archives_context, caplog, entry_type
):
    samples = [SAMPLES[0], COATED_CHIP]
    write_entry(tmp_path, 'rec.archive.yaml', entry_type, name='rec', samples=samples)
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'rec.archive.yaml', context=context).data

    assert names(data.particles) == ['M270 batch 3']
    assert names(data.chips) == ['2023_0418']  # the chip, not the coated chip
    assert data.spacer_thickness.to('nm').magnitude == 3369.25
    assert not warnings(caplog)


def test_coated_chip_and_its_chip_list_the_chip_once(
    tmp_path, process_entry, stored_archives_context, caplog
):
    samples = [SAMPLES[1], COATED_CHIP]
    write_entry(tmp_path, 'rec.archive.yaml', 'AGE_ParticleTracking', samples=samples)
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'rec.archive.yaml', context=context).data

    assert names(data.chips) == ['2023_0418']
    assert data.spacer_thickness.to('nm').magnitude == 3369.25
    assert not warnings(caplog)


def test_coated_chips_of_different_thickness_give_the_first_with_a_warning(
    tmp_path, process_entry, stored_archives_context, caplog
):
    samples = [
        COATED_CHIP,
        {
            'lab_id': '2023_0418_PMMA3',
            'reference': reference(PARTICLES_UPLOAD_ID, 'pmma3'),
        },
    ]
    write_entry(tmp_path, 'rec.archive.yaml', 'AGE_ParticleTracking', samples=samples)
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'rec.archive.yaml', context=context).data

    assert names(data.chips) == ['2023_0418']
    assert data.spacer_thickness.to('nm').magnitude == 3369.25
    assert len(warnings(caplog)) == 1
    assert (
        '2023_0418_PMMA2: 3369.25 nm, 2023_0418_PMMA3: 1210 nm' in warnings(caplog)[0]
    )


def test_coated_chip_whose_chip_cannot_be_loaded_is_listed_by_its_lab_id(
    tmp_path, process_entry, stored_archives_context, caplog
):
    samples = [
        {
            'lab_id': '2023_0325_1_PMMA1',
            'reference': reference(PARTICLES_UPLOAD_ID, 'lost_chip'),
        }
    ]
    write_entry(tmp_path, 'rec.archive.yaml', 'AGE_ParticleTracking', samples=samples)
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'rec.archive.yaml', context=context).data

    assert names(data.chips) == ['2023_0325_1_PMMA1']
    assert data.spacer_thickness.to('nm').magnitude == 980.0
    assert not errors(caplog)
    assert len(warnings(caplog)) == 1
    assert 'Chip of sample 2023_0325_1_PMMA1' in warnings(caplog)[0]


def test_samples_that_cannot_be_loaded_are_left_out_with_a_warning(
    tmp_path, process_entry, stored_archives_context, caplog
):
    samples = [
        SAMPLES[0],
        # e.g. deleted, or in an upload that the server cannot read
        {'lab_id': 'M450-2023-01', 'reference': reference(UPLOAD_ID, 'deleted')},
        # its lab_id was not found
        {'lab_id': '2023_9999'},
        # a coated chip that was deleted
        {'lab_id': '2023_0418_PMMA9', 'reference': reference(UPLOAD_ID, 'deleted')},
    ]
    write_entry(
        tmp_path,
        'rec.archive.yaml',
        'AGE_ParticleTracking',
        name='rec',
        samples=samples,
    )
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'rec.archive.yaml', context=context).data

    assert names(data.particles) == ['M270 batch 3']
    assert names(data.chips) == []
    assert data.spacer_thickness is None
    assert not errors(caplog)
    assert len(warnings(caplog)) == 3
    assert 'M450-2023-01' in warnings(caplog)[0]
    assert '2023_9999' in warnings(caplog)[1]
    assert '2023_0418_PMMA9' in warnings(caplog)[2]


def test_values_from_samples_are_recomputed_on_each_normalize(
    tmp_path, process_entry, stored_archives_context
):
    # e.g. a save in the GUI wrote them before samples were edited
    write_entry(
        tmp_path,
        'rec.archive.yaml',
        'AGE_ParticleTransportVideo',
        name='rec',
        samples=[SAMPLES[0], COATED_CHIP],
        particles=[{'name': 'M450 batch 1'}],
        chips=[{'name': '2023_0325_1'}],
        spacer_thickness=1210.0,
    )
    logger = logging.getLogger(__name__)
    context = stored_archives_context(tmp_path, ARCHIVES)
    archive = process_entry(tmp_path, 'rec.archive.yaml', logger, context)

    assert names(archive.data.particles) == ['M270 batch 3']
    assert names(archive.data.chips) == ['2023_0418']
    assert archive.data.spacer_thickness.to('nm').magnitude == 3369.25

    archive.data.normalize(archive, logger)

    assert names(archive.data.particles) == ['M270 batch 3']
    assert names(archive.data.chips) == ['2023_0418']
    assert archive.data.spacer_thickness.to('nm').magnitude == 3369.25

    archive.data.m_remove_sub_section(type(archive.data).samples, 1)  # coated chip
    archive.data.normalize(archive, logger)

    assert names(archive.data.particles) == ['M270 batch 3']
    assert names(archive.data.chips) == []
    assert archive.data.spacer_thickness is None
