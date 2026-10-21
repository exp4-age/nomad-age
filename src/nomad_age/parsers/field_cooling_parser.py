import os
import re
from datetime import datetime, timedelta

import numpy as np
import plotly.graph_objects as go
from nomad.config import config
from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.plot import PlotlyFigure
from nomad.parsing import MatchingParser
from plotly.subplots import make_subplots

from nomad_age.schema_packages.age_schema import AGE_RawFile, AGE_Sample_Reference
from nomad_age.schema_packages.field_cooling_schema import AGE_FieldCooling
from nomad_age.utils.fingerprint import file_fingerprint
from nomad_age.utils.utils import (
    create_archive,
    find_chip_reference,
    get_entry_id,
    get_hash_ref,
    lab_time_to_utc,
    normalize_sample_id,
    update_entry,
)

configuration = config.get_plugin_entry_point(
    'nomad_age.parsers:field_cooling_parser_entry_point'
)

# Sample ids such as 2023_0418, 2023_0418_1 or the broken chip 2023_0418_1_2.
SAMPLE_ID_RE = re.compile(r'\d{4}_\d{4}(?:_\d+)*')


def parse_date(date_str: str) -> datetime:
    # Replace any sequence of spaces or tabs with a single space
    cleaned = re.sub(r'[ \t]+', ' ', date_str.strip())
    return datetime.strptime(cleaned, '%Y.%m.%d %H:%M:%S')


PLOT_POINTS = 2000  # per trace; the full data stays in the entry
PLATEAU_TOLERANCE = 5.0  # K around the blocking temperature
PLATEAU_SHORTFALL = 2.0  # min a plateau may be shorter than set without a warning


def downsample(t, *ys, n=PLOT_POINTS):
    """Indices of at most ~n points of the series, keeping each bucket's first
    point and the extrema of every y, so peaks and dips survive."""
    size = len(t)
    if size <= n:
        return np.arange(size)
    buckets = max(1, n // (1 + 2 * len(ys)))
    edges = np.linspace(0, size, buckets + 1, dtype=int)
    keep = {0, size - 1}
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        keep.add(a)
        for y in ys:
            seg = y[a:b]
            keep.add(a + int(np.argmin(seg)))
            keep.add(a + int(np.argmax(seg)))
    return np.array(sorted(keep))


def process_summary(t, temperature, penning, blocking_temperature):
    """Values of the real process, from the data: max temperature, plateau
    duration within ±PLATEAU_TOLERANCE of the blocking temperature, mean cooling
    rate after the plateau, lowest Penning pressure."""
    summary = {
        'max_temperature': float(np.max(temperature)),
        'min_penning_pressure': float(np.min(penning)),
    }
    if blocking_temperature is None or len(t) < 2:
        return summary
    dt = np.diff(t, append=t[-1])
    near = np.abs(temperature - blocking_temperature) <= PLATEAU_TOLERANCE
    if not near.any():
        summary['measured_plateau_duration'] = 0.0
        return summary
    summary['measured_plateau_duration'] = float(dt[near].sum() / 60)
    end = np.flatnonzero(near)[-1]
    if t[-1] > t[end]:
        summary['measured_cooling_rate'] = float(
            (temperature[end] - temperature[-1]) / ((t[-1] - t[end]) / 60)
        )
    return summary


def plot_field_cooling_data(
    time, measured_temperature, target_temperature, pirani_pressure, penning_pressure
) -> PlotlyFigure:
    fig = make_subplots(specs=[[{'secondary_y': True}]])

    # Temperature traces
    fig.add_trace(
        go.Scatter(
            x=time,
            y=measured_temperature,
            mode='lines',
            name='Measured Temperature',
            yaxis='y1',
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=target_temperature,
            mode='lines',
            name='Target Temperature',
            line=dict(dash='dash'),
            yaxis='y1',
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=time,
            y=penning_pressure,
            mode='lines',
            name='Penning Pressure',
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=time,
            y=pirani_pressure,
            mode='lines',
            name='Pirani Pressure',
            visible='legendonly',
        ),
        secondary_y=True,
    )

    # Layout with two y-axes
    fig.update_layout(
        # title='Field Cooling: Temperature and Pressure over Time',
        showlegend=True,
        xaxis=dict(title='Time (s)', fixedrange=False),
        yaxis=dict(title='Temperature (°C)', side='left'),
        yaxis2=dict(
            title='Pressure (mbar)',
            type='log',
            showgrid=False,
            side='right',
            overlaying='y',
            zeroline=False,
            exponentformat='e',
        ),
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.01,
            xanchor='right',
            x=1,
        ),
    )

    return fig


