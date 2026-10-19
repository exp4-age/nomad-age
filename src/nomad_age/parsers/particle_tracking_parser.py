import base64
import io
import os
import re
from datetime import datetime
from typing import Optional

import h5py
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yaml
from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.basesections import (
    CompositeSystemReference,
    InstrumentReference,
)
from nomad.datamodel.metainfo.plot import PlotlyFigure
from nomad.parsing import MatchingParser
from PIL import Image

from nomad_age.schema_packages.age_schema import AGE_RawFile, AGE_Sample
from nomad_age.schema_packages.particle_tracking_schema import (
    FROM_SAMPLES,
    AGE_FocusSweep,
    AGE_ParticleTracking,
    AGE_ParticleTransportVideo,
)
from nomad_age.utils.fingerprint import file_fingerprint
from nomad_age.utils.utils import (
    YAML_LOADER,
    create_archive,
    find_existing_AGE_sample,
    get_entry_id,
    get_hash_ref,
    get_reference,
    lab_time_to_utc,
    update_entry,
)

TRACKS_SUFFIX = '_trajs.h5'
FILTERED_TRACKS_SUFFIX = '_filtered_trajs.h5'
# Random id that the acquisition software (harvesters_pg) gives each recording;
# the tracking scripts copy it from the video into the (filtered) tracks.
RECORDING_ID_ATTR = 'recording_id'
# Optional attributes with the lab ids of the particle batches (AGE_Particles)
# and of the objective (AGE_Objective) of a recording: one id, comma-separated
# ids or a list of ids.
PARTICLES_ATTR = 'particles'
OBJECTIVE_ATTR = 'objective'
PYTABLES_ATTRS = {'CLASS', 'PYTABLES_FORMAT_VERSION', 'TITLE', 'VERSION'}
REQUIRED_TRACK_COLUMNS = ('x', 'y', 'frame', 'particle')
MAX_PLOT_TRACKS = 100
MAX_POINTS_PER_TRACK = 200
# Median pixel value relative to full scale. Rig recordings: darkfield videos
# <= 0.06, brightfield videos >= 0.44, focus sweeps 0.09-0.13.
DARKFIELD_MAX_BACKGROUND = 0.2
BRIGHTFIELD_MIN_BACKGROUND = 0.3
# Optional per-frame columns of the tracks with the external field, e.g. field_voltage.
FIELD_PREFIX = 'field_'
MAX_FIELD_POINTS = 5000
# AGE chip ids such as 2023_0418 or 2023_0325_1; '2023_0418_1hz' yields 2023_0418.
CHIP_ID_RE = re.compile(r'(?<!\d)\d{4}_\d{4}(?:_\d(?![0-9A-Za-z]))?(?!\d)')
# Lab-local date (and time) at the start of a file name: 20250227110207_...,
# 202604081623_..., 20260319_... or the date of a chip id such as 2023_0418_...
FILENAME_TIME_RE = re.compile(r'(\d{14}|\d{12}|\d{8}|\d{4}_\d{4})(?!\d)')
FILENAME_TIME_FORMATS = {14: '%Y%m%d%H%M%S', 12: '%Y%m%d%H%M', 8: '%Y%m%d'}
# The first-frame preview of a video is reduced to at most this width (px).
MAX_PREVIEW_WIDTH = 960


def recording_stem(filename: str) -> str:
    """Name of the recording that a (filtered) tracks file belongs to."""
    name = os.path.basename(filename)
    for suffix in (FILTERED_TRACKS_SUFFIX, TRACKS_SUFFIX):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    raise ValueError(f'{name} is not a *{TRACKS_SUFFIX} file')


def chip_ids_from_filename(filename: str) -> list:
    """AGE sample lab ids in a file name, in order of appearance, without repeats."""
    return list(dict.fromkeys(CHIP_ID_RE.findall(os.path.basename(filename))))


def _to_builtin(value):
    """Convert an HDF5 attribute value to builtins that safe YAML can load."""
    if isinstance(value, np.ndarray):
        return [_to_builtin(v) for v in value.tolist()]
    if isinstance(value, bytes):  # includes np.bytes_
        return value.decode('utf-8', errors='replace')
    if isinstance(value, np.generic):
        return value.item()
    return value


