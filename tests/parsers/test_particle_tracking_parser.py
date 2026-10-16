import base64
import io
import logging
from datetime import datetime, timezone

import h5py
import numpy as np
import pandas as pd
import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.context import ClientContext
from PIL import Image

from nomad_age.parsers import (
    focus_sweep_parser_entry_point,
    particle_tracking_parser_entry_point,
    particle_transport_video_parser_entry_point,
)
from nomad_age.parsers.particle_tracking_parser import (
    MAX_PREVIEW_WIDTH,
    ParticleTrackingParser,
    ParticleTransportVideoParser,
    build_particle_tracking_entry,
    build_video_entry,
    chip_ids_from_filename,
    find_recording_files,
    guess_illumination,
    parse_timestamp,
    plot_external_field,
    plot_first_frame,
    plot_trajectories,
    time_from_filename,
)
from nomad_age.schema_packages.age_schema import AGE_RawFile
from nomad_age.schema_packages.particle_tracking_schema import (
    AGE_ParticleTracking,
    AGE_ParticleTransportVideo,
)
from nomad_age.utils.utils import (
    get_hash_ref,
    merge_stored_values,
    user_editable_keys,
)

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

    assert entry.tracks_file is None
    assert entry.n_particles is None
    assert entry.filtered_tracks_file == 'rec_filtered_trajs.h5'
    assert entry.video_file == 'rec.h5'
    assert entry.n_particles_filtered == 2
    assert entry.n_localizations_filtered == 6
    assert entry.camera_model == 'MC2066'
    assert entry.frame_rate.to('Hz').magnitude == 100
    # 14:43:48 local summer time (UTC+2)
    assert entry.datetime == datetime(2026, 4, 15, 12, 43, 48, tzinfo=timezone.utc)
    assert entry.illumination == 'darkfield'  # the video frames are black


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
    }
    assert {'illumination', 'pixel_size', 'datetime', 'samples'} <= editable
    assert not editable & {
        'figures',
        'n_particles',
        'tracks_file',
        'frame_rate',
        'lab_id',  # the recording id comes from the files
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


def test_video_entry_shows_camera_settings_and_grayscale_first_frame(tmp_path):
    frames = np.full((3, 4, 6), 255, dtype=np.uint8)
    frames[0] = np.arange(24, dtype=np.uint8).reshape(4, 6) * 10
    write_video(tmp_path / 'rec.h5', recording(ID_A), frames)

    entry = build_video_entry(str(tmp_path / 'rec.h5'), 'sub/rec.h5')

    assert (entry.name, entry.video_file, entry.lab_id) == ('rec', 'sub/rec.h5', ID_A)
    assert (entry.n_frames, entry.frame_width, entry.frame_height) == (3, 6, 4)
    assert entry.frame_rate.to('Hz').magnitude == 100
    assert entry.duration.to('s').magnitude == pytest.approx(0.03)
    assert entry.camera_model == 'MC2066'
    assert entry.datetime == datetime(2026, 4, 15, 12, 43, 48, tzinfo=timezone.utc)
    (figure,) = entry.figures
    assert figure.label == 'First frame'
    np.testing.assert_array_equal(decode_png(figure.figure), frames[0])


def test_wide_first_frames_are_reduced_but_keep_pixel_coordinates():
    frame = np.tile((np.arange(2000) % 256).astype(np.uint8), (10, 1))

    figure = plot_first_frame(frame, 'wide.h5').to_plotly_json()

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
    assert [f.label for f in entry.figures] == ['First frame']
