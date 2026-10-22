import base64
import hashlib
import io
import logging
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext
from nomad.datamodel.metainfo.plot import PlotlyFigure
from PIL import Image

from nomad_age.parsers import (
    focus_sweep_parser_entry_point,
    particle_tracking_parser_entry_point,
    particle_transport_video_parser_entry_point,
)
from nomad_age.parsers.particle_tracking_parser import (
    MAX_PREVIEW_WIDTH,
    FocusSweepParser,
    ParticleTrackingParser,
    ParticleTransportVideoParser,
    build_particle_tracking_entry,
    build_video_entry,
    chip_ids_from_filename,
    find_recording_files,
    guess_illumination,
    parse_timestamp,
    plot_external_field,
    plot_frame,
    plot_trajectories,
    share_with_tracks,
    time_from_filename,
)
from nomad_age.schema_packages import particle_tracking_schema
from nomad_age.schema_packages.age_schema import AGE_Particles, AGE_RawFile, AGE_Sample
from nomad_age.schema_packages.particle_tracking_schema import (
    FROM_SAMPLES,
    AGE_FocusSweep,
    AGE_ParticleTracking,
    AGE_ParticleTransportVideo,
)
from nomad_age.utils import utils
from nomad_age.utils.utils import (
    AGE_PARTICLES_SCHEMA,
    get_entry_id,
    get_hash_ref,
    merge_stored_values,
    parse_reference,
    user_editable_keys,
)

FILTERED_KEYS = {
    'filtered_tracks_file',
    'n_particles_filtered',
    'n_localizations_filtered',
}

# Root attributes as written by the acquisition software (harvesters_pg).
CAMERA_ATTRS = {
    'fps': np.int64(100),
    'ExposureTime': np.int64(1000),
    'DeviceModelName': 'MC2066',
    'InfoFieldFrameCounterEnable': np.True_,
    'timestamp': '20260415144348',
}
ID_A = '0d1f3c6a-5b9e-4c2d-8e7f-a1b2c3d4e5f6'
ID_B = '7e8f9a0b-1c2d-4e3f-9a4b-5c6d7e8f9a0b'


def recording(recording_id):
    """Attributes of a recording saved since harvesters_pg writes recording ids."""
    return {**CAMERA_ATTRS, 'recording_id': recording_id}


def with_inventory(attrs, particles, objective):
    """Attributes plus the lab ids of the particles and objective of a recording."""
    return {**attrs, 'particles': particles, 'objective': objective}


def lab_ids(references):
    return [reference['lab_id'] for reference in references or []]


def parse(parser, tmp_path, mainfile, context=None):
    """Parse `mainfile` of an upload in `tmp_path`; the data of its entry YAML."""
    archive = EntryArchive(
        m_context=context or ClientContext(local_dir=str(tmp_path)),
        metadata=EntryMetadata(mainfile=mainfile, upload_id='test_upload'),
    )
    parser.parse(str(tmp_path / mainfile), archive, logging.getLogger(__name__))
    with open(tmp_path / f'{mainfile}.archive.yaml') as f:
        return yaml.safe_load(f)['data']


def write_video(path, attrs=CAMERA_ATTRS, frames=None):
    if frames is None:
        frames = np.zeros((3, 4, 6), dtype=np.uint8)
    with h5py.File(path, 'w') as f:
        f.create_dataset('frames', data=frames)
        f.create_dataset('timestamps', data=np.array([0.0, 0.01, 0.02]))
        f.create_dataset('frame_counters', data=np.arange(3, dtype=np.uint32))
        for key, value in attrs.items():
            f.attrs.create(key, value)


def make_tracks():
    """Particles 0 and 1 in frames 0-2, particle 2 only in frame 0."""
    rows = [(particle, frame) for particle in (0, 1) for frame in range(3)]
    rows.append((2, 0))
    particle = np.array([p for p, _ in rows])
    frame = np.array([f for _, f in rows])
    return pd.DataFrame(
        {
            'y': 10.0 + 5 * particle,
            'x': 20.0 + frame,
            'mass': 1500.0,
            'size': 2.5,
            'ecc': 0.1,
            'signal': 50.0,
            'raw_mass': 9000.0,
            'ep': 0.05,
            'frame': frame,
            'particle': particle,
        }
    )


def write_tracks(path, df, attrs):
    """Like tracking/main.py: pandas fixed format, then camera attrs via h5py."""
    df.to_hdf(path, key='trajs', mode='w')
    with h5py.File(path, 'a') as f:
        for key, value in attrs.items():
            f.attrs[key] = value


def write_filtered_tracks(path, df, attrs=None):
    """Like tracking/filtering.py: index named frame, compressed, attrs of the
    tracks (none in files filtered before its fix of line 41)."""
    df.set_index('frame', drop=False).to_hdf(
        path, key='trajs', mode='w', complevel=4, complib='zlib'
    )
    with h5py.File(path, 'a') as f:
        for key, value in (attrs or {}).items():
            f.attrs[key] = value


def write_focus_sweep(path):
    with h5py.File(path, 'w') as f:
        f.create_dataset('imgs', data=np.zeros((5, 6, 4), dtype=np.uint8))
        f.create_dataset('poss', data=np.array([137.0, 137.3, 137.6, 137.9, 138.2]))
        f.create_dataset('tgs', data=np.array([1, 2, 5, 3, 1.5]))
        f.attrs['maxfocus'] = 137.6
        f.attrs['maxslope'] = 137.3
        f.attrs['last_position'] = 138.2
        f.attrs['timestamp'] = '20250227110207'


def matches(parser, path):
    with open(path, 'rb') as f:
        buffer = f.read(12000)
    return parser.is_mainfile(str(path), 'application/x-hdf5', buffer, None)


def test_is_mainfile_prefers_unfiltered_tracks(tmp_path):
    tracks = make_tracks()
    write_tracks(tmp_path / 'rec_trajs.h5', tracks, CAMERA_ATTRS)
    write_filtered_tracks(
        tmp_path / 'rec_filtered_trajs.h5', tracks[tracks['particle'] < 2]
    )
    write_video(tmp_path / 'rec.h5')
    parser = particle_tracking_parser_entry_point.load()

    assert matches(parser, tmp_path / 'rec_trajs.h5')
    assert not matches(parser, tmp_path / 'rec_filtered_trajs.h5')
    assert not matches(parser, tmp_path / 'rec.h5')

    (tmp_path / 'rec_trajs.h5').unlink()
    assert matches(parser, tmp_path / 'rec_filtered_trajs.h5')


def test_recording_files_are_matched_by_recording_id(tmp_path):
    tracks = make_tracks()
    write_tracks(tmp_path / 'rec_trajs.h5', tracks, recording(ID_A))
    # filtered before filtering.py copied attributes: linked by name
    write_filtered_tracks(
        tmp_path / 'rec_filtered_trajs.h5', tracks[tracks['particle'] < 2]
    )
    write_video(tmp_path / 'rec.h5', recording(ID_B))  # overwritten by another
    write_video(tmp_path / 'renamed.h5', recording(ID_A))

    assert find_recording_files(str(tmp_path), 'rec', ID_A) == {
        'tracks': 'rec_trajs.h5',
        'filtered_tracks': 'rec_filtered_trajs.h5',
        'video': 'renamed.h5',
    }


def test_renamed_filtered_tracks_stay_with_their_tracks(tmp_path):
    tracks = make_tracks()
    filtered = tracks[tracks['particle'] < 2]
    write_tracks(tmp_path / 'rec_trajs.h5', tracks, recording(ID_A))
    write_filtered_tracks(
        tmp_path / 'rec_short_filtered_trajs.h5', filtered, recording(ID_A)
    )
    parser = particle_tracking_parser_entry_point.load()

    files = find_recording_files(str(tmp_path), 'rec', ID_A)
    assert files['filtered_tracks'] == 'rec_short_filtered_trajs.h5'
    assert not matches(parser, tmp_path / 'rec_short_filtered_trajs.h5')

    # Tracked again under another name: the filtered tracks that pair up with
    # the first tracks by name are not attributed to the second tracks.
    (tmp_path / 'rec_short_filtered_trajs.h5').rename(
        tmp_path / 'rec_filtered_trajs.h5'
    )
    write_tracks(tmp_path / 'rec_v2_trajs.h5', tracks, recording(ID_A))
    files = find_recording_files(str(tmp_path), 'rec_v2', ID_A)
    assert files['filtered_tracks'] is None
    assert not matches(parser, tmp_path / 'rec_filtered_trajs.h5')


