import re
from datetime import datetime

import numpy as np
import plotly.graph_objects as go
from nomad.config import config
from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.plot import PlotlyFigure
from nomad.parsing import MatchingParser
from plotly.subplots import make_subplots

from nomad_age.schema_packages.age_schema import Sample

from ..schema_packages.field_cooling_schema import FieldCoolingEntry

configuration = config.get_plugin_entry_point(
    'nomad_age.parsers:field_cooling_parser_entry_point'
)


def parse_date(date_str: str) -> datetime:
    # Replace any sequence of spaces or tabs with a single space
    cleaned = re.sub(r'[ \t]+', ' ', date_str.strip())
    return datetime.strptime(cleaned, '%Y.%m.%d %H:%M:%S')


def plot_field_cooling_data(
    time, measured_temperature, target_temperature, pirani_pressure, penning_pressure
) -> list[PlotlyFigure]:
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
            y=pirani_pressure,
            mode='lines',
            name='Pirani Pressure',
        ),
        secondary_y=True,
    )

    # Layout with two y-axes
    fig.update_layout(
        # title='Field Cooling: Temperature and Pressure over Time',
        showlegend=True,
        xaxis=dict(title='Time (s)'),
        yaxis=dict(title='Temperature (°C)', side='left'),
        yaxis2=dict(
            title='Pressure (mbar)',
            showgrid=False,
            side='right',
            overlaying='y',
            zeroline=False,
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
    def parse(self, mainfile: str, archive: 'EntryArchive', logger):
        logger.info(
            f'FieldCoolingParser called on {mainfile}',
            configuration=configuration.parameter,
        )
        entry = FieldCoolingEntry()
        archive.data = entry
        entry.name = f'FC_{mainfile.split("/")[-1].split(".")[0]}'

        with open(mainfile, encoding='latin1') as f:
            content = f.read()

        # Parse metadata
        for line in content.split('\n'):
            if 'Probenname:' in line:
                # Can repeat for multiple samples
                sample_names = re.findall(r'\d{4}_\d{4}_?\d?', line.split(':')[1])
                entry.samples = [
                    Sample(name=name, state='after FC', comment='')
                    for name in sample_names
                ]
            elif 'Datum:' in line:
                entry.experiment_date = parse_date(line.split(':', 1)[1].strip())
            elif 'T(Blocking)' in line:
                entry.blocking_temperature = float(line.split(':')[1])
            elif 'Plateuzeit' in line:
                entry.plateau_duration = float(line.split(':')[1].replace(',', '.'))
            elif 'hlrate [' in line:  # circumventing issues with the umlaut
                entry.cooling_rate = float(line.split(':')[1].replace(',', '.'))

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
            entry.measured_temperature = data[:, 1].tolist()
            entry.target_temperature = data[:, 2].tolist()
            entry.pirani_pressure = data[:, 3].tolist()
            entry.penning_pressure = data[:, 4].tolist()

            fig = plot_field_cooling_data(
                data[:, 0].tolist(),
                data[:, 1].tolist(),
                data[:, 2].tolist(),
                data[:, 3].tolist(),
                data[:, 4].tolist(),
            )
            entry.figures = [
                PlotlyFigure(label='Field Cooling Plot', figure=fig.to_plotly_json())
            ]
