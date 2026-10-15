import os
import re
from datetime import datetime
from typing import Optional

import h5py
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.basesections import CompositeSystemReference
from nomad.datamodel.metainfo.plot import PlotlyFigure
from nomad.parsing import MatchingParser

from nomad_age.schema_packages.age_schema import AGE_RawFile, AGE_Sample
from nomad_age.schema_packages.particle_tracking_schema import (
    AGE_FocusSweep,
    AGE_ParticleTracking,
)
from nomad_age.utils.utils import (
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
PYTABLES_ATTRS = {'CLASS', 'PYTABLES_FORMAT_VERSION', 'TITLE', 'VERSION'}
REQUIRED_TRACK_COLUMNS = ('x', 'y', 'frame', 'particle')
MAX_PLOT_TRACKS = 100
MAX_POINTS_PER_TRACK = 200
# Median pixel value relative to full scale. Rig recordings: darkfield videos
# <= 0.06, brightfield videos >= 0.44, focus sweeps 0.09-0.13.
DARKFIELD_MAX_BACKGROUND = 0.2
BRIGHTFIELD_MIN_BACKGROUND = 0.3
# AGE chip ids such as 2023_0418 or 2023_0325_1; '2023_0418_1hz' yields 2023_0418.
CHIP_ID_RE = re.compile(r'(?<!\d)\d{4}_\d{4}(?:_\d(?![0-9A-Za-z]))?(?!\d)')


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


def find_recording_files(directory: str, stem: str) -> dict:
    """Basenames of the tracks, filtered tracks and video of a recording.

    Only exact names in the same directory count; missing files and videos that
    cannot be read are None.
    """
    files = {
        'tracks': f'{stem}{TRACKS_SUFFIX}',
        'filtered_tracks': f'{stem}{FILTERED_TRACKS_SUFFIX}',
        'video': f'{stem}.h5',
    }
    for kind, name in files.items():
        path = os.path.join(directory, name)
        if not os.path.isfile(path) or (kind == 'video' and not _is_video(path)):
            files[kind] = None
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


def build_particle_tracking_entry(
    directory: str, rel_directory: str, stem: str, files: dict
) -> AGE_ParticleTracking:
    """Entry of one recording.

    `files` comes from find_recording_files; `directory` is where they are on
    disk, `rel_directory` is the upload-relative directory used for the links.
    """
    entry = AGE_ParticleTracking(name=stem)
    tracks = filtered = None
    if files['tracks']:
        tracks = read_tracks(os.path.join(directory, files['tracks']))
        entry.tracks_file = os.path.join(rel_directory, files['tracks'])
        entry.n_particles = int(tracks['particle'].nunique())
        entry.n_localizations = len(tracks)
    if files['filtered_tracks']:
        filtered = read_tracks(os.path.join(directory, files['filtered_tracks']))
        entry.filtered_tracks_file = os.path.join(
            rel_directory, files['filtered_tracks']
        )
        entry.n_particles_filtered = int(filtered['particle'].nunique())
        entry.n_localizations_filtered = len(filtered)
    if files['video']:
        entry.video_file = os.path.join(rel_directory, files['video'])
        with h5py.File(os.path.join(directory, files['video']), 'r') as f:
            entry.illumination = guess_illumination(f['frames'][0])

    frame_source = tracks if tracks is not None else filtered
    if frame_source is not None and len(frame_source):
        entry.n_frames = int(frame_source['frame'].max()) + 1

    # Older tracks and all filtered tracks lack the camera attributes.
    for kind in ('tracks', 'filtered_tracks', 'video'):
        if not files[kind]:
            continue
        settings = read_h5_attrs(os.path.join(directory, files[kind]))
        if settings:
            entry.camera_settings = settings
            entry.frame_rate = _float_or_none(settings.get('fps'))
            entry.exposure_time = _float_or_none(settings.get('ExposureTime'))
            entry.camera_model = settings.get('DeviceModelName')
            entry.datetime = parse_timestamp(settings.get('timestamp'))
            break

    plot_kind = 'filtered_tracks' if filtered is not None else 'tracks'
    plot_tracks = filtered if filtered is not None else tracks
    if plot_tracks is not None and len(plot_tracks):
        figure = plot_trajectories(plot_tracks, files[plot_kind])
        entry.figures = [
            PlotlyFigure(label='Trajectories', figure=figure.to_plotly_json())
        ]
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
        datetime=parse_timestamp(attrs.get('timestamp')),
    )
    figure = plot_focus_sweep(z_position, tenengrad, max_focus, max_slope)
    entry.figures = [PlotlyFigure(label='Focus Sweep', figure=figure.to_plotly_json())]
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


def store_entry(entry, archive: EntryArchive, entry_file_name: str, logger) -> None:
    """Write `entry` as YAML entry; on reprocessing, existing values win."""
    upload_id = archive.metadata.upload_id
    archive.data = AGE_RawFile(
        processed_archive=get_hash_ref(upload_id, entry_file_name)
    )
    if not create_archive(entry, archive, entry_file_name):
        merged = update_entry(
            entry, get_entry_id(upload_id, entry_file_name), archive, logger
        )
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
            unfiltered = filename[: -len(FILTERED_TRACKS_SUFFIX)] + TRACKS_SUFFIX
            return not os.path.isfile(unfiltered)
        return is_match

    def parse(
        self, mainfile: str, archive: EntryArchive, logger, child_archives=None
    ) -> None:
        logger.info(f'ParticleTrackingParser called on {mainfile}')
        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        directory = os.path.dirname(mainfile)
        stem = recording_stem(mainfile)
        entry = build_particle_tracking_entry(
            directory,
            os.path.dirname(rel_mainfile),
            stem,
            find_recording_files(directory, stem),
        )
        link_AGE_samples(entry, chip_ids_from_filename(mainfile), archive, logger)
        store_entry(entry, archive, f'{rel_mainfile}.archive.yaml', logger)


class FocusSweepParser(MatchingParser):
    def parse(
        self, mainfile: str, archive: EntryArchive, logger, child_archives=None
    ) -> None:
        logger.info(f'FocusSweepParser called on {mainfile}')
        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        entry = build_focus_sweep_entry(mainfile, rel_mainfile)
        link_AGE_samples(entry, chip_ids_from_filename(mainfile), archive, logger)
        store_entry(entry, archive, f'{rel_mainfile}.archive.yaml', logger)