def test_filtered_only_recording_takes_camera_settings_from_video(tmp_path):
    tracks = make_tracks()
    write_filtered_tracks(
        tmp_path / 'rec_filtered_trajs.h5', tracks[tracks['particle'] < 2]
    )
    write_video(tmp_path / 'rec.h5')

    entry = build_particle_tracking_entry(
        str(tmp_path), '', 'rec', find_recording_files(str(tmp_path), 'rec')
    )

    # the filtered tracks are the only tracks of the recording
    assert entry.tracks_file == 'rec_filtered_trajs.h5'
    assert entry.video_file == 'rec.h5'
    assert (entry.n_particles, entry.n_localizations) == (2, 6)
    assert entry.camera_model == 'MC2066'
    assert entry.frame_rate.to('Hz').magnitude == 100
    # 14:43:48 local summer time (UTC+2)
    assert entry.datetime == datetime(2026, 4, 15, 12, 43, 48, tzinfo=timezone.utc)
    assert entry.illumination == 'darkfield'  # the video frames are black


def test_filtered_only_recording_references_its_video(tmp_path):
    tracks = make_tracks()
    write_filtered_tracks(
        tmp_path / 'rec_filtered_trajs.h5',
        tracks[tracks['particle'] < 2],
        recording(ID_A),
    )
    write_video(tmp_path / 'renamed.h5', recording(ID_A))

    data = parse(ParticleTrackingParser(), tmp_path, 'rec_filtered_trajs.h5')

    assert data['video'] == get_hash_ref('test_upload', 'renamed.h5.archive.yaml')
    assert data['tracks_file'] == 'rec_filtered_trajs.h5'
    assert data['n_particles'] == 2
    assert not data.keys() & FILTERED_KEYS


def test_tracks_entry_references_its_video_entry(
    tmp_path, process_entry, entry_references
):
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    write_video(tmp_path / 'rec.h5', recording(ID_B))  # another recording
    write_video(tmp_path / 'renamed.h5', recording(ID_A))

    data = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')

    assert data['video'] == get_hash_ref('test_upload', 'renamed.h5.archive.yaml')
    # NOMAD indexes the reference, so the video lists the tracks as referencing it
    tracks = process_entry(tmp_path, 'rec_trajs.h5.archive.yaml')
    video_id = get_entry_id('test_upload', 'renamed.h5.archive.yaml')
    assert ('data.video', video_id) in entry_references(tracks)


def test_tracks_without_video_have_no_video_reference(
    tmp_path, process_entry, entry_references, caplog
):
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))

    data = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')
    tracks = process_entry(tmp_path, 'rec_trajs.h5.archive.yaml')

    assert 'video' not in data
    assert not {path for path, _ in entry_references(tracks)} & {'data.video'}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_tracks_entry_shows_unfiltered_tracks_next_to_filtered_ones(tmp_path):
    tracks = make_tracks()
    tracks['field_voltage'] = 0.05 * tracks['frame']
    write_tracks(tmp_path / 'rec_trajs.h5', tracks, recording(ID_A))
    write_filtered_tracks(
        tmp_path / 'rec_filtered_trajs.h5',
        tracks[tracks['particle'] < 2],
        recording(ID_A),
    )

    data = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')

    assert not data.keys() & FILTERED_KEYS
    assert data['tracks_file'] == 'rec_trajs.h5'
    assert (data['n_particles'], data['n_localizations']) == (3, 7)
    trajectories, field = data['figures']
    assert (trajectories['label'], field['label']) == ('Trajectories', 'External field')
    plotted = trajectories['figure']
    assert plotted['layout']['title']['text'] == '3 longest tracks of rec_trajs.h5'
    assert len(plotted['data']) == 3


def old_tracks_entry() -> dict:
    """Tracks entry as older versions wrote it, with the filtered tracks folded
    in, and edited by users afterwards."""
    tracks = make_tracks()
    filtered = tracks[tracks['particle'] < 2]
    entry = AGE_ParticleTracking(
        name='rec',
        tracks_file='rec_trajs.h5',
        n_particles=3,
        n_localizations=7,
        figures=[
            PlotlyFigure(
                label='Trajectories',
                figure=plot_trajectories(
                    filtered, 'rec_filtered_trajs.h5'
                ).to_plotly_json(),
            )
        ],
    ).m_to_dict(with_root_def=True)
    entry.update(
        filtered_tracks_file='rec_filtered_trajs.h5',
        n_particles_filtered=2,
        n_localizations_filtered=6,
        # user edits
        description='Chip tilted by 2°',
        illumination='brightfield',
        pixel_size=0.345,
        samples=[{'name': '2023_0418', 'lab_id': '2023_0418'}],
    )
    return entry


def test_reprocessing_rewrites_old_tracks_entries_without_filtered_values(
    tmp_path, stored_archives, caplog
):
    tracks = make_tracks()
    write_tracks(tmp_path / 'rec_trajs.h5', tracks, recording(ID_A))
    write_filtered_tracks(
        tmp_path / 'rec_filtered_trajs.h5',
        tracks[tracks['particle'] < 2],
        recording(ID_A),
    )
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    old = old_tracks_entry()
    entry_file = tmp_path / 'rec_trajs.h5.archive.yaml'
    with open(entry_file, 'w') as f:
        yaml.dump({'data': old}, f)
    # the processed archive of the old entry file, as written by older versions
    eid = get_entry_id('test_upload', 'rec_trajs.h5.archive.yaml')
    stored_archives({eid: old})

    data = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not data.keys() & FILTERED_KEYS
    (trajectories,) = data['figures']
    title = trajectories['figure']['layout']['title']['text']
    assert title == '3 longest tracks of rec_trajs.h5'
    assert data['video'] == get_hash_ref('test_upload', 'rec.h5.archive.yaml')
    assert data['description'] == 'Chip tilted by 2°'
    assert data['illumination'] == 'brightfield'
    assert data['pixel_size'] == 0.345
    assert lab_ids(data['samples']) == ['2023_0418']
    assert data['name'] == 'rec'
    # older versions wrote no link to the raw file entry
    assert data['raw_file'] == get_hash_ref('test_upload', 'rec_trajs.h5')


def test_entry_files_do_not_store_values_from_samples(tmp_path, stored_archives):
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    written = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    entry_file = tmp_path / 'rec.h5.archive.yaml'
    text = entry_file.read_text()
    # the processed archive holds the values that normalizing fills in
    processed = {
        **written,
        'particles': [{'name': 'M270 batch 3'}],
        'chips': [{'name': '2023_0418'}],
        'spacer_thickness': 3369.25,
    }
    eid = get_entry_id('test_upload', 'rec.h5.archive.yaml')
    stored_archives({eid: processed})

    parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')

    # unchanged, so neither written nor processed again
    assert entry_file.read_text() == text
    assert not written.keys() & {'particles', 'chips', 'spacer_thickness'}


@pytest.mark.parametrize(
    'background, dtype, illumination',
    [
        (4, np.uint8, 'darkfield'),  # like the rig's darkfield videos
        (131, np.uint8, 'brightfield'),  # like the rig's brightfield videos
        (64, np.uint8, None),  # in between: left to the scientists
        (60000, np.uint16, 'brightfield'),
        (0.5, np.float32, None),  # no known full scale
    ],
)
def test_illumination_from_background(background, dtype, illumination):
    image = np.full((40, 60), background, dtype=dtype)
    image[10:14, 10:14] = 0 if background > 100 else 200  # one particle
    assert guess_illumination(image) == illumination


@pytest.mark.parametrize(
    'timestamp, utc',
    [
        ('20250227110207', datetime(2025, 2, 27, 10, 2, 7, tzinfo=timezone.utc)),
        ('20260415144348', datetime(2026, 4, 15, 12, 43, 48, tzinfo=timezone.utc)),
    ],
    ids=['winter CET', 'summer CEST'],
)
def test_timestamps_are_lab_local_time(timestamp, utc):
    assert parse_timestamp(timestamp) == utc


@pytest.mark.parametrize(
    'filename, utc',
    [
        (
            '20250227110207_focus_sweep.h5',
            datetime(2025, 2, 27, 10, 2, 7, tzinfo=timezone.utc),
        ),
        (
            '202604081623_x1Hz_z1Hz_5mu_4kAm_M270_trajs.h5',
            datetime(2026, 4, 8, 14, 23, tzinfo=timezone.utc),
        ),
        # midnight local time is the previous day in UTC
        (
            '20260319_x2kAm_z4kAm_5mu_M270_720fps_trajs.h5',
            datetime(2026, 3, 18, 23, 0, tzinfo=timezone.utc),
        ),
        (
            '2023_0418_M270COOHDynabeads_20x_FieldSweep0.2Hz_100mV_25s_1_trajs.h5',
            datetime(2023, 4, 17, 22, 0, tzinfo=timezone.utc),
        ),
        ('1to2_trajs.h5', None),
        ('NewLadder1_trajs.h5', None),
        ('2023_1399_trajs.h5', None),  # no such date
        ('123456789_trajs.h5', None),
        ('rec_20260319_trajs.h5', None),  # only a leading date counts
    ],
)
def test_recording_time_from_filename(filename, utc):
    assert time_from_filename(filename) == utc


