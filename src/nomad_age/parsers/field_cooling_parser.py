import os
import re
import sys
from datetime import datetime, timedelta

import numpy as np
import plotly.graph_objects as go
from nomad.config import config
from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.plot import PlotlyFigure
from nomad.parsing import MatchingParser
from plotly.subplots import make_subplots

from nomad_age.schema_packages.age_schema import (
    AGE_RawFile,
    AGE_Sample,
    AGE_Sample_Reference,
)
from nomad_age.schema_packages.field_cooling_schema import AGE_FieldCooling
from nomad_age.utils.utils import (
    create_archive,
    find_existing_AGE_sample,
    get_entry_id,
    get_hash_ref,
)

configuration = config.get_plugin_entry_point(
    'nomad_age.parsers:field_cooling_parser_entry_point'
)


def update_entry(entry, eid, archive, logger):
    """Update the entries with the new archive."""
    from nomad import files
    from nomad.search import search

    query = {
        'entry_id': eid,
    }
    search_result = search(
        owner='all', query=query, user_id=archive.metadata.main_author.user_id
    )
    new_entry_dict = entry.m_to_dict()
    res = search_result.data[0]
    try:
        # Open Archives
        with files.UploadFiles.get(upload_id=res['upload_id']).read_archive(
            entry_id=res['entry_id']
        ) as ar:
            entry_id = res['entry_id']
            entry_data = ar[entry_id]['data']
            entry_data.pop('m_def', None)
            new_entry_dict.update(entry_data)
    except Exception as e:
        logger.error('Error in processing data: ', e)
    new_entry = getattr(sys.modules[__name__], type(entry).__name__).m_from_dict(
        new_entry_dict
    )
    return new_entry


def parse_date(date_str: str) -> datetime:
    # Replace any sequence of spaces or tabs with a single space
    cleaned = re.sub(r'[ \t]+', ' ', date_str.strip())
    return datetime.strptime(cleaned, '%Y.%m.%d %H:%M:%S')


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

    # Layout with two y-axes
    fig.update_layout(
        # title='Field Cooling: Temperature and Pressure over Time',
        showlegend=True,
        xaxis=dict(title='Time (s)', fixedrange=False),
        yaxis=dict(title='Temperature (°C)', side='left'),
        yaxis2=dict(
            title='Pressure (mbar)',
            showgrid=False,
            side='right',
            overlaying='y',
            zeroline=False,
            tickformat='.2e',  # Format pressure ticks to 2 decimal places
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

        with open(mainfile, encoding='latin1') as f:
            content = f.read()

        # Parse metadata
        start_time = None
        sample_names = []
        for line in content.split('\n'):
            if 'Probenname:' in line:
                lineend = line.split(':')[1].strip()
                sample_names = re.findall(r'\d{4}_\d{4}_?\d?', lineend)
                if not sample_names:
                    # If there is no sample name found, it's probably only a comment
                    entry.description = line.split(':')[1].strip()
                else:
                    # Ceck if there is more text than just the sample names
                    rest = re.sub(r'\d{4}_\d{4}_?\d?|,', '', lineend)
                    if (
                        len(rest.strip()) > 0
                    ):  # if there is more than just the sample, add it to description
                        entry.description = lineend
            elif 'Datum:' in line:
                start_time = parse_date(line.split(':', 1)[1].strip())
                entry.datetime = start_time
            elif 'T(Blocking)' in line:
                entry.blocking_temperature = float(line.split(':')[1])
            elif 'Plateuzeit' in line:
                entry.plateau_duration = float(line.split(':')[1].replace(',', '.'))
            elif 'hlrate [' in line:  # circumventing issues with the umlaut
                entry.cooling_rate = float(line.split(':')[1].replace(',', '.'))

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
                entry.end_time = start_time + timedelta(seconds=data[:, 0].tolist()[-1])
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

        # Create AGE_Sample_Reference entries for each sample
        # If it doesn't exist, create a new AGE_Sample
        for id in sample_names:
            existing_sample = find_existing_AGE_sample(id)
            if len(existing_sample.data) == 1:  # already exists
                entry.samples.append(
                    AGE_Sample_Reference(
                        reference=get_hash_ref(uid, f'{id}.archive.yaml')
                    )
                )
            elif len(existing_sample.data) == 0:  # does not exist
                SampleArchive = AGE_Sample(name=id, lab_id=id, state='after FC')
                create_archive(
                    SampleArchive,
                    archive,
                    f'{id}.archive.yaml',
                )
                sample = get_hash_ref(uid, f'{id}.archive.yaml')
                entry.samples.append(
                    AGE_Sample_Reference(name=id, lab_id=id, reference=sample)
                )
            else:
                raise ValueError('Two samples have the same ID. Something went wrong')

        raw_file = AGE_RawFile(processed_archive=get_hash_ref(uid, entry_file_name))
        archive.data = raw_file
        new_entry_created = create_archive(entry, archive, entry_file_name)
        if not new_entry_created:
            new_entry = update_entry(entry, eid, archive, logger)
            if new_entry is not None:
                create_archive(new_entry, archive, entry_file_name, overwrite=True)
