import logging
from datetime import datetime, timezone

import yaml
from nomad.datamodel import EntryArchive

UPLOAD_ID = 'test_upload'  # of the entry that process_entry processes
SCHEMA = 'nomad_age.schema_packages.age_schema'


def reference(entry_id):
    return f'../uploads/{UPLOAD_ID}/archive/{entry_id}#data'


ARCHIVES = {
    (UPLOAD_ID, 'chip'): {
        'm_def': f'{SCHEMA}.AGE_Sample',
        'name': '2023_0418',
        'lab_id': '2023_0418',
        'description': 'Si / CoFe 10 / IrMn 30 / Cu 10',
    },
    (UPLOAD_ID, 'pmma2'): {
        'm_def': f'{SCHEMA}.AGE_CoatedSample',
        'lab_id': '2023_0418_PMMA2',
        'chip': reference('chip'),
        'spacer_thickness': 3369.25,
    },
}

COATED_CHIP = {
    'm_def': f'{SCHEMA}.AGE_CoatedSample',
    'name': '2023_0418 PMMA 2',
    'lab_id': '2023_0418_PMMA2',
    'chip': reference('chip'),
    'spacer_thickness': 3369.25,
    'spacer_thickness_uncertainty': 36.9,
    'thickness_method': 'profilometry (scratch)',
    'n_thickness_points': 4,
    'date_coated': '2025-03-12T00:00:00+00:00',
}

SPIN_COATING = {
    'm_def': f'{SCHEMA}.AGE_SpinCoating',
    'name': 'PMMA 2 on 2023_0418',
    'datetime': '2025-03-12T10:30:00+00:00',
    'chip': reference('chip'),
    'coated_sample': reference('pmma2'),
    'resist': 'PMMA 950K A11',
    'spin_speed': 3000.0,
    'acceleration': 1000.0,
    'spin_time': 60.0,
    'n_layers': 1,
    'bake_temperature': 180.0,
    'bake_time': 120.0,
}


def write_entry(directory, entry_file, data):
    with open(directory / entry_file, 'w') as f:
        yaml.dump({'data': data}, f)


def test_coated_chip_round_trip(
    tmp_path, process_entry, stored_archives_context, entry_references
):
    write_entry(tmp_path, 'pmma2.archive.yaml', COATED_CHIP)
    context = stored_archives_context(tmp_path, ARCHIVES)

    archive = process_entry(tmp_path, 'pmma2.archive.yaml', context=context)
    data = archive.data

    assert data.spacer_material == 'PMMA'  # default
    assert data.spacer_thickness.to('nm').magnitude == 3369.25
    assert data.spacer_thickness_uncertainty.to('nm').magnitude == 36.9
    assert data.thickness_method == 'profilometry (scratch)'
    assert data.n_thickness_points == 4
    assert data.date_coated == datetime(2025, 3, 12, tzinfo=timezone.utc)
    assert data.date_removed is None
    assert data.chip.name == '2023_0418'
    # recordings find it by lab_id
    assert archive.results.eln.lab_ids == ['2023_0418_PMMA2']
    assert ('data.chip', 'chip') in entry_references(archive)

    stored = archive.m_to_dict()
    again = EntryArchive.m_from_dict(stored, m_context=context)
    assert again.m_to_dict() == stored
    assert again.data.spacer_thickness == data.spacer_thickness


def test_spin_coating_links_chip_to_coated_chip(
    tmp_path, process_entry, stored_archives_context, entry_references, caplog
):
    write_entry(tmp_path, 'coating.archive.yaml', SPIN_COATING)
    context = stored_archives_context(tmp_path, ARCHIVES)

    archive = process_entry(tmp_path, 'coating.archive.yaml', context=context)
    data = archive.data

    assert data.method == 'Spin coating'
    assert [(s.name, s.lab_id) for s in data.samples] == [
        ('Chip', '2023_0418'),
        ('Coated chip', '2023_0418_PMMA2'),
    ]
    workflow = archive.workflow2
    assert [(link.name, link.section.lab_id) for link in workflow.inputs] == [
        ('Chip', '2023_0418')
    ]
    assert [(link.name, link.section.lab_id) for link in workflow.outputs] == [
        ('Coated chip', '2023_0418_PMMA2')
    ]
    references = entry_references(archive)
    assert {('data.chip', 'chip'), ('data.coated_sample', 'pmma2')} <= references
    assert ('data.samples.reference', 'pmma2') in references
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    # parameters keep their units, the bake temperature its offset unit
    stored = archive.m_to_dict()['data']
    assert stored['spin_speed'] == 3000.0
    assert stored['bake_temperature'] == 180.0
    assert data.spin_speed.to('1/s').magnitude == 50.0
    assert data.bake_temperature.to('kelvin').magnitude == 453.15
    assert data.datetime == datetime(2025, 3, 12, 10, 30, tzinfo=timezone.utc)


def test_spin_coating_with_unloadable_coated_chip_warns_only(
    tmp_path, process_entry, stored_archives_context, caplog
):
    write_entry(
        tmp_path,
        'coating.archive.yaml',
        {**SPIN_COATING, 'coated_sample': reference('deleted')},
    )
    context = stored_archives_context(tmp_path, ARCHIVES)

    data = process_entry(tmp_path, 'coating.archive.yaml', context=context).data

    assert [(s.name, s.lab_id) for s in data.samples] == [
        ('Chip', '2023_0418'),
        ('Coated chip', None),
    ]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert 'Coated chip of the spin coating not loaded' in warnings[0]
