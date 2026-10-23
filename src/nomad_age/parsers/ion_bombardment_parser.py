"""Parser for the logs of the helium ion bombardment (ISA) software, *logger.txt.

The log has no chip id. The chip is taken from the L-MOKE files next to the log
(<chip>_LMOKE_*.txt) if they name exactly one chip; users can change it in the
GUI, their choice wins on reprocessing.

Log formats are told apart by `detect_format_version`; each version has its own
reader in READERS. To support a rewritten ISA software, teach
`detect_format_version` to recognise it and add a reader for it.
"""

import ast
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import plotly.graph_objects as go
from nomad.config import config
from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.plot import PlotlyFigure
from nomad.parsing import MatchingParser
from plotly.subplots import make_subplots

from nomad_age.parsers.field_cooling_parser import downsample
from nomad_age.schema_packages.age_schema import AGE_RawFile, AGE_Sample_Reference
from nomad_age.schema_packages.ion_bombardment_schema import (
    AGE_IonBombardment,
    AGE_IonBombardmentPoint,
)
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
    'nomad_age.parsers:ion_bombardment_parser_entry_point'
)

FILENAME_TIME_RE = re.compile(r'(\d{8}_\d{6})_logger\.txt$')
LMOKE_CHIP_RE = re.compile(r'^(\d{4}_\d{4}(?:_\d+)*)_LMOKE_.*\.txt$')
VERSION_LINE_RE = re.compile(
    r'^\W*(?:ISA\s+)?(?:log(?:ger)?\s+)?version\s*[:=]\s*(\S+)', re.I
)
V1_HEADER = 'Time [hh:mm:ss]'
POINT_RE = re.compile(r'^(Point(\d+))\s*:\s*(\[.*\])\s*$')

# column title in the v1 log -> quantity of AGE_IonBombardment (None: summary only)
V1_COLUMNS = {
    'PrePressure': 'pre_pressure',
    'ChamberPressure': 'chamber_pressure',
    'SourcePressure': 'source_pressure',
    'SourceSetpoint': None,
    'BeamCurrent': 'beam_current',
    'LensSetpoint': None,
    'MagnetSetpoint': None,
    'MagnetCurrent': 'magnet_current',
    'PlasmaCurrent': 'plasma_current',
    'PlasmaVoltage': 'plasma_voltage',
    'Xpos': 'x_position',
    'Ypos': 'y_position',
}


def detect_format_version(lines: list) -> Optional[str]:
    """Format version of an ISA log, None if unknown.

    A rewritten software is expected to write a version line at the top (e.g.
    `Version: 2`); the current one (version '1') writes none and starts with a
    dashed line and the tab-separated column header `Time [hh:mm:ss] ...`.
    """
    for line in lines[:10]:
        match = VERSION_LINE_RE.match(line.strip())
        if match:
            return match.group(1)
    head = [line.strip() for line in lines[:5] if line.strip()]
    if len(head) >= 2 and head[0].startswith('---') and head[1].startswith(V1_HEADER):
        return '1'
    return None


def start_date(mainfile: str) -> Optional[datetime]:
    """Wall-clock start of the run from the file name YYYYMMDD_HHMMSS_logger.txt."""
    match = FILENAME_TIME_RE.search(os.path.basename(mainfile))
    if not match:
        return None
    return datetime.strptime(match.group(1), '%Y%m%d_%H%M%S')


def parse_point(line: str) -> Optional[dict]:
    """One row of the positions table, e.g.
    Point6: [[0.300,0.250],3.5e15,True,True,179.8547,['3.5e15']]
    as [[x, y], dose wanted, assigned, bombarded, time or velocity, dose bombarded]."""
    match = POINT_RE.match(line.strip())
    if not match:
        return None
    name, number, body = match.groups()
    (x, y), wanted, assigned, bombarded, time, done = ast.literal_eval(body)
    record = done if isinstance(done, (list, tuple)) else [done]
    return {
        'name': name,
        'number': int(number),
        'x': float(x),
        'y': float(y),
        'dose_wanted': float(wanted),
        'assigned': bool(assigned),
        'bombarded': bool(bombarded),
        'bombardment_time': float(time),
        'dose_bombarded': float(sum(float(d) for d in record)),
        'dose_record': ', '.join(str(d) for d in record),
    }