def read_h5_attrs(path: str) -> dict:
    """Root attributes of an HDF5 file without the PyTables bookkeeping keys."""
    with h5py.File(path, 'r') as f:
        return {
            key: _to_builtin(value)
            for key, value in f.attrs.items()
            if key not in PYTABLES_ATTRS and not isinstance(value, h5py.Empty)
        }


def parse_timestamp(value) -> Optional[datetime]:
    """UTC time of the local save time (%Y%m%d%H%M%S) of the acquisition software."""
    if isinstance(value, str) and re.fullmatch(r'\d{14}', value):
        return lab_time_to_utc(datetime.strptime(value, '%Y%m%d%H%M%S'))
    return None


def time_from_filename(filename: str) -> Optional[datetime]:
    """UTC time of the lab-local date (and time) that a file name starts with."""
    match = FILENAME_TIME_RE.match(os.path.basename(filename))
    if not match:
        return None
    digits = match.group(1).replace('_', '')
    try:
        local_time = datetime.strptime(digits, FILENAME_TIME_FORMATS[len(digits)])
    except ValueError:  # no such date, e.g. 2023_1399
        return None
    return lab_time_to_utc(local_time)


def _float_or_none(value) -> Optional[float]:
    return None if value is None else float(value)


def read_tracks(path: str) -> pd.DataFrame:
    """trackpy trajectory table stored under the key 'trajs'."""
    # Filtered tables carry an index named 'frame' next to the 'frame' column,
    # which makes sorting by 'frame' ambiguous.
    tracks = pd.read_hdf(path, key='trajs').reset_index(drop=True)
    missing = [c for c in REQUIRED_TRACK_COLUMNS if c not in tracks.columns]
    if missing:
        raise ValueError(f'{path}: trajs table lacks columns {missing}')
    return tracks


def _is_video(path: str) -> bool:
    try:
        with h5py.File(path, 'r') as f:
            return 'frames' in f
    except OSError:
        return False


def read_recording_id(path: str) -> Optional[str]:
    """The recording_id attribute of an HDF5 file; None without one."""
    try:
        with h5py.File(path, 'r') as f:
            value = f.attrs.get(RECORDING_ID_ATTR)
    except OSError:
        return None
    return None if value is None else str(_to_builtin(value))


def guess_illumination(image: np.ndarray) -> Optional[str]:
    """Darkfield images have a dark background, brightfield images a bright one.

    None if the background lies in between or the image is not integer-valued.
    """
    if not np.issubdtype(image.dtype, np.integer):
        return None
    background = np.median(image) / np.iinfo(image.dtype).max
    if background < DARKFIELD_MAX_BACKGROUND:
        return 'darkfield'
    if background > BRIGHTFIELD_MIN_BACKGROUND:
        return 'brightfield'
    return None


def _file_kind(name: str) -> Optional[str]:
    if name.endswith(FILTERED_TRACKS_SUFFIX):
        return 'filtered_tracks'
    if name.endswith(TRACKS_SUFFIX):
        return 'tracks'
    return 'video' if name.endswith('.h5') else None


def _paired_by_name(directory: str, name: str, kind: str) -> bool:
    """Whether (filtered) tracks have their filtered (unfiltered) twin by name."""
    twin = TRACKS_SUFFIX if kind == 'filtered_tracks' else FILTERED_TRACKS_SUFFIX
    return os.path.isfile(os.path.join(directory, recording_stem(name) + twin))


def find_recording_files(
    directory: str, stem: str, recording_id: Optional[str] = None
) -> dict:
    """Basenames of the tracks, filtered tracks and video of a recording.

    Files are found by name in the same directory: {stem}_trajs.h5,
    {stem}_filtered_trajs.h5 and {stem}.h5. With a recording id, a named file
    with another id belongs to another recording, and files with the same id
    count under any name, e.g. after renaming; tracks and filtered tracks that
    pair up by name are not taken apart. Missing files and videos that cannot
    be read are None.
    """
    names = {
        'tracks': f'{stem}{TRACKS_SUFFIX}',
        'filtered_tracks': f'{stem}{FILTERED_TRACKS_SUFFIX}',
        'video': f'{stem}.h5',
    }
    files = {}
    for kind, name in names.items():
        path = os.path.join(directory, name)
        found = os.path.isfile(path) and (kind != 'video' or _is_video(path))
        if found and recording_id is not None:
            found = read_recording_id(path) in (None, recording_id)
        files[kind] = name if found else None
    if recording_id is None or all(files.values()):
        return files
    for name in sorted(os.listdir(directory or '.')):
        kind = _file_kind(name)
        if kind is None or files[kind] or name in names.values():
            continue
        path = os.path.join(directory, name)
        if read_recording_id(path) != recording_id:
            continue
        if kind == 'video' and not _is_video(path):
            continue
        if kind != 'video' and _paired_by_name(directory, name, kind):
            continue
        files[kind] = name
    return files