def test_camera_timestamp_wins_over_filename_date(tmp_path):
    write_tracks(tmp_path / '2023_0418_a_trajs.h5', make_tracks(), {})
    write_tracks(tmp_path / '2023_0418_b_trajs.h5', make_tracks(), CAMERA_ATTRS)

    def recorded(stem):
        files = find_recording_files(str(tmp_path), stem)
        return build_particle_tracking_entry(str(tmp_path), '', stem, files).datetime

    assert recorded('2023_0418_a') == datetime(2023, 4, 17, 22, tzinfo=timezone.utc)
    assert recorded('2023_0418_b') == datetime(
        2026, 4, 15, 12, 43, 48, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    'filename, chip_ids',
    [
        ('2023_0418_1hz_1hz_m270_trajs.h5', ['2023_0418']),
        ('2023_0325_1_LMOKE_trajs.h5', ['2023_0325_1']),
        ('2024_0207_2_trajs.h5', ['2024_0207_2']),
        ('2023_0418_2023_0419_trajs.h5', ['2023_0418', '2023_0419']),
        ('1to2_trajs.h5', []),
        ('20260319_x2kAm_z4kAm_5mu_M270_720fps_trajs.h5', []),
        ('202604081623_x1Hz_z1Hz_5mu_4kAm_M270_trajs.h5', []),
        ('20250227110207_focus_sweep.h5', []),
        ('NewLadder1_trajs.h5', []),
    ],
)
def test_chip_ids_from_filename(filename, chip_ids):
    assert chip_ids_from_filename(filename) == chip_ids


@pytest.mark.parametrize('found', [False, True])
def test_videos_link_chips_but_never_create_them(tmp_path, monkeypatch, caplog, found):
    def search(lab_id, user_id=None):
        hits = [{'upload_id': 'age_samples', 'entry_id': f'chip_{lab_id}'}]
        return SimpleNamespace(data=hits if found else [])

    monkeypatch.setattr(utils, 'find_existing_AGE_sample', search)
    write_video(tmp_path / '2023_0418_rec.h5', recording(ID_A))

    with caplog.at_level(logging.WARNING):
        data = parse(ParticleTransportVideoParser(), tmp_path, '2023_0418_rec.h5')

    (chip, *_) = data['samples']
    assert (chip['name'], chip['lab_id']) == ('2023_0418_1', '2023_0418_1')
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    if found:
        reference = '../uploads/age_samples/archive/chip_2023_0418_1#data'
        assert chip['reference'] == reference
        assert not warnings
    else:
        assert 'reference' not in chip
        (warning,) = warnings
        assert '2023_0418_1' in warning.getMessage()
    assert {p.name for p in tmp_path.glob('*.archive.yaml')} == {
        '2023_0418_rec.h5.archive.yaml'
    }


def test_trajectory_plot_keeps_longest_tracks_and_caps_points():
    lengths = np.arange(150) + 151  # particle i has i + 151 localizations
    frame = np.concatenate([np.arange(n) for n in lengths])
    particle = np.repeat(np.arange(150), lengths)
    tracks = pd.DataFrame(
        {'x': 0.5 * frame, 'y': 2.0 * particle, 'frame': frame, 'particle': particle}
    )

    fig = plot_trajectories(tracks, 'rec_trajs.h5')

    assert {trace.name for trace in fig.data} == {
        f'particle {i}' for i in range(50, 150)
    }
    assert all(len(trace.x) <= 200 for trace in fig.data)


def test_external_field_is_plotted_once_per_frame():
    tracks = make_tracks()  # frames 0-2; frame 0 has three particles
    tracks['field_voltage'] = 0.05 * tracks['frame']
    tracks['timestamp_fixed'] = 0.01 * tracks['frame']

    (trace,) = plot_external_field(tracks, frame_rate=None).data
    assert trace.name == 'field_voltage'
    assert list(trace.x) == [0.0, 0.01, 0.02]
    assert list(trace.y) == [0.0, 0.05, 0.1]

    # without timestamps the time comes from the frame rate
    no_time = plot_external_field(tracks.drop(columns='timestamp_fixed'), 100.0)
    assert list(no_time.data[0].x) == [0.0, 0.01, 0.02]
    assert plot_external_field(make_tracks(), frame_rate=100.0) is None


def test_reprocessing_keeps_user_edits_and_refreshes_parsed_values():
    editable = user_editable_keys(AGE_ParticleTracking.m_def)
    assert not user_editable_keys(AGE_ParticleTransportVideo.m_def) & {
        'lab_id',
        'video_file',
        'n_frames',
        'figures',
        'raw_file',
    }
    assert {'illumination', 'pixel_size', 'datetime', 'samples'} <= editable
    assert not editable & {
        'figures',
        'n_particles',
        'tracks_file',
        'frame_rate',
        'lab_id',  # the recording id comes from the files
        'raw_file',
    }

    fresh = {
        'figures': ['tracks', 'field'],
        'n_particles': 3,
        'illumination': 'darkfield',
    }
    stored = {
        'figures': ['tracks'],
        'n_particles': 2,
        'illumination': 'brightfield',
        'method': 'Particle Tracking',
    }
    assert merge_stored_values(fresh, stored, editable) == {
        'figures': ['tracks', 'field'],  # parser output is refreshed
        'n_particles': 3,
        'illumination': 'brightfield',  # the user's choice stays
        'method': 'Particle Tracking',  # not set by the parser: kept
    }
    # figures only the parse makes: stored ones go even if the parse makes none
    assert merge_stored_values({}, stored, editable, parser_owned=('figures',)) == {
        'illumination': 'brightfield',
        'n_particles': 2,
        'method': 'Particle Tracking',
    }


def test_parse_writes_entry_yaml_that_round_trips(tmp_path):
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(tmp_path)),
        metadata=EntryMetadata(mainfile='rec_trajs.h5', upload_id='test_upload'),
    )

    ParticleTrackingParser().parse(
        str(tmp_path / 'rec_trajs.h5'), archive, logging.getLogger(__name__)
    )

    assert isinstance(archive.data, AGE_RawFile)
    assert archive.data.m_to_dict()['processed_archive'] == get_hash_ref(
        'test_upload', 'rec_trajs.h5.archive.yaml'
    )
    with open(tmp_path / 'rec_trajs.h5.archive.yaml') as f:
        data = yaml.safe_load(f)['data']
    assert data['m_def'] == (
        'nomad_age.schema_packages.particle_tracking_schema.AGE_ParticleTracking'
    )
    entry = AGE_ParticleTracking.m_from_dict(data)
    assert entry.n_particles == 3
    assert entry.n_localizations == 7
    assert entry.n_frames == 3
    assert entry.lab_id == ID_A
    assert entry.camera_settings == {
        'fps': 100,
        'ExposureTime': 1000,
        'DeviceModelName': 'MC2066',
        'InfoFieldFrameCounterEnable': True,
        'timestamp': '20260415144348',
        'recording_id': ID_A,
    }
    assert len(entry.figures) == 1


def test_focus_sweep_parser_matches_sweeps_only(tmp_path):
    write_focus_sweep(tmp_path / '20250227110207_focus_sweep.h5')
    write_video(tmp_path / 'rec.h5')
    parser = focus_sweep_parser_entry_point.load()

    assert matches(parser, tmp_path / '20250227110207_focus_sweep.h5')
    assert not matches(parser, tmp_path / 'rec.h5')


def decode_png(figure: dict) -> np.ndarray:
    """Pixels of the PNG that a first-frame figure embeds."""
    source = figure['data'][0]['source']
    return np.array(Image.open(io.BytesIO(base64.b64decode(source.split(',', 1)[1]))))


def test_video_parser_matches_videos_only(tmp_path):
    write_video(tmp_path / 'rec.h5')
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), CAMERA_ATTRS)
    write_focus_sweep(tmp_path / '20250227110207_focus_sweep.h5')
    parser = particle_transport_video_parser_entry_point.load()

    assert matches(parser, tmp_path / 'rec.h5')
    assert not matches(parser, tmp_path / 'rec_trajs.h5')
    assert not matches(parser, tmp_path / '20250227110207_focus_sweep.h5')


def test_video_entry_shows_camera_settings_and_first_and_last_frame(tmp_path):
    frames = np.full((3, 4, 6), 128, dtype=np.uint8)
    frames[0] = np.arange(24, dtype=np.uint8).reshape(4, 6) * 10
    frames[2] = 255 - frames[0]
    write_video(tmp_path / 'rec.h5', recording(ID_A), frames)

    entry = build_video_entry(str(tmp_path / 'rec.h5'), 'sub/rec.h5')

    assert (entry.name, entry.video_file, entry.lab_id) == ('rec', 'sub/rec.h5', ID_A)
    assert (entry.n_frames, entry.frame_width, entry.frame_height) == (3, 6, 4)
    assert entry.frame_rate.to('Hz').magnitude == 100
    assert entry.duration.to('s').magnitude == pytest.approx(0.03)
    assert entry.camera_model == 'MC2066'
    assert entry.datetime == datetime(2026, 4, 15, 12, 43, 48, tzinfo=timezone.utc)
    first, last = entry.figures
    assert (first.label, last.label) == ('First frame', 'Last frame')
    np.testing.assert_array_equal(decode_png(first.figure), frames[0])
    np.testing.assert_array_equal(decode_png(last.figure), frames[2])