def read_v1(lines: list, start: Optional[datetime], logger) -> dict:
    """Columns, clock times and positions of a log of the current ISA software."""
    header = None
    rows, clock, points = [], [], []
    in_points = False
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith(V1_HEADER):
            header = [re.sub(r'\s*\[.*\]$', '', c.strip()) for c in line.split('\t')]
            continue
        if text.startswith('Positions Dictionary'):
            in_points = True
            continue
        if in_points:
            if text.startswith('Point'):
                try:
                    point = parse_point(text)
                except (ValueError, SyntaxError) as e:
                    logger.warning(f'Unreadable position line {text!r}: {e!r}')
                    continue
                if point:
                    points.append(point)
            continue
        if text.startswith('-') or header is None:
            continue
        cells = line.rstrip('\r\n').split('\t')
        if len(cells) != len(header):
            logger.warning(f'Skipped log line with {len(cells)} columns: {text[:60]!r}')
            continue
        try:
            values = [float(c) for c in cells[1:]]
            clock.append(datetime.strptime(cells[0].strip(), '%H:%M:%S').time())
        except ValueError:
            logger.warning(f'Skipped unreadable log line: {text[:60]!r}')
            continue
        rows.append(values)

    columns = {}
    if rows:
        data = np.array(rows)
        for i, title in enumerate(header[1:]):
            columns[title] = data[:, i]

    # Seconds since the first line; the log only has clock times, so a run past
    # midnight continues on the next day.
    seconds, times = [], []
    if clock:
        day = (start or datetime(1970, 1, 1)).date()
        previous = None
        for t in clock:
            moment = datetime.combine(day, t)
            if previous is not None and moment < previous:
                day += timedelta(days=1)
                moment += timedelta(days=1)
            times.append(moment)
            previous = moment
        seconds = [(t - times[0]).total_seconds() for t in times]
    return {
        'columns': columns,
        'seconds': seconds,
        'first': times[0] if times else None,
        'last': times[-1] if times else None,
        'points': points,
    }


READERS = {'1': read_v1}


def plot_log(seconds, columns) -> go.Figure:
    t = np.asarray(seconds) / 60
    current = columns['BeamCurrent']
    chamber = columns['ChamberPressure']
    keep = downsample(t, current, chamber)
    fig = make_subplots(specs=[[{'secondary_y': True}]])
    fig.add_trace(
        go.Scatter(x=t[keep], y=current[keep], mode='lines', name='Beam current'),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=t[keep], y=chamber[keep], mode='lines', name='Chamber pressure'),
        secondary_y=True,
    )
    fig.update_layout(
        showlegend=True,
        xaxis=dict(title='Time (min)'),
        yaxis=dict(title='Beam current (A)', type='log', exponentformat='e'),
        yaxis2=dict(
            title='Chamber pressure (mbar)',
            type='log',
            showgrid=False,
            overlaying='y',
            side='right',
            exponentformat='e',
        ),
        legend=dict(orientation='h', yanchor='bottom', y=1.01, xanchor='right', x=1),
    )
    return fig


def plot_points(points) -> go.Figure:
    doses = np.array([p['dose_bombarded'] for p in points])
    shown = np.log10(np.where(doses > 0, doses, np.nan))
    fig = go.Figure(
        go.Scatter(
            x=[p['x'] for p in points],
            y=[p['y'] for p in points],
            mode='markers+text',
            text=[str(p['number']) for p in points],
            textposition='top center',
            customdata=[
                [p['name'], p['dose_bombarded'], p['dose_wanted']] for p in points
            ],
            hovertemplate=(
                '%{customdata[0]}<br>x %{x} cm, y %{y} cm<br>'
                'dose %{customdata[1]:.3g} /cm² (wanted %{customdata[2]:.3g})'
                '<extra></extra>'
            ),
            marker=dict(
                size=14,
                color=shown,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title='log10 dose (/cm²)'),
                line=dict(width=1, color='black'),
            ),
        )
    )
    fig.update_layout(
        xaxis=dict(title='x (cm)'),
        yaxis=dict(title='y (cm)', scaleanchor='x'),
    )
    return fig