class FieldCoolingParser(MatchingParser):
    def parse(self, mainfile: str, archive: EntryArchive, logger):
        logger.info(
            f'FieldCoolingParser called on {mainfile}',
            configuration=configuration.parameter,
        )
        """
        Create a new entry for the field cooling data.
        Later create a new archive out of this.
        Everyting called archive in here, is the original .DAT logfile!
        """
        uid = archive.metadata.upload_id
        entry = AGE_FieldCooling()
        entry_file_name = f'{os.path.basename(mainfile)}.archive.yaml'
        eid = get_entry_id(uid, entry_file_name)
        entry.data_file = os.path.basename(mainfile)  # the original log file

        entry.instrument = 'Fieldcooling'
        entry.location = 'BAHAMAS'
        entry.field_source = 'permanent magnet'  # a GUI edit wins on reparse

        with open(mainfile, encoding='latin1') as f:
            content = f.read()

        # Parse metadata
        start_time = None
        sample_names = []
        for line in content.split('\n'):
            if 'Probenname:' in line:
                lineend = line.split(':')[1].strip()
                sample_names = SAMPLE_ID_RE.findall(lineend)
                if not sample_names:
                    # If there is no sample name found, it's probably only a comment
                    entry.description = line.split(':')[1].strip()
                else:
                    # Ceck if there is more text than just the sample names
                    rest = SAMPLE_ID_RE.sub('', lineend).replace(',', '')
                    if (
                        len(rest.strip()) > 0
                    ):  # if there is more than just the sample, add it to description
                        entry.description = lineend
            elif 'Datum:' in line:
                start_time = parse_date(line.split(':', 1)[1].strip())
                entry.datetime = lab_time_to_utc(start_time)
            elif 'T(Blocking)' in line:
                entry.blocking_temperature = float(line.split(':')[1])
            elif 'Plateuzeit' in line:
                entry.plateau_duration = float(line.split(':')[1].replace(',', '.'))
            elif 'hlrate [' in line:  # circumventing issues with the umlaut
                entry.cooling_rate = float(line.split(':')[1].replace(',', '.'))

        if entry.cooling_rate is not None:
            entry.cooling_mode = (
                'natural' if entry.cooling_rate.magnitude == 0 else 'controlled'
            )

        if start_time:
            name = f'FC_{start_time}'
        else:
            name = f'FC_{mainfile.split("/")[-1].split(".DAT")[0]}'
        entry.name = name

        # Parse time-series data
        data_table = []
        in_data_section = False

        for line in content.split('\n'):
            if line.startswith('#Zeit [s]#'):
                in_data_section = True
                continue

            if in_data_section and line.strip() and not line.startswith('#'):
                values = list(map(float, line.strip().split('\t')))
                if len(values) == 5:
                    data_table.append(values)

        if data_table:
            data = np.array(data_table)
            entry.time = data[:, 0].tolist()
            if start_time:
                entry.end_time = lab_time_to_utc(start_time) + timedelta(
                    seconds=data[:, 0].tolist()[-1]
                )
            entry.measured_temperature = data[:, 1].tolist()
            entry.target_temperature = data[:, 2].tolist()
            entry.pirani_pressure = data[:, 3].tolist()
            entry.penning_pressure = data[:, 4].tolist()

            t, T, T_set, pirani, penning = data.T
            keep = downsample(t, T, T_set, pirani, penning)
            fig = plot_field_cooling_data(
                t[keep].tolist(),
                T[keep].tolist(),
                T_set[keep].tolist(),
                pirani[keep].tolist(),
                penning[keep].tolist(),
            )
            blocking = entry.blocking_temperature
            summary = process_summary(
                t, T, penning, None if blocking is None else blocking.magnitude
            )
            for key, value in summary.items():
                setattr(entry, key, value)
            measured = summary.get('measured_plateau_duration')
            if (
                entry.plateau_duration is not None
                and measured is not None
                and measured < entry.plateau_duration.magnitude - PLATEAU_SHORTFALL
            ):
                logger.warning(
                    f'Plateau shorter than set: {measured:.1f} min within '
                    f'±{PLATEAU_TOLERANCE:g} K of the blocking temperature, set '
                    f'{entry.plateau_duration.magnitude:g} min'
                )
            entry.figures = [
                PlotlyFigure(label='Field Cooling Plot', figure=fig.to_plotly_json())
            ]

        # Chips live in the AGE Samples upload: link them, never create them.
        for lab_id in dict.fromkeys(map(normalize_sample_id, sample_names)):
            entry.samples.append(
                AGE_Sample_Reference(
                    name=lab_id,
                    lab_id=lab_id,
                    reference=find_chip_reference(lab_id, archive, logger),
                )
            )

        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        archive.data = AGE_RawFile(
            file_name=rel_mainfile,
            file_type='field cooling log',
            processed_archive=get_hash_ref(uid, entry_file_name),
            **file_fingerprint(mainfile),
        )
        entry.raw_file = get_hash_ref(uid, rel_mainfile)
        new_entry_created = create_archive(entry, archive, entry_file_name)
        if not new_entry_created:
            # The samples are parsed from the log: stale references go.
            new_entry = update_entry(
                entry, eid, archive, logger, parsed_wins=('samples',)
            )
            if new_entry is not None:
                create_archive(new_entry, archive, entry_file_name, overwrite=True)