def test_single_frame_video_shows_that_frame_once(tmp_path):
    write_video(tmp_path / 'rec.h5', frames=np.zeros((1, 4, 6), dtype=np.uint8))

    entry = build_video_entry(str(tmp_path / 'rec.h5'), 'rec.h5')

    assert [f.label for f in entry.figures] == ['First frame']


def test_wide_frames_are_reduced_but_keep_pixel_coordinates():
    frame = np.tile((np.arange(2000) % 256).astype(np.uint8), (10, 1))

    figure = plot_frame(frame, 'Wide frame').to_plotly_json()

    image, step = decode_png(figure), figure['data'][0]['dx']
    assert image.shape[1] <= MAX_PREVIEW_WIDTH
    assert image.shape[1] * step >= frame.shape[1]
    np.testing.assert_array_equal(image, frame[::step, ::step])


def test_video_parse_writes_entry_yaml_that_round_trips(tmp_path):
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(tmp_path)),
        metadata=EntryMetadata(mainfile='rec.h5', upload_id='test_upload'),
    )

    ParticleTransportVideoParser().parse(
        str(tmp_path / 'rec.h5'), archive, logging.getLogger(__name__)
    )

    assert isinstance(archive.data, AGE_RawFile)
    with open(tmp_path / 'rec.h5.archive.yaml') as f:
        data = yaml.safe_load(f)['data']
    assert data['m_def'] == (
        'nomad_age.schema_packages.particle_tracking_schema.AGE_ParticleTransportVideo'
    )
    entry = AGE_ParticleTransportVideo.m_from_dict(data)
    assert (entry.lab_id, entry.n_frames) == (ID_A, 3)
    assert [f.label for f in entry.figures] == ['First frame', 'Last frame']


def test_video_links_particle_batches_and_objective_from_its_attributes(
    tmp_path, fake_index, caplog
):
    index_inventory(fake_index, INVENTORY)
    # OBJ-20x is an objective, not a particle batch; M450 is not in the inventory
    particles = np.array(
        ['M270', 'NH2', 'OBJ-20x', 'M450-2023-01'], dtype=h5py.string_dtype()
    )
    attrs = with_inventory(recording(ID_A), particles, 'OBJ-20x')
    write_video(tmp_path / 'rec.h5', attrs)

    data = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')

    assert data['particle_batches'] == [
        inventory_reference('m270'),
        inventory_reference('nh2'),
    ]
    assert 'samples' not in data  # particles are no samples; no chip in the name
    assert lab_ids(data['instruments']) == ['OBJ-20x']
    assert [m.split(';')[0] for m in warning_messages(caplog)] == [
        'No particle batch (Particles entry) with lab_id OBJ-20x found',
        'No particle batch (Particles entry) with lab_id M450-2023-01 found',
    ]
    # searched among the particle batches of every upload the user sees
    assert len(fake_index.calls) == 4
    for call in fake_index.calls:
        assert call['owner'] == 'visible'
        assert call['query']['section_defs.definition_qualified_name'] == (
            AGE_PARTICLES_SCHEMA
        )
    # nothing is created
    assert {p.name for p in tmp_path.glob('*.archive.yaml')} == {'rec.h5.archive.yaml'}


def test_tracks_without_video_entry_link_their_own_particles_and_objective(
    tmp_path, fake_index
):
    index_inventory(fake_index, INVENTORY)
    attrs = with_inventory(recording(ID_A), 'M270, NH2', 'OBJ-20x')
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), attrs)

    tracks = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')

    assert tracks['particle_batches'] == [
        inventory_reference('m270'),
        inventory_reference('nh2'),
    ]
    assert 'samples' not in tracks
    assert lab_ids(tracks['instruments']) == ['OBJ-20x']


def test_tracks_take_particles_and_instruments_from_the_video_entry(
    tmp_path, fake_index
):
    index_inventory(fake_index, INVENTORY)
    write_video(tmp_path / 'rec.h5', with_inventory(recording(ID_A), 'M270', 'OBJ-20x'))
    # the attributes of the tracks do not count: the video entry is edited
    attrs = with_inventory(recording(ID_A), 'NH2', 'OBJ-20x')
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), attrs)
    video = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    # corrected in the GUI after the upload
    video['instruments'] = [{'name': 'OBJ-50x', 'lab_id': 'OBJ-50x'}]
    with open(tmp_path / 'rec.h5.archive.yaml', 'w') as f:
        yaml.dump({'data': video}, f)

    tracks = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')

    assert batch_entry_ids(tracks) == ['m270']
    assert 'samples' not in tracks
    assert lab_ids(tracks['instruments']) == ['OBJ-50x']


def test_video_entry_passes_its_samples_particles_and_instruments_to_its_tracks(
    tmp_path, fake_index
):
    index_inventory(fake_index, INVENTORY)
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    write_tracks(tmp_path / 'other_trajs.h5', make_tracks(), recording(ID_B))
    rec = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')
    # written by an older version, without raw_file and with particles as
    # samples; particles as a save in the GUI writes them
    del rec['raw_file']
    rec.update(
        filtered_tracks_file='rec_filtered_trajs.h5',
        n_particles_filtered=2,
        samples=[{'name': 'M450-2023-01', 'lab_id': 'M450-2023-01'}],
        particles=[{'name': 'M450 batch 1'}],
    )
    with open(tmp_path / 'rec_trajs.h5.archive.yaml', 'w') as f:
        yaml.dump({'data': rec}, f)
    other = parse(ParticleTrackingParser(), tmp_path, 'other_trajs.h5')
    # uploaded later, under another name
    attrs = with_inventory(recording(ID_A), 'M270', 'OBJ-20x')
    write_video(tmp_path / 'renamed.h5', attrs)
    video = parse(ParticleTransportVideoParser(), tmp_path, 'renamed.h5')
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(tmp_path)),
        metadata=EntryMetadata(
            mainfile='renamed.h5.archive.yaml', upload_id='test_upload'
        ),
    )

    share_with_tracks(
        AGE_ParticleTransportVideo.m_from_dict(video),
        archive,
        logging.getLogger(__name__),
    )

    with open(tmp_path / 'rec_trajs.h5.archive.yaml') as f:
        tracks = yaml.safe_load(f)['data']
    assert 'samples' not in tracks  # the video links no chip
    assert batch_entry_ids(tracks) == ['m270']
    assert lab_ids(tracks['instruments']) == ['OBJ-20x']
    assert tracks['n_particles'] == 3
    assert tracks['video'] == get_hash_ref('test_upload', 'renamed.h5.archive.yaml')
    assert tracks['raw_file'] == get_hash_ref('test_upload', 'rec_trajs.h5')
    assert not tracks.keys() & (FILTERED_KEYS | {'particles'})
    with open(tmp_path / 'other_trajs.h5.archive.yaml') as f:
        assert yaml.safe_load(f)['data'] == other


INVENTORY_UPLOAD_ID = 'inventory_upload'


def inventory_reference(entry_id):
    return f'../uploads/{INVENTORY_UPLOAD_ID}/archive/{entry_id}#data'


def batch_entry_ids(data: dict) -> list:
    """Entry ids that the particle_batches of an entry file link."""
    return [parse_reference(b)[1] for b in data.get('particle_batches', [])]


INVENTORY = {
    (INVENTORY_UPLOAD_ID, 'obj20'): {
        'm_def': 'nomad_age.schema_packages.age_schema.AGE_Objective',
        'name': 'Objective 20x',
        'lab_id': 'OBJ-20x',
    },
    (INVENTORY_UPLOAD_ID, 'obj50'): {
        'm_def': 'nomad_age.schema_packages.age_schema.AGE_Objective',
        'name': 'Objective 50x',
        'lab_id': 'OBJ-50x',
    },
    (INVENTORY_UPLOAD_ID, 'm270'): {
        'm_def': 'nomad_age.schema_packages.age_schema.AGE_Particles',
        'name': 'Dynabeads M-270',
        'lab_id': 'M270',
    },
    (INVENTORY_UPLOAD_ID, 'nh2'): {
        'm_def': 'nomad_age.schema_packages.age_schema.AGE_Particles',
        'name': 'micromer-M NH2',
        'lab_id': 'NH2',
    },
    (INVENTORY_UPLOAD_ID, 'cooh'): {
        'm_def': 'nomad_age.schema_packages.age_schema.AGE_Particles',
        'name': 'micromer-M COOH',
        'lab_id': 'COOH',
    },
    (INVENTORY_UPLOAD_ID, 'camera'): {
        'm_def': 'nomad.datamodel.metainfo.eln.ELNInstrument',
        'name': 'Camera MC2066',
        'lab_id': 'CAM-1',
    },
}


