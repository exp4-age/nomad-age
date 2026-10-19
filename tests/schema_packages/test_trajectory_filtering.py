import logging

import yaml
from nomad.datamodel.context import ClientContext

from nomad_age.schema_packages.particle_tracking_schema import AGE_TrajectoryFiltering
from nomad_age.utils.utils import get_entry_id, get_hash_ref

UPLOAD_ID = 'test_upload'
FILTER = {
    'm_def': (
        'nomad_age.schema_packages.particle_tracking_schema.AGE_TrajectoryFiltering'
    ),
    'name': 'Trajectory filter',
    'min_frames': 20,
    'min_net_displacement': 5.5,
    'displacement_axes': ['x', 'y'],
    'software': 'trackpy 0.7',
    'script_file': 'scripts/filtering.py',
}


def write_upload(tmp_path, filter_data=FILTER):
    """An upload with the entry files of two tracks, a filtered-only recording,
    a video and the filter entry."""
    for entry_file in (
        'a_trajs.h5.archive.yaml',
        'day2/b_trajs.h5.archive.yaml',
        'day2/c_filtered_trajs.h5.archive.yaml',
        'a.h5.archive.yaml',
    ):
        (tmp_path / entry_file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / entry_file).write_text('data: {}\n')
    with open(tmp_path / 'filter.archive.yaml', 'w') as f:
        yaml.dump({'data': filter_data}, f)


def inputs(archive) -> list:
    """Inputs of a filter entry; references in one form, as NOMAD serializes
    references read from files with #/data instead of #data."""
    return [
        {**i, 'reference': i['reference'].replace('#/data', '#data')}
        for i in archive.data.m_to_dict().get('inputs', [])
    ]


def test_filter_parameters_round_trip_from_yaml(tmp_path, process_entry):
    write_upload(tmp_path)

    entry = process_entry(tmp_path, 'filter.archive.yaml').data

    assert isinstance(entry, AGE_TrajectoryFiltering)
    assert entry.m_def.label == 'Trajectory filtering'
    assert entry.min_frames == 20
    assert entry.min_net_displacement == 5.5
    assert list(entry.displacement_axes) == ['x', 'y']
    assert entry.software == 'trackpy 0.7'
    assert entry.script_file == 'scripts/filtering.py'


def test_filter_inputs_default_to_the_tracks_entries_of_the_upload(
    tmp_path, process_entry, entry_references
):
    write_upload(tmp_path)

    archive = process_entry(tmp_path, 'filter.archive.yaml')

    tracks = ['a_trajs.h5.archive.yaml', 'day2/b_trajs.h5.archive.yaml']
    assert inputs(archive) == [
        {'name': 'a_trajs.h5', 'reference': get_hash_ref(UPLOAD_ID, tracks[0])},
        {'name': 'b_trajs.h5', 'reference': get_hash_ref(UPLOAD_ID, tracks[1])},
    ]
    # each tracks entry lists the filter as referencing it, also in the workflow
    references = entry_references(archive)
    for entry_file in tracks:
        entry_id = get_entry_id(UPLOAD_ID, entry_file)
        assert ('data.inputs.reference', entry_id) in references
        assert ('workflow2.inputs.section', entry_id) in references


def test_explicit_filter_inputs_are_kept(tmp_path, process_entry):
    reference = get_hash_ref(UPLOAD_ID, 'day2/b_trajs.h5.archive.yaml')
    write_upload(
        tmp_path, {**FILTER, 'inputs': [{'name': 'b', 'reference': reference}]}
    )

    archive = process_entry(tmp_path, 'filter.archive.yaml')

    assert inputs(archive) == [{'name': 'b', 'reference': reference}]


def test_filter_without_access_to_the_upload_files_is_processed(
    tmp_path, process_entry, caplog
):
    write_upload(tmp_path)

    with caplog.at_level(logging.WARNING):
        archive = process_entry(
            tmp_path, 'filter.archive.yaml', context=ClientContext(local_dir=None)
        )

    assert inputs(archive) == []
    assert archive.data.min_frames == 20
    assert any('not linked' in r.getMessage() for r in caplog.records)