def plot_trajectories(tracks: pd.DataFrame, source_name: str) -> go.Figure:
    """Paths of the longest tracks, each thinned to a bounded number of points."""
    selected = tracks['particle'].value_counts().nlargest(MAX_PLOT_TRACKS).index
    longest = tracks[tracks['particle'].isin(selected)].sort_values(
        ['particle', 'frame']
    )
    fig = go.Figure()
    for particle, track in longest.groupby('particle'):
        step = -(-len(track) // MAX_POINTS_PER_TRACK)
        track = track.iloc[::step]
        fig.add_trace(
            go.Scatter(
                x=track['x'].tolist(),
                y=track['y'].tolist(),
                mode='lines+markers',
                name=f'particle {particle}',
                showlegend=False,
                line=dict(width=1),
                marker=dict(size=3),
            )
        )
    fig.update_layout(
        title=f'{len(selected)} longest tracks of {source_name}',
        xaxis=dict(title='x (px)'),
        # image coordinates: origin top left, square pixels
        yaxis=dict(title='y (px)', autorange='reversed', scaleanchor='x', scaleratio=1),
    )
    return fig


def plot_external_field(
    tracks: pd.DataFrame, frame_rate: Optional[float]
) -> Optional[go.Figure]:
    """The field_* columns over time, one point per frame; None without them.

    Time is timestamp_fixed (s) if present, else frame / frame_rate, else the frame.
    """
    columns = [c for c in tracks.columns if c.startswith(FIELD_PREFIX)]
    if not columns:
        return None
    frames = tracks.drop_duplicates('frame').sort_values('frame')
    if 'timestamp_fixed' in frames.columns:
        time, time_title = frames['timestamp_fixed'], 'time (s)'
    elif frame_rate:
        time, time_title = frames['frame'] / frame_rate, 'time (s)'
    else:
        time, time_title = frames['frame'], 'frame'
    step = -(-len(frames) // MAX_FIELD_POINTS)
    fig = go.Figure()
    for column in columns:
        fig.add_trace(
            go.Scatter(
                x=time.iloc[::step].tolist(),
                y=frames[column].iloc[::step].tolist(),
                mode='lines',
                name=column,
            )
        )
    fig.update_layout(
        title='External field',
        xaxis=dict(title=time_title),
        yaxis=dict(title=', '.join(columns)),
    )
    return fig


def build_particle_tracking_entry(
    directory: str, rel_directory: str, stem: str, files: dict
) -> AGE_ParticleTracking:
    """Entry of one recording: its unfiltered tracks, or its filtered tracks if
    only these exist.

    `files` comes from find_recording_files; `directory` is where they are on
    disk, `rel_directory` is the upload-relative directory used for the links.
    """
    entry = AGE_ParticleTracking(name=stem)
    table_kind = 'tracks' if files['tracks'] else 'filtered_tracks'
    tracks = None
    if files[table_kind]:
        tracks = read_tracks(os.path.join(directory, files[table_kind]))
        entry.tracks_file = os.path.join(rel_directory, files[table_kind])
        entry.n_particles = int(tracks['particle'].nunique())
        entry.n_localizations = len(tracks)
        if len(tracks):
            entry.n_frames = int(tracks['frame'].max()) + 1
    if files['video']:
        entry.video_file = os.path.join(rel_directory, files['video'])
        with h5py.File(os.path.join(directory, files['video']), 'r') as f:
            entry.illumination = guess_illumination(f['frames'][0])

    # Older tracks lack the camera attributes.
    frame_rate = None
    for kind in (table_kind, 'video'):
        if not files[kind]:
            continue
        settings = read_h5_attrs(os.path.join(directory, files[kind]))
        if settings:
            frame_rate = _float_or_none(settings.get('fps'))
            entry.camera_settings = settings
            entry.frame_rate = frame_rate
            entry.exposure_time = _float_or_none(settings.get('ExposureTime'))
            entry.camera_model = settings.get('DeviceModelName')
            entry.lab_id = settings.get(RECORDING_ID_ATTR)
            entry.datetime = parse_timestamp(settings.get('timestamp'))
            break
    if entry.datetime is None:
        entry.datetime = time_from_filename(stem)

    figures = []
    if tracks is not None and len(tracks):
        trajectories = plot_trajectories(tracks, files[table_kind])
        figures.append(
            PlotlyFigure(label='Trajectories', figure=trajectories.to_plotly_json())
        )
        field = plot_external_field(tracks, frame_rate)
        if field is not None:
            figures.append(
                PlotlyFigure(label='External field', figure=field.to_plotly_json())
            )
    if figures:
        entry.figures = figures
    return entry


def plot_focus_sweep(
    z_position: list,
    tenengrad: list,
    max_focus: Optional[float],
    max_slope: Optional[float],
) -> go.Figure:
    fig = go.Figure(
        go.Scatter(x=z_position, y=tenengrad, mode='lines+markers', name='Tenengrad')
    )
    for label, position in (('maxfocus', max_focus), ('maxslope', max_slope)):
        if position is not None:
            fig.add_vline(x=position, line_dash='dash', annotation_text=label)
    fig.update_layout(
        xaxis=dict(title='z position (µm)'),
        yaxis=dict(title='Tenengrad (a.u.)'),
    )
    return fig


def build_focus_sweep_entry(path: str, rel_path: str) -> AGE_FocusSweep:
    """Entry of a focus sweep file; `rel_path` is its upload-relative path."""
    with h5py.File(path, 'r') as f:
        n_images = f['imgs'].shape[0]  # only the first image is loaded
        illumination = guess_illumination(f['imgs'][0])
        z_position = f['poss'][()].tolist()
        tenengrad = f['tgs'][()].tolist()
    attrs = read_h5_attrs(path)
    max_focus = _float_or_none(attrs.get('maxfocus'))
    max_slope = _float_or_none(attrs.get('maxslope'))
    entry = AGE_FocusSweep(
        name=os.path.splitext(os.path.basename(path))[0],
        data_file=rel_path,
        n_images=n_images,
        illumination=illumination,
        z_position=z_position,
        tenengrad=tenengrad,
        max_focus_position=max_focus,
        max_slope_position=max_slope,
        last_position=_float_or_none(attrs.get('last_position')),
        datetime=parse_timestamp(attrs.get('timestamp')) or time_from_filename(path),
    )
    figure = plot_focus_sweep(z_position, tenengrad, max_focus, max_slope)
    entry.figures = [PlotlyFigure(label='Focus Sweep', figure=figure.to_plotly_json())]
    return entry


def grayscale_uint8(frame: np.ndarray) -> np.ndarray:
    """A video frame as 8-bit grayscale; colour channels are averaged."""
    if frame.ndim == 3:
        frame = frame.mean(axis=-1).astype(frame.dtype)
    if frame.dtype == np.uint8:
        return frame
    if np.issubdtype(frame.dtype, np.integer):
        full_scale = np.iinfo(frame.dtype).max
    else:
        full_scale = float(np.nanmax(frame)) or 1.0
    return np.clip(np.nan_to_num(frame) * (255 / full_scale), 0, 255).astype(np.uint8)


def plot_frame(frame: np.ndarray, title: str) -> go.Figure:
    """A video frame in grayscale, embedded as PNG image.

    Frames wider than MAX_PREVIEW_WIDTH keep every n-th pixel; the axes stay in
    pixels of the full frame.
    """
    step = -(-frame.shape[1] // MAX_PREVIEW_WIDTH)
    image = np.ascontiguousarray(grayscale_uint8(frame)[::step, ::step])
    png = io.BytesIO()
    Image.fromarray(image).save(png, format='PNG', optimize=True)
    source = 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()
    fig = go.Figure(go.Image(source=source, dx=step, dy=step))
    fig.update_layout(
        title=title,
        xaxis=dict(title='x (px)'),
        # image coordinates as in the trajectory plot: origin top left
        yaxis=dict(title='y (px)', autorange='reversed', scaleanchor='x', scaleratio=1),
    )
    return fig


def build_video_entry(path: str, rel_path: str) -> AGE_ParticleTransportVideo:
    """Entry of a particle transport video; `rel_path` is its upload-relative path."""
    name = os.path.basename(path)
    with h5py.File(path, 'r') as f:
        frames = f['frames']
        n_frames, height, width = frames.shape[:3]
        # only the first and the last frame are read
        first_frame = frames[0] if n_frames else None
        last_frame = frames[n_frames - 1] if n_frames > 1 else None
    attrs = read_h5_attrs(path)
    frame_rate = _float_or_none(attrs.get('fps'))
    entry = AGE_ParticleTransportVideo(
        name=os.path.splitext(name)[0],
        video_file=rel_path,
        lab_id=attrs.get(RECORDING_ID_ATTR),
        frame_rate=frame_rate,
        exposure_time=_float_or_none(attrs.get('ExposureTime')),
        camera_model=attrs.get('DeviceModelName'),
        n_frames=n_frames,
        frame_width=width,
        frame_height=height,
        duration=n_frames / frame_rate if frame_rate else None,
        datetime=parse_timestamp(attrs.get('timestamp')) or time_from_filename(path),
        camera_settings=attrs or None,
    )
    link_particles_and_objective(entry, attrs)
    if first_frame is not None:
        entry.illumination = guess_illumination(first_frame)
        figure = plot_frame(first_frame, f'First frame of {name}')
        entry.figures = [
            PlotlyFigure(label='First frame', figure=figure.to_plotly_json())
        ]
    if last_frame is not None:
        at = f', {(n_frames - 1) / frame_rate:.2f} s' if frame_rate else ''
        title = f'Last frame of {name} (frame {n_frames - 1}{at})'
        figure = plot_frame(last_frame, title)
        entry.figures.append(
            PlotlyFigure(label='Last frame', figure=figure.to_plotly_json())
        )
    return entry


def link_AGE_samples(entry, lab_ids: list, archive: EntryArchive, logger) -> None:
    """Reference the AGE samples with the given lab ids; create missing ones."""
    main_author = archive.metadata.main_author
    # Without a user id the search only sees published samples.
    user_id = main_author.user_id if main_author else None
    for lab_id in lab_ids:
        hits = find_existing_AGE_sample(lab_id, user_id=user_id).data
        if len(hits) > 1:
            logger.error(
                f'Found {len(hits)} AGE samples with lab_id {lab_id}; not linked.'
            )
            continue
        if hits:
            # The sample may live in another upload.
            reference = get_reference(hits[0]['upload_id'], hits[0]['entry_id'])
            reference += '#data'
        else:
            sample_file = f'{lab_id}.archive.yaml'
            create_archive(AGE_Sample(name=lab_id, lab_id=lab_id), archive, sample_file)
            reference = get_hash_ref(archive.metadata.upload_id, sample_file)
        entry.samples.append(
            CompositeSystemReference(name=lab_id, lab_id=lab_id, reference=reference)
        )


def lab_ids_from_attr(value) -> list:
    """Lab ids in an attribute value: one id, comma-separated ids or a list."""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    ids = (part.strip() for v in values for part in str(v).split(','))
    return list(dict.fromkeys(i for i in ids if i))


def link_particles_and_objective(entry, attrs: dict) -> None:
    """Link the particle batches and the objective that the attributes name.

    Only the lab ids are set; when NOMAD normalizes the entry, it resolves them
    to the inventory entries with these ids.
    """
    linked = {sample.lab_id for sample in entry.samples}
    for lab_id in lab_ids_from_attr(attrs.get(PARTICLES_ATTR)):
        if lab_id not in linked:
            entry.samples.append(CompositeSystemReference(name=lab_id, lab_id=lab_id))
    linked = {instrument.lab_id for instrument in entry.instruments}
    for lab_id in lab_ids_from_attr(attrs.get(OBJECTIVE_ATTR)):
        if lab_id not in linked:
            entry.instruments.append(InstrumentReference(name=lab_id, lab_id=lab_id))


def video_samples_and_instruments(archive: EntryArchive, rel_video: str):
    """Samples and instruments of the entry of a video (upload-relative path), as
    stored in its YAML; None if the video has no entry."""
    entry_file = f'{rel_video}.archive.yaml'
    if not archive.m_context.raw_path_exists(entry_file):
        return None
    with archive.m_context.raw_file(entry_file) as f:
        data = yaml.load(f, Loader=YAML_LOADER).get('data') or {}
    samples = data.get('samples') or []
    instruments = data.get('instruments') or []
    return (
        [CompositeSystemReference.m_from_dict(sample) for sample in samples],
        [InstrumentReference.m_from_dict(instrument) for instrument in instruments],
    )


def raw_os_path(context, rel_path: str) -> Optional[str]:
    """OS path of a raw file of the upload of `context`; None without access."""
    if getattr(context, 'upload', None) is not None:  # ServerContext
        return os.path.join(context.raw_path(), rel_path)
    local_dir = getattr(context, 'local_dir', None)  # ClientContext
    return os.path.join(local_dir, rel_path) if local_dir else None


def tracks_entry_files(context) -> Optional[list]:
    """Upload-relative paths of the tracks entry files of the upload of
    `context`, sorted; None without access to its raw files.

    Entries of filtered tracks (recordings uploaded without their unfiltered
    tracks) do not count.
    """
    root = raw_os_path(context, '')
    if root is None or not os.path.isdir(root):
        return None
    suffix = f'{TRACKS_SUFFIX}.archive.yaml'
    filtered_suffix = f'{FILTERED_TRACKS_SUFFIX}.archive.yaml'
    entry_files = []
    for directory, _, names in os.walk(root):
        for name in names:
            if name.endswith(suffix) and not name.endswith(filtered_suffix):
                path = os.path.join(directory, name)
                entry_files.append(os.path.relpath(path, root))
    return sorted(entry_files)


def share_with_tracks(video, archive: EntryArchive, logger) -> None:
    """Give the tracks entries of a video's recording the samples and instruments
    of the video entry, so that they are edited in one place, and a reference to
    the video entry.

    The tracks are found as their parser finds the video: in the same folder, by
    name or recording id. Tracks entries that change are written and processed
    again.
    """
    if not video.video_file:
        return
    path = raw_os_path(archive.m_context, video.video_file)
    if path is None or not os.path.isfile(path):
        return
    directory, video_name = os.path.split(path)
    rel_directory = os.path.dirname(video.video_file)
    upload_id = archive.metadata.upload_id
    shared = {
        'samples': [sample.m_to_dict() for sample in video.samples],
        'instruments': [instrument.m_to_dict() for instrument in video.instruments],
        'video': get_hash_ref(upload_id, f'{video.video_file}.archive.yaml'),
    }
    for name in sorted(os.listdir(directory)):
        entry_file = os.path.join(rel_directory, f'{name}.archive.yaml')
        if not name.endswith(TRACKS_SUFFIX):
            continue
        if not archive.m_context.raw_path_exists(entry_file):
            continue  # filtered tracks next to their unfiltered tracks
        recording_id = read_recording_id(os.path.join(directory, name))
        files = find_recording_files(directory, recording_stem(name), recording_id)
        if files['video'] != video_name:
            continue
        with archive.m_context.raw_file(entry_file) as f:
            data = yaml.load(f, Loader=YAML_LOADER)['data']
        # as the tracks parser sets it, which may not have run since an update
        wanted = {
            **shared,
            'raw_file': get_hash_ref(upload_id, os.path.join(rel_directory, name)),
        }
        if all(
            (data.get(key) or None) == (value or None) for key, value in wanted.items()
        ):
            continue
        data.update(wanted)
        # e.g. the filtered counts that older versions wrote, or particles, chips
        # and spacer thickness that a save in the GUI wrote
        defined = AGE_ParticleTracking.m_def.all_properties
        tracks = AGE_ParticleTracking.m_from_dict(
            {
                key: value
                for key, value in data.items()
                if key in defined and key not in FROM_SAMPLES
            }
        )
        create_archive(tracks, archive, entry_file, overwrite=True)
        logger.info(f'Samples, instruments and video of {name} taken from {video_name}')


def store_entry(
    entry,
    archive: EntryArchive,
    mainfile: str,
    file_type: str,
    logger,
    parsed_wins=(),
    parser_owned=(),
) -> None:
    """Write `entry`, parsed from `mainfile` (a `file_type`), as YAML entry next
    to it; the entry of `mainfile` itself records the file and links both ways.

    On reprocessing, stored values that users may edit win, except for the keys
    in `parsed_wins`; stored values of the keys in `parser_owned` and of
    FROM_SAMPLES, which the stored archive holds as normalizer output, are
    dropped."""
    upload_id = archive.metadata.upload_id
    rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
    entry_file_name = f'{rel_mainfile}.archive.yaml'
    archive.data = AGE_RawFile(
        file_name=rel_mainfile,
        file_type=file_type,
        processed_archive=get_hash_ref(upload_id, entry_file_name),
        **file_fingerprint(mainfile),
    )
    entry.raw_file = get_hash_ref(upload_id, rel_mainfile)
    if not create_archive(entry, archive, entry_file_name):
        eid = get_entry_id(upload_id, entry_file_name)
        parser_owned = (*parser_owned, *FROM_SAMPLES)
        merged = update_entry(entry, eid, archive, logger, parsed_wins, parser_owned)
        create_archive(merged, archive, entry_file_name, overwrite=True)


class ParticleTrackingParser(MatchingParser):
    def is_mainfile(
        self,
        filename: str,
        mime: str,
        buffer: bytes,
        decoded_buffer: str,
        compression: Optional[str] = None,
    ):
        is_match = super().is_mainfile(
            filename, mime, buffer, decoded_buffer, compression
        )
        if is_match and filename.endswith(FILTERED_TRACKS_SUFFIX):
            # One entry per recording: the unfiltered tracks are its mainfile.
            files = find_recording_files(
                os.path.dirname(filename),
                recording_stem(filename),
                read_recording_id(filename),
            )
            return files['tracks'] is None
        return is_match

    def parse(
        self, mainfile: str, archive: EntryArchive, logger, child_archives=None
    ) -> None:
        logger.info(f'ParticleTrackingParser called on {mainfile}')
        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        directory = os.path.dirname(mainfile)
        rel_directory = os.path.dirname(rel_mainfile)
        stem = recording_stem(mainfile)
        files = find_recording_files(directory, stem, read_recording_id(mainfile))
        entry = build_particle_tracking_entry(directory, rel_directory, stem, files)
        from_video = None
        parsed_wins = ()
        if files['video']:
            rel_video = os.path.join(rel_directory, files['video'])
            entry.video = get_hash_ref(
                archive.metadata.upload_id, f'{rel_video}.archive.yaml'
            )
            parsed_wins = ('video',)
            from_video = video_samples_and_instruments(archive, rel_video)
        if from_video is None:
            link_AGE_samples(entry, chip_ids_from_filename(mainfile), archive, logger)
            link_particles_and_objective(entry, entry.camera_settings or {})
        else:
            # Samples and instruments of a recording are edited in its video entry.
            samples, instruments = from_video
            for sample in samples:
                entry.samples.append(sample)
            for instrument in instruments:
                entry.instruments.append(instrument)
            parsed_wins += ('samples', 'instruments')
        file_type = (
            'filtered trajectories'
            if mainfile.endswith(FILTERED_TRACKS_SUFFIX)
            else 'trajectories'
        )
        # Figures of filtered tracks, which older versions plotted, do not stay.
        store_entry(
            entry,
            archive,
            mainfile,
            file_type,
            logger,
            parsed_wins,
            parser_owned=('figures',),
        )


class FocusSweepParser(MatchingParser):
    def parse(
        self, mainfile: str, archive: EntryArchive, logger, child_archives=None
    ) -> None:
        logger.info(f'FocusSweepParser called on {mainfile}')
        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        entry = build_focus_sweep_entry(mainfile, rel_mainfile)
        link_AGE_samples(entry, chip_ids_from_filename(mainfile), archive, logger)
        store_entry(entry, archive, mainfile, 'focus sweep', logger)


class ParticleTransportVideoParser(MatchingParser):
    def parse(
        self, mainfile: str, archive: EntryArchive, logger, child_archives=None
    ) -> None:
        logger.info(f'ParticleTransportVideoParser called on {mainfile}')
        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        entry = build_video_entry(mainfile, rel_mainfile)
        link_AGE_samples(entry, chip_ids_from_filename(mainfile), archive, logger)
        store_entry(entry, archive, mainfile, 'particle transport video', logger)