def instrument(entry_id):
    """An instrument as NOMAD stores it once the lab_id found its entry."""
    lab_id = INVENTORY[(INVENTORY_UPLOAD_ID, entry_id)]['lab_id']
    return {
        'name': lab_id,
        'lab_id': lab_id,
        'reference': inventory_reference(entry_id),
    }


def linked(instruments) -> list:
    """(name, lab_id, linked entry id) of instrument sections."""
    return [(i.name, i.lab_id, parse_reference(i.reference)[1]) for i in instruments]


def write_measurement(tmp_path, entry_type, **data):
    data = {'m_def': f'{SCHEMA}.{entry_type}', 'name': 'rec', **data}
    with open(tmp_path / 'rec.archive.yaml', 'w') as f:
        yaml.dump({'data': data}, f)


SCHEMA = 'nomad_age.schema_packages.particle_tracking_schema'
WITH_OBJECTIVE = ['AGE_ParticleTransportVideo', 'AGE_FocusSweep']


def test_objective_is_shown_and_edited_on_the_overview():
    for section in (AGE_ParticleTransportVideo, AGE_FocusSweep):
        objective = section.m_def.all_quantities['objective']
        eln = objective.m_annotations['eln']
        assert eln.component == 'ReferenceEditQuantity'
        assert eln.label == 'Objective'
        assert 'objective' in user_editable_keys(section.m_def)
        assert section.m_def.m_annotations['eln'].properties.order == [
            'name',
            'datetime',
            'chip',
            'spacer_thickness',
            'spacer_thickness_uncertainty',
            'particle_batches',
            'objective',
        ]
    # tracks take the instruments of their video and pick no objective
    assert 'objective' not in AGE_ParticleTracking.m_def.all_quantities


def index_inventory(fake_index, archives: dict) -> None:
    """Make the entries of `archives` findable by lab_id and entry type."""
    for (upload_id, entry_id), data in archives.items():
        fake_index.docs.append(
            {
                'upload_id': upload_id,
                'entry_id': entry_id,
                'lab_ids': [data['lab_id']],
                'section_defs': [{'definition_qualified_name': data['m_def']}],
            }
        )