def guess_chip(mainfile: str, logger) -> Optional[str]:
    """The chip of the L-MOKE files in the folder of the log, if they name one."""
    folder = os.path.dirname(mainfile) or '.'
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    chips = sorted(
        {normalize_sample_id(m.group(1)) for m in map(LMOKE_CHIP_RE.match, names) if m}
    )
    if len(chips) == 1:
        return chips[0]
    if chips:
        logger.warning(
            f'L-MOKE files of {len(chips)} chips ({", ".join(chips)}) next to the ISA '
            'log; no chip linked. Choose the chip under samples.'
        )
    else:
        logger.warning(
            'The ISA log names no chip and there are no L-MOKE files next to it; '
            'choose the chip under samples.'
        )
    return None


def summarise(entry, columns, points):
    def median(title):
        return float(np.median(columns[title])) if title in columns else None

    if 'BeamCurrent' in columns:
        entry.max_beam_current = float(np.max(columns['BeamCurrent']))
    if 'ChamberPressure' in columns:
        entry.mean_chamber_pressure = float(np.mean(columns['ChamberPressure']))
    entry.source_setpoint = median('SourceSetpoint')
    entry.lens_setpoint = median('LensSetpoint')
    entry.magnet_setpoint = median('MagnetSetpoint')
    entry.number_of_points = len(points)
    done = [p for p in points if p['bombarded']]
    entry.number_bombarded = len(done)
    doses = [p['dose_bombarded'] for p in done if p['dose_bombarded'] > 0]
    if doses:
        entry.min_dose = min(doses)
        entry.max_dose = max(doses)


class IonBombardmentParser(MatchingParser):
    def parse(self, mainfile: str, archive: EntryArchive, logger):
        logger.info(
            f'IonBombardmentParser called on {mainfile}',
            configuration=configuration.parameter if configuration else None,
        )
        uid = archive.metadata.upload_id
        entry = AGE_IonBombardment()
        entry_file_name = f'{os.path.basename(mainfile)}.archive.yaml'
        eid = get_entry_id(uid, entry_file_name)
        entry.data_file = os.path.basename(mainfile)
        entry.instrument = 'ISA'

        with open(mainfile, encoding='latin1') as f:
            lines = f.read().splitlines()

        start = start_date(mainfile)
        version = detect_format_version(lines)
        entry.log_format_version = version
        reader = READERS.get(version)
        if reader is None:
            logger.error(
                f'Unknown ISA log format (version {version!r}); only the raw file and '
                'its date are stored. Add a reader for this version to the parser.'
            )
            parsed = {
                'columns': {},
                'seconds': [],
                'first': None,
                'last': None,
                'points': [],
            }
        else:
            parsed = reader(lines, start, logger)

        first = parsed['first'] or start
        if first is not None:
            entry.datetime = lab_time_to_utc(first)
            entry.name = f'IB_{first:%Y-%m-%d %H:%M:%S}'
        else:
            entry.name = f'IB_{os.path.basename(mainfile)}'
        if parsed['last'] is not None:
            entry.end_time = lab_time_to_utc(parsed['last'])

        columns = parsed['columns']
        if parsed['seconds']:
            entry.time = parsed['seconds']
        for title, quantity in V1_COLUMNS.items():
            if quantity and title in columns:
                setattr(entry, quantity, columns[title].tolist())

        points = parsed['points']
        entry.points = [AGE_IonBombardmentPoint(**p) for p in points]
        summarise(entry, columns, points)

        figures = []
        if points:
            figures.append(
                PlotlyFigure(
                    label='Bombarded positions',
                    figure=plot_points(points).to_plotly_json(),
                )
            )
        if parsed['seconds'] and {'BeamCurrent', 'ChamberPressure'} <= set(columns):
            figures.append(
                PlotlyFigure(
                    label='Beam current and pressure',
                    figure=plot_log(parsed['seconds'], columns).to_plotly_json(),
                )
            )
        entry.figures = figures

        # Chips live in the AGE Samples upload: link them, never create them.
        lab_id = guess_chip(mainfile, logger)
        if lab_id:
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
            file_type='ion bombardment log',
            processed_archive=get_hash_ref(uid, entry_file_name),
            **file_fingerprint(mainfile),
        )
        entry.raw_file = get_hash_ref(uid, rel_mainfile)
        if not create_archive(entry, archive, entry_file_name):
            # A chip chosen in the GUI wins over the guess (samples are editable).
            new_entry = update_entry(entry, eid, archive, logger)
            if new_entry is not None:
                create_archive(new_entry, archive, entry_file_name, overwrite=True)