def test_picked_objective_becomes_the_objective_instrument_of_video_and_tracks(
    tmp_path, process_entry, stored_archives_context, kwargs_logger, caplog
):
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')
    video = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    assert not video.get('instruments')
    # picked on the overview page
    video['objective'] = inventory_reference('obj20')
    with open(tmp_path / 'rec.h5.archive.yaml', 'w') as f:
        yaml.dump({'data': video}, f)
    context = stored_archives_context(tmp_path, INVENTORY)

    data = process_entry(
        tmp_path, 'rec.h5.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert parse_reference(data.objective) == (INVENTORY_UPLOAD_ID, 'obj20')
    assert linked(data.instruments) == [('Objective 20x', 'OBJ-20x', 'obj20')]
    with open(tmp_path / 'rec_trajs.h5.archive.yaml') as f:
        tracks = yaml.safe_load(f)['data']
    assert lab_ids(tracks['instruments']) == ['OBJ-20x']
    assert parse_reference(tracks['instruments'][0]['reference'])[1] == 'obj20'
    assert 'objective' not in tracks
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize('entry_type', WITH_OBJECTIVE)
def test_objective_is_taken_from_the_objective_instrument(
    tmp_path, process_entry, stored_archives_context, kwargs_logger, entry_type
):
    # as the parser links it from the objective attribute, or older entries
    write_measurement(
        tmp_path,
        entry_type,
        instruments=[instrument('camera'), instrument('obj20')],
    )
    context = stored_archives_context(tmp_path, INVENTORY)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert parse_reference(data.objective) == (INVENTORY_UPLOAD_ID, 'obj20')
    assert linked(data.instruments) == [
        ('Camera MC2066', 'CAM-1', 'camera'),
        ('Objective 20x', 'OBJ-20x', 'obj20'),
    ]


@pytest.mark.parametrize('entry_type', WITH_OBJECTIVE)
def test_picking_another_objective_replaces_the_objective_instrument(
    tmp_path, process_entry, stored_archives_context, kwargs_logger, entry_type
):
    # a save in the GUI: the new objective next to the instruments from before
    write_measurement(
        tmp_path,
        entry_type,
        objective=inventory_reference('obj50'),
        instruments=[instrument('obj20'), instrument('camera'), instrument('obj20')],
    )
    context = stored_archives_context(tmp_path, INVENTORY)

    def process():
        return process_entry(
            tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
        ).data

    data = process()

    assert parse_reference(data.objective) == (INVENTORY_UPLOAD_ID, 'obj50')
    assert linked(data.instruments) == [
        ('Objective 50x', 'OBJ-50x', 'obj50'),
        ('Camera MC2066', 'CAM-1', 'camera'),
    ]
    # the next save stores what the GUI shows: nothing changes any more
    saved = data.m_to_dict(with_root_def=True)
    with open(tmp_path / 'rec.archive.yaml', 'w') as f:
        yaml.dump({'data': saved}, f)
    again = process()
    assert parse_reference(again.objective) == (INVENTORY_UPLOAD_ID, 'obj50')
    assert linked(again.instruments) == linked(data.instruments)
    assert again.m_to_dict(with_root_def=True) == saved


@pytest.mark.parametrize('attribute', ['OBJ-20x', None])
def test_reprocessing_keeps_the_picked_objective(
    tmp_path,
    stored_archives,
    process_entry,
    stored_archives_context,
    kwargs_logger,
    attribute,
):
    attrs = recording(ID_A)
    if attribute:
        attrs = with_inventory(attrs, 'M270-2024-03', attribute)
    write_video(tmp_path / 'rec.h5', attrs)
    written = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    # the processed archive after the objective was picked on the overview page
    processed = {
        **written,
        'objective': inventory_reference('obj50'),
        'instruments': [{**instrument('obj50'), 'name': 'Objective 50x'}],
    }
    stored_archives({get_entry_id('test_upload', 'rec.h5.archive.yaml'): processed})

    reparsed = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')

    assert reparsed['objective'] == inventory_reference('obj50')
    assert lab_ids(reparsed['instruments']) == ['OBJ-50x']
    context = stored_archives_context(tmp_path, INVENTORY)
    data = process_entry(
        tmp_path, 'rec.h5.archive.yaml', logger=kwargs_logger, context=context
    ).data
    assert parse_reference(data.objective) == (INVENTORY_UPLOAD_ID, 'obj50')
    assert linked(data.instruments) == [('Objective 50x', 'OBJ-50x', 'obj50')]


def test_tracks_take_the_picked_objective_from_the_video_entry(
    tmp_path, stored_archives_context
):
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    video = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    # saved in the GUI after picking another objective than the linked one
    video['objective'] = inventory_reference('obj50')
    video['instruments'] = [instrument('obj20'), instrument('camera')]
    with open(tmp_path / 'rec.h5.archive.yaml', 'w') as f:
        yaml.dump({'data': video}, f)
    context = stored_archives_context(tmp_path, INVENTORY)

    tracks = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5', context)

    assert lab_ids(tracks['instruments']) == ['OBJ-50x', 'CAM-1']
    assert 'objective' not in tracks


def test_objective_text_of_old_entries_is_dropped(
    tmp_path, process_entry, stored_archives_context, kwargs_logger, caplog
):
    # entries saved before objectives were entries stored free text
    write_measurement(
        tmp_path,
        'AGE_ParticleTransportVideo',
        objective='20x',
        instruments=[instrument('obj20')],
    )
    context = stored_archives_context(tmp_path, INVENTORY)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert parse_reference(data.objective) == (INVENTORY_UPLOAD_ID, 'obj20')
    assert linked(data.instruments) == [('Objective 20x', 'OBJ-20x', 'obj20')]
    assert "Objective '20x' is text" in caplog.text


SAMPLES_UPLOAD_ID = 'age_samples'
AGE_SCHEMA = 'nomad_age.schema_packages.age_schema'


def samples_reference(entry_id):
    return f'../uploads/{SAMPLES_UPLOAD_ID}/archive/{entry_id}#data'


def coated_chip(chip, layer, thickness, coated, removed=None, uncertainty=None):
    lab_id = {'chip1': '2023_0418_1', 'chip2': '2023_0325_1'}[chip]
    return {
        'm_def': f'{AGE_SCHEMA}.AGE_CoatedSample',
        'lab_id': f'{lab_id}_PMMA{layer}',
        'chip': samples_reference(chip),
        'spacer_thickness': thickness,
        'spacer_thickness_uncertainty': uncertainty,
        'date_coated': coated,
        'date_removed': removed,
    }


# The AGE Samples upload; the layers of chip1 follow each other, the dates are
# entered without time (midnight UTC or lab time).
AGE_SAMPLES = {
    (SAMPLES_UPLOAD_ID, 'chip1'): {
        'm_def': f'{AGE_SCHEMA}.AGE_Sample',
        'name': '2023_0418_1',
        'lab_id': '2023_0418_1',
    },
    (SAMPLES_UPLOAD_ID, 'chip2'): {
        'm_def': f'{AGE_SCHEMA}.AGE_Sample',
        'name': '2023_0325_1',
        'lab_id': '2023_0325_1',
    },
    (SAMPLES_UPLOAD_ID, 'pmma3'): coated_chip(
        'chip1', 3, 1210.0, '2025-11-03T00:00:00+00:00', '2026-02-20T00:00:00+00:00'
    ),
    (SAMPLES_UPLOAD_ID, 'pmma4'): coated_chip(
        'chip1', 4, 2400.0, '2026-02-20T00:00:00+00:00', '2026-04-14T22:00:00+00:00'
    ),
    (SAMPLES_UPLOAD_ID, 'pmma5'): coated_chip(
        'chip1',
        5,
        3369.25,
        '2026-04-15T00:00:00+00:00',
        '2026-10-14T00:00:00+00:00',
        uncertainty=33.7,
    ),
    (SAMPLES_UPLOAD_ID, 'chip2_pmma1'): coated_chip(
        'chip2', 1, 980.0, '2026-01-05T00:00:00+00:00'
    ),
    (INVENTORY_UPLOAD_ID, 'm270'): {
        'm_def': f'{AGE_SCHEMA}.AGE_Particles',
        'name': 'M270 batch 3',
        'lab_id': 'M270-2024-03',
    },
    (INVENTORY_UPLOAD_ID, 'nh2'): {
        'm_def': f'{AGE_SCHEMA}.AGE_Particles',
        'name': 'micromer-M NH2',
        'lab_id': 'NH2',
    },
}
# while PMMA5 is on chip1 and PMMA1 on chip2
PMMA5_TIME = '2026-06-02T10:00:00+00:00'


def sample(entry_id, **data):
    """A sample as NOMAD stores it once the lab_id found its entry."""
    particles = ('m270', 'nh2')
    upload_id = INVENTORY_UPLOAD_ID if entry_id in particles else SAMPLES_UPLOAD_ID
    lab_id = AGE_SAMPLES[(upload_id, entry_id)]['lab_id']
    reference = f'../uploads/{upload_id}/archive/{entry_id}#data'
    return {'name': lab_id, 'lab_id': lab_id, 'reference': reference, **data}


def linked_ids(samples) -> list:
    """Entry ids that sample sections or dicts link."""
    return [
        parse_reference(s['reference'] if isinstance(s, dict) else s.reference)[1]
        for s in samples
    ]


def links(samples) -> list:
    """(name, lab_id, linked entry id) of sample sections or dicts."""
    return [
        (s['name'], s['lab_id'], i) if isinstance(s, dict) else (s.name, s.lab_id, i)
        for s, i in zip(samples, linked_ids(samples))
    ]


def entry_id_of(reference):
    return parse_reference(reference)[1] if reference is not None else None


@pytest.fixture
def coated_chips(fake_index):
    """The search index finds the coated chips of AGE_SAMPLES by their chip."""
    for (upload_id, entry_id), data in AGE_SAMPLES.items():
        if data['m_def'].endswith('AGE_CoatedSample'):
            fake_index.docs.append(
                {
                    'upload_id': upload_id,
                    'entry_id': entry_id,
                    'entry_references': [
                        {'target_entry_id': parse_reference(data['chip'])[1]}
                    ],
                    'section_defs': [
                        {'definition_qualified_name': data['m_def']},
                        {'definition_qualified_name': 'nomad.datamodel.data.EntryData'},
                    ],
                }
            )
    return fake_index


def warning_messages(caplog) -> list:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def magnitude(quantity):
    """Magnitude in nm of a length; None if empty."""
    return None if quantity is None else quantity.to('nm').magnitude


def test_chip_and_spacer_thickness_are_shown_on_the_overview():
    for section in (AGE_ParticleTransportVideo, AGE_FocusSweep):
        quantities = section.m_def.all_quantities
        chip = quantities['chip'].m_annotations['eln']
        assert (chip.component, chip.label) == ('ReferenceEditQuantity', 'Chip')
        # the dropdown offers bare chips only
        assert quantities['chip'].type.target_section_def is AGE_Sample.m_def
        labels = {
            name: quantities[name].m_annotations['eln'].label
            for name in ('spacer_thickness', 'spacer_thickness_uncertainty')
        }
        assert labels == {
            'spacer_thickness': 'Spacer thickness',
            'spacer_thickness_uncertainty': 'Spacer thickness uncertainty',
        }
        editable = user_editable_keys(section.m_def)
        assert 'chip' in editable
        assert not editable & labels.keys()  # derived, shown read-only
        # the coated chip is the sample, not a quantity of its own
        assert 'coating' not in quantities
    # not kept from the stored entry on reparse
    assert {'spacer_thickness', 'spacer_thickness_uncertainty'} <= set(FROM_SAMPLES)
    assert not {'chip', 'coating'} & AGE_ParticleTracking.m_def.all_quantities.keys()


@pytest.mark.parametrize('entry_type', WITH_OBJECTIVE)
def test_the_sample_is_the_coated_chip_of_the_picked_chip_at_the_measurement(
    tmp_path,
    process_entry,
    stored_archives_context,
    coated_chips,
    kwargs_logger,
    caplog,
    entry_type,
):
    write_measurement(
        tmp_path,
        entry_type,
        datetime=PMMA5_TIME,
        chip=samples_reference('chip1'),
        samples=[sample('chip1')],
        particle_batches=[inventory_reference('m270')],
    )
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    def process():
        return process_entry(
            tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
        ).data

    data = process()

    assert linked_ids(data.samples) == ['pmma5']
    assert [s.lab_id for s in data.samples] == ['2023_0418_1_PMMA5']
    assert entry_id_of(data.chip) == 'chip1'
    assert magnitude(data.spacer_thickness) == 3369.25
    assert magnitude(data.spacer_thickness_uncertainty) == 33.7
    assert batch_ids(data) == ['m270']
    assert [p.name for p in data.particles] == ['M270 batch 3']
    assert [c.name for c in data.chips] == ['2023_0418_1']
    assert not warning_messages(caplog)
    # the next save stores what the GUI shows: nothing changes any more
    saved = data.m_to_dict(with_root_def=True)
    with open(tmp_path / 'rec.archive.yaml', 'w') as f:
        yaml.dump({'data': saved}, f)
    assert process().m_to_dict(with_root_def=True) == saved


@pytest.mark.parametrize(
    'moment, linked, warning',
    [
        ('2026-01-15T10:00:00+00:00', 'pmma3', None),
        # 23:00 lab time, the day before PMMA4 was removed and PMMA5 coated
        ('2026-04-14T21:00:00+00:00', 'pmma4', None),
        (
            '2026-04-15T12:43:48+00:00',
            'pmma5',
            'Coated chips 2023_0418_1_PMMA4, 2023_0418_1_PMMA5 of chip 2023_0418_1 '
            'were all on it on 2026-04-15',
        ),
        ('2025-06-01T10:00:00+00:00', 'chip1', 'None of the 3 coated chips'),
        (None, 'chip1', 'The measurement has no datetime'),
    ],
    ids=['PMMA3', 'day before boundary', 'boundary day', 'before any', 'no time'],
)
def test_the_sample_is_the_coated_chip_on_the_chip_at_the_datetime(
    tmp_path,
    process_entry,
    stored_archives_context,
    coated_chips,
    kwargs_logger,
    caplog,
    moment,
    linked,
    warning,
):
    data = {'datetime': moment} if moment else {}
    write_measurement(
        tmp_path,
        'AGE_ParticleTransportVideo',
        chip=samples_reference('chip1'),
        samples=[sample('pmma5')],
        particle_batches=[inventory_reference('m270')],
        **data,
    )
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert linked_ids(data.samples) == [linked]
    assert batch_ids(data) == ['m270']
    # empty for the bare chip
    expected = AGE_SAMPLES[(SAMPLES_UPLOAD_ID, linked)]
    assert magnitude(data.spacer_thickness) == expected.get('spacer_thickness')
    assert magnitude(data.spacer_thickness_uncertainty) == expected.get(
        'spacer_thickness_uncertainty'
    )
    if warning is None:
        assert not warning_messages(caplog)
    else:
        assert len(warning_messages(caplog)) == 1
        assert warning in warning_messages(caplog)[0]


def test_chip_is_taken_from_the_coated_chip_the_samples_link(
    tmp_path, process_entry, stored_archives_context, coated_chips, kwargs_logger
):
    # existing videos: the coated chip was linked under samples by hand
    samples = [sample('pmma5', name='coated chip')]
    write_measurement(
        tmp_path, 'AGE_ParticleTransportVideo', datetime=PMMA5_TIME, samples=samples
    )
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert entry_id_of(data.chip) == 'chip1'
    assert links(data.samples) == links(samples)  # the same link stays
    assert magnitude(data.spacer_thickness) == 3369.25


@pytest.mark.parametrize('entry_type', WITH_OBJECTIVE)
def test_picking_another_chip_replaces_the_sample(
    tmp_path,
    process_entry,
    stored_archives_context,
    coated_chips,
    kwargs_logger,
    caplog,
    entry_type,
):
    # a save in the GUI: the new chip next to the samples from before, one of
    # them a chip that the parser did not find
    write_measurement(
        tmp_path,
        entry_type,
        datetime=PMMA5_TIME,
        chip=samples_reference('chip2'),
        samples=[sample('pmma5'), sample('chip1'), {'lab_id': '2023_0418_2'}],
    )
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert linked_ids(data.samples) == ['chip2_pmma1']
    assert [s.lab_id for s in data.samples] == ['2023_0325_1_PMMA1']
    assert [c.name for c in data.chips] == ['2023_0325_1']
    assert magnitude(data.spacer_thickness) == 980.0
    assert data.spacer_thickness_uncertainty is None
    assert warning_messages(caplog) == [
        'Samples 2023_0418_2 removed: the sample of the measurement is its chip, '
        '2023_0325_1_PMMA1'
    ]


def test_samples_stay_if_the_coated_chips_cannot_be_looked_up(
    tmp_path,
    process_entry,
    stored_archives_context,
    kwargs_logger,
    caplog,
    monkeypatch,
):
    def unavailable(chip_entry_id, user_id=None):
        raise ConnectionError('search index unavailable')

    monkeypatch.setattr(particle_tracking_schema, 'find_coated_samples', unavailable)
    write_measurement(
        tmp_path,
        'AGE_ParticleTransportVideo',
        datetime=PMMA5_TIME,
        chip=samples_reference('chip2'),
        samples=[sample('chip1'), sample('m270')],
    )
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    # the particles go all the same
    assert links(data.samples) == links([sample('chip1')])
    assert batch_ids(data) == ['m270']
    assert warning_messages(caplog) == [
        "Coated chips of chip 2023_0325_1 not looked up: ConnectionError('search "
        "index unavailable'); samples left as they are"
    ]


def test_reprocessing_keeps_the_picked_chip_and_the_tracks_get_its_coated_chip(
    tmp_path,
    monkeypatch,
    stored_archives,
    process_entry,
    stored_archives_context,
    coated_chips,
    kwargs_logger,
):
    # the parser links the chip in the file name, here chip1
    monkeypatch.setattr(
        utils,
        'find_existing_AGE_sample',
        lambda lab_id, user_id=None: SimpleNamespace(
            data=[{'upload_id': SAMPLES_UPLOAD_ID, 'entry_id': 'chip1'}]
        ),
    )
    attrs = {**recording(ID_A), 'timestamp': '20260602120000'}
    write_video(tmp_path / '2023_0418_rec.h5', attrs)
    write_tracks(tmp_path / '2023_0418_rec_trajs.h5', make_tracks(), attrs)
    parse(ParticleTrackingParser(), tmp_path, '2023_0418_rec_trajs.h5')
    written = parse(ParticleTransportVideoParser(), tmp_path, '2023_0418_rec.h5')
    assert linked_ids(written['samples']) == ['chip1']
    # the processed archive after chip2 was picked on the overview page, as
    # stored when the coated chip was a quantity of its own (coating)
    processed = {
        **written,
        'chip': samples_reference('chip2'),
        'coating': samples_reference('chip2_pmma1'),
        'samples': [sample('chip2_pmma1')],
        'spacer_thickness': 980.0,
    }
    eid = get_entry_id('test_upload', '2023_0418_rec.h5.archive.yaml')
    stored_archives({eid: processed})

    reparsed = parse(ParticleTransportVideoParser(), tmp_path, '2023_0418_rec.h5')

    assert reparsed['chip'] == samples_reference('chip2')
    assert linked_ids(reparsed['samples']) == ['chip2_pmma1']
    assert not reparsed.keys() & {'coating', 'spacer_thickness'}
    context = stored_archives_context(tmp_path, AGE_SAMPLES)
    data = process_entry(
        tmp_path, '2023_0418_rec.h5.archive.yaml', logger=kwargs_logger, context=context
    ).data
    assert linked_ids(data.samples) == ['chip2_pmma1']
    assert magnitude(data.spacer_thickness) == 980.0
    with open(tmp_path / '2023_0418_rec_trajs.h5.archive.yaml') as f:
        tracks = yaml.safe_load(f)['data']
    assert linked_ids(tracks['samples']) == ['chip2_pmma1']
    assert not tracks.keys() & {'chip', 'coating'}


def test_tracks_take_the_coated_chip_of_the_picked_chip_from_the_video_entry(
    tmp_path, stored_archives_context, coated_chips
):
    index_inventory(coated_chips, AGE_SAMPLES)
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    video = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    # saved in the GUI after picking another chip than the linked one; the
    # particles by lab_id, as older versions of the parser linked them
    video['datetime'] = PMMA5_TIME
    video['chip'] = samples_reference('chip2')
    video['samples'] = [sample('pmma5'), {'name': 'M270', 'lab_id': 'M270-2024-03'}]
    with open(tmp_path / 'rec.h5.archive.yaml', 'w') as f:
        yaml.dump({'data': video}, f)
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    tracks = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5', context)

    assert lab_ids(tracks['samples']) == ['2023_0325_1_PMMA1']
    assert batch_entry_ids(tracks) == ['m270']
    assert not tracks.keys() & {'chip', 'coating'}


def test_old_entries_lose_particle_samples_and_coating(
    tmp_path,
    stored_archives,
    process_entry,
    stored_archives_context,
    coated_chips,
    kwargs_logger,
    entry_references,
    caplog,
):
    # a video and its tracks as stored before particles stopped being samples
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    old_tracks = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5')
    old_video = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    old_samples = [sample('pmma5'), sample('m270')]
    old_video.update(
        datetime=PMMA5_TIME,
        chip=samples_reference('chip1'),
        coating=samples_reference('pmma5'),
        samples=old_samples,
        particle_batches=[inventory_reference('m270')],
    )
    old_tracks['samples'] = old_samples

    def write_old_entries():
        for name, data in (('rec.h5', old_video), ('rec_trajs.h5', old_tracks)):
            with open(tmp_path / f'{name}.archive.yaml', 'w') as f:
                yaml.dump({'data': data}, f)

    def stored_tracks() -> dict:
        with open(tmp_path / 'rec_trajs.h5.archive.yaml') as f:
            return yaml.safe_load(f)['data']

    write_old_entries()
    context = stored_archives_context(tmp_path, AGE_SAMPLES)

    # the video entry is processed first and rewrites its tracks entries
    video = process_entry(
        tmp_path, 'rec.h5.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert linked_ids(video.samples) == ['pmma5']
    assert batch_ids(video) == ['m270']
    assert 'coating' not in video.m_to_dict()
    tracks = stored_tracks()
    assert linked_ids(tracks['samples']) == ['pmma5']
    assert batch_entry_ids(tracks) == ['m270']

    # the tracks parser reads the video entry file as it is stored
    write_old_entries()
    eid = get_entry_id('test_upload', 'rec_trajs.h5.archive.yaml')
    stored_archives({eid: old_tracks})
    parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5', context)

    tracks = stored_tracks()
    assert linked_ids(tracks['samples']) == ['pmma5']
    assert batch_entry_ids(tracks) == ['m270']

    # tracks entries that were not rewritten move their particles themselves
    write_old_entries()
    archive = process_entry(
        tmp_path, 'rec_trajs.h5.archive.yaml', logger=kwargs_logger, context=context
    )

    assert linked_ids(archive.data.samples) == ['pmma5']
    assert batch_ids(archive.data) == ['m270']
    assert [p.name for p in archive.data.particles] == ['M270 batch 3']
    assert magnitude(archive.data.spacer_thickness) == 3369.25
    # the particle batch lists the tracks entry under 'Referenced by'
    assert ('data.particle_batches', 'm270') in entry_references(archive)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


RECORDINGS = [*WITH_OBJECTIVE, 'AGE_ParticleTracking']


@pytest.mark.parametrize('entry_type', RECORDINGS)
def test_workflow_inputs_are_the_sample_and_the_particles(
    tmp_path,
    process_entry,
    stored_archives_context,
    coated_chips,
    kwargs_logger,
    entry_references,
    entry_type,
):
    write_measurement(
        tmp_path,
        entry_type,
        datetime=PMMA5_TIME,
        samples=[sample('pmma5')],
        particle_batches=[inventory_reference('m270'), inventory_reference('nh2')],
    )
    context = stored_archives_context(tmp_path, AGE_SAMPLES)
    archive = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    )

    def inputs() -> list:
        return [(i.name, entry_id_of(i.section)) for i in archive.workflow2.inputs]

    expected = [
        ('2023_0418_1_PMMA5', 'pmma5'),
        ('M270 batch 3', 'm270'),
        ('micromer-M NH2', 'nh2'),
    ]
    assert inputs() == expected
    archive.data.normalize(archive, kwargs_logger)
    assert inputs() == expected  # no duplicates
    references = entry_references(archive)
    for batch in ('m270', 'nh2'):
        # 'Referenced by' of the particle batch lists the entry
        assert ('data.particle_batches', batch) in references
        assert ('workflow2.inputs.section', batch) in references


def parse_raw_file(parser, tmp_path, mainfile):
    """Parse `mainfile` of an upload in `tmp_path`; its normalized AGE_RawFile."""
    archive = EntryArchive(
        m_context=ClientContext(local_dir=str(tmp_path)),
        metadata=EntryMetadata(mainfile=mainfile, upload_id='test_upload'),
    )
    logger = logging.getLogger(__name__)
    parser.parse(str(tmp_path / mainfile), archive, logger)
    archive.data.normalize(archive, logger)
    return archive


@pytest.mark.parametrize(
    'parser, mainfile, write, file_type',
    [
        (
            ParticleTransportVideoParser(),
            'day1/rec.h5',
            lambda path: write_video(path, recording(ID_A)),
            'particle transport video',
        ),
        (
            ParticleTrackingParser(),
            'day1/rec_trajs.h5',
            lambda path: write_tracks(path, make_tracks(), recording(ID_A)),
            'trajectories',
        ),
        (
            ParticleTrackingParser(),
            'day1/rec_filtered_trajs.h5',
            lambda path: write_filtered_tracks(path, make_tracks(), recording(ID_A)),
            'filtered trajectories',
        ),
        (
            FocusSweepParser(),
            'day1/20250227110207_focus_sweep.h5',
            write_focus_sweep,
            'focus sweep',
        ),
    ],
)
def test_raw_file_entry_fingerprints_the_file(
    tmp_path, process_entry, entry_references, parser, mainfile, write, file_type
):
    path = tmp_path / mainfile
    path.parent.mkdir()
    write(path)
    os.utime(path, (0, 1700000000.25))

    archive = parse_raw_file(parser, tmp_path, mainfile)

    raw = archive.data
    assert isinstance(raw, AGE_RawFile)
    assert raw.file_name == mainfile
    assert raw.file_type == file_type
    assert raw.file_size.to('byte').magnitude == path.stat().st_size
    assert raw.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert raw.modified == datetime(2023, 11, 14, 22, 13, 20, 250000, timezone.utc)
    assert raw.name == archive.metadata.entry_name == os.path.basename(mainfile)
    assert raw.m_to_dict()['processed_archive'] == get_hash_ref(
        'test_upload', f'{mainfile}.archive.yaml'
    )
    # the entry file links back; NOMAD lists the link under the references
    entry = process_entry(tmp_path, f'{mainfile}.archive.yaml')
    raw_id = get_entry_id('test_upload', mainfile)
    assert ('data.raw_file', raw_id) in entry_references(entry)


def test_old_entry_gains_raw_file_once_and_keeps_user_edits(tmp_path, stored_archives):
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    entry_file = tmp_path / 'rec.h5.archive.yaml'
    eid = get_entry_id('test_upload', 'rec.h5.archive.yaml')
    old = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    # as older versions wrote it, then edited in the GUI
    del old['raw_file']
    old['description'] = 'Field ramp at 1 Hz'
    with open(entry_file, 'w') as f:
        yaml.dump({'data': old}, f)
    stored_archives({eid: old})

    migrated = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')

    assert migrated['raw_file'] == get_hash_ref('test_upload', 'rec.h5')
    assert migrated['description'] == 'Field ramp at 1 Hz'
    assert migrated == {**old, 'raw_file': migrated['raw_file']}

    # the next reprocessing finds the entry file up to date and leaves it alone
    text = entry_file.read_text()
    mtime = entry_file.stat().st_mtime_ns
    stored_archives({eid: migrated})
    parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    assert entry_file.read_text() == text
    assert entry_file.stat().st_mtime_ns == mtime


def test_particles_are_shown_and_edited_on_the_overview():
    for section in (AGE_ParticleTransportVideo, AGE_FocusSweep, AGE_ParticleTracking):
        batches = section.m_def.all_quantities['particle_batches']
        assert batches.m_annotations['eln'].component == 'ReferenceEditQuantity'
        assert batches.m_annotations['eln'].label == 'Particles'
        assert list(batches.shape) == ['*']
        assert batches.type.target_section_def is AGE_Particles.m_def
    for section in (AGE_ParticleTransportVideo, AGE_FocusSweep):
        assert 'particle_batches' in user_editable_keys(section.m_def)
    # tracks take them from their video: shown read-only
    assert 'particle_batches' not in user_editable_keys(AGE_ParticleTracking.m_def)


def particle(entry_id):
    """A particle sample as NOMAD stored it once the lab_id found its entry."""
    return instrument(entry_id)


def batch_ids(data) -> list:
    return [parse_reference(b)[1] for b in data.particle_batches]


@pytest.mark.parametrize('entry_type', WITH_OBJECTIVE)
def test_picked_particles_win_over_particle_samples(
    tmp_path, process_entry, stored_archives_context, kwargs_logger, entry_type
):
    # a save in the GUI: two batches picked, M-270 linked as sample from before
    write_measurement(
        tmp_path,
        entry_type,
        particle_batches=[
            inventory_reference('nh2'),
            inventory_reference('cooh'),
            inventory_reference('nh2'),
        ],
        samples=[particle('m270')],
    )
    context = stored_archives_context(tmp_path, INVENTORY)

    def process():
        return process_entry(
            tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
        ).data

    data = process()

    assert batch_ids(data) == ['nh2', 'cooh']
    assert not data.samples
    assert [p.name for p in data.particles] == ['micromer-M NH2', 'micromer-M COOH']
    saved = data.m_to_dict(with_root_def=True)
    with open(tmp_path / 'rec.archive.yaml', 'w') as f:
        yaml.dump({'data': saved}, f)
    again = process()
    assert batch_ids(again) == ['nh2', 'cooh']
    assert again.m_to_dict(with_root_def=True) == saved


@pytest.mark.parametrize('entry_type', RECORDINGS)
def test_particle_samples_of_older_entries_become_the_particle_batches(
    tmp_path,
    process_entry,
    stored_archives_context,
    fake_index,
    kwargs_logger,
    caplog,
    entry_type,
):
    index_inventory(fake_index, INVENTORY)
    # linked by reference, twice, or by a lab_id that NOMAD did not resolve
    samples = [particle('m270'), particle('m270'), {'name': 'NH2', 'lab_id': 'NH2'}]
    write_measurement(tmp_path, entry_type, samples=samples)
    context = stored_archives_context(tmp_path, INVENTORY)

    data = process_entry(
        tmp_path, 'rec.archive.yaml', logger=kwargs_logger, context=context
    ).data

    assert batch_ids(data) == ['m270', 'nh2']
    assert not data.samples
    assert [p.name for p in data.particles] == ['Dynabeads M-270', 'micromer-M NH2']
    assert not warning_messages(caplog)


def test_reprocessing_keeps_the_picked_particles(
    tmp_path,
    stored_archives,
    process_entry,
    stored_archives_context,
    fake_index,
    kwargs_logger,
):
    index_inventory(fake_index, INVENTORY)
    write_video(tmp_path / 'rec.h5', {**recording(ID_A), 'particles': 'M270'})
    written = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    assert written['particle_batches'] == [inventory_reference('m270')]
    # the processed archive after COOH was picked on the overview page, with
    # the particles among the samples as older versions linked them
    processed = {
        **written,
        'particle_batches': [inventory_reference('cooh')],
        'samples': [particle('cooh')],
    }
    stored_archives({get_entry_id('test_upload', 'rec.h5.archive.yaml'): processed})

    reparsed = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    assert reparsed['particle_batches'] == [inventory_reference('cooh')]
    context = stored_archives_context(tmp_path, INVENTORY)
    data = process_entry(
        tmp_path, 'rec.h5.archive.yaml', logger=kwargs_logger, context=context
    ).data
    assert batch_ids(data) == ['cooh']
    assert not data.samples


def test_tracks_take_the_picked_particles_from_the_video_entry(
    tmp_path, stored_archives_context
):
    write_video(tmp_path / 'rec.h5', recording(ID_A))
    write_tracks(tmp_path / 'rec_trajs.h5', make_tracks(), recording(ID_A))
    video = parse(ParticleTransportVideoParser(), tmp_path, 'rec.h5')
    video['particle_batches'] = [inventory_reference('nh2')]
    video['samples'] = [particle('m270')]
    with open(tmp_path / 'rec.h5.archive.yaml', 'w') as f:
        yaml.dump({'data': video}, f)
    context = stored_archives_context(tmp_path, INVENTORY)

    tracks = parse(ParticleTrackingParser(), tmp_path, 'rec_trajs.h5', context)

    assert batch_entry_ids(tracks) == ['nh2']
    assert 'samples' not in tracks
