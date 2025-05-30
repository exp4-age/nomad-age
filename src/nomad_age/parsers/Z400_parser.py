
import os
import re
import sys
from datetime import datetime, timedelta
import pandas as pd
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
from nomad_age.schema_packages.Z400_schema import AGE_Z400
from nomad_age.utils.utils import (
    create_archive,
    find_existing_AGE_sample,
    get_entry_id,
    get_hash_ref,
)



configuration = config.get_plugin_entry_point(
    'nomad_age.parsers:Z400_parser_entry_point'
)



rate_array_columns = [
    "rate_id",
    "rate [nm/min]",
    "rate_uncertainty [nm/min]",
    "sputter power [W]",
    "gas flow [sscm]",
    "date",
    "setpoint voltage [V]",
    "Material",
    "material_id"
]

substrate_array_columns = [
    "substrate_id",
    "substrate",
]

target_array_columns = [
    "target_id",
    "target",
    "Z400_number?"
]

pretreatment_array_columns = [
    "pretreatment_id",
    "pretreatment",
]

user_array_columns = [
    "AGE_user_id",
    "AGE_user",
    "AGE_user_status"
]

machine_array_columns = [
    "AGE_machine_id",
    "AGE_machine",
    "AGE_machine_category"
]

gas_array_columns = [
    "gas_id",
    "gas",
    "purity"
]

rate_array = pd.read_csv(
    'tests/data/Z400/Ratenarray5_newTurbo.txt',
    sep='\t',
    header=None,
    names=rate_array_columns
)

substrate_array = pd.read_csv(
    'tests/data/Z400/Substratarray.txt',
    sep='\t',
    header=None,
    names=substrate_array_columns
)
target_array = pd.read_csv(
    'tests/data/Z400/Targetarray.txt',
    sep='\t',
    header=None,
    names=target_array_columns
)
pretreatment_array = pd.read_csv(
    'tests/data/Z400/VorbehandlungArray.txt',
    sep='\t',
    header=None,
    names=pretreatment_array_columns
)


with open('tests/data/Z400/db_userarray.txt', encoding='utf-8') as f:
    lines = f.readlines()
AGE_user_data = []
for line in lines:
    match = re.match(r"\((\d+),\s*'([^']+)',\s*(\d+)\)", line.strip().rstrip(',;'))
    if match:
        AGE_user_id, AGE_user, AGE_user_status = match.groups()
        AGE_user_data.append([int(AGE_user_id), AGE_user, int(AGE_user_status)])

AGE_user_array = pd.DataFrame(AGE_user_data, columns=user_array_columns)

with open('tests/data/Z400/db_machinearray.txt', encoding='utf-8') as f:
    lines = f.readlines()
AGE_machine_data = []
for line in lines:
    match = re.match(r"\((\d+),\s*'([^']+)',\s*'([^']+)'\)", line.strip().rstrip(',;'))
    if match:
        AGE_machine_id, AGE_machine, AGE_machine_category = match.groups()
        AGE_machine_data.append([int(AGE_machine_id), AGE_machine, AGE_machine_category])

AGE_machine_array = pd.DataFrame(AGE_machine_data, columns=machine_array_columns)

with open('tests/data/Z400/db_gasarray.txt', encoding='utf-8') as f:
    lines = f.readlines()
AGE_gas_data = []
for line in lines:
    match = re.match(r"\((\d+),\s*'([^']+)',\s*'([^']+)'\)", line.strip().rstrip(',;'))
    if match:
        AGE_gas_id, AGE_gas, AGE_gas_purity = match.groups()
        AGE_gas_data.append([int(AGE_gas_id), AGE_gas, float(AGE_gas_purity)])
AGE_gas_array = pd.DataFrame(AGE_gas_data, columns=gas_array_columns)



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



def parse_date_Z400process(date_str: str) -> datetime:
    # Replace any sequence of spaces or tabs with a single space
    #cleaned = re.sub(r'[ \t]+', ' ', date_str.strip())
    return datetime.strptime(date_str, '%d.%m.%Y %H:%M:%S,%f')


class Z400Parser(MatchingParser):
    def parse(self, mainfile: str, archive: EntryArchive, logger):
        logger.info(
            f'Z400Parser called on {mainfile}',
            configuration=configuration.parameter,
        )
        """
        Create a new entry for the Z400 process data.
        (And create a new entry for the sample)
        Later create a new archive out of this.
        Everyting called archive in here, is the original .DAT logfile!
        """
        uid = archive.metadata.upload_id
        entry = AGE_Z400()
        entry_file_name = f'{os.path.basename(mainfile)}.archive.yaml'
        eid = get_entry_id(uid, entry_file_name)
        entry.data_file = os.path.basename(mainfile)  # the original log file

        entry.instrument = 'Z400'
        entry.location = 'BAHAMAS'

        with open(mainfile, encoding='latin1') as f:
            content = f.read()

        # Parse metadata for the layer and rate processes


        lines = content.split('\n')
        if len(lines) > 3:
            if lines[3].startswith("Layer"):
                for i, line in enumerate(lines):
                    if i == 4:
                        sample_name = re.search(r'\d{4}_\d{4}_?\d?', line).group(0)

                    elif i == 5:
                        date = re.search(r'\d{4}\-\d{2}\-\d{2}', line).group(0)
                        entry.date = date

                    elif i == 6:
                        AGE_user_id = re.search(r'\d+', line)
                        user = AGE_user_array.loc[
                            AGE_user_array['AGE_user_id'] == int(AGE_user_id.group(0)), 'AGE_user'
                        ].values[0]
                        entry.user = str(user)

                    elif i == 7:
                        machineID = re.search(r'\d+', line)
                        machine = AGE_machine_array.loc[
                            AGE_machine_array['AGE_machine_id'] == int(machineID.group(0)), 'AGE_machine'
                        ].values[0]
                        entry.machine = str(machine)

                    elif i == 8:
                        substrateID = re.search(r'\d+', line)
                        substrate = substrate_array.loc[
                            substrate_array['substrate_id'] == int(substrateID.group(0)), 'substrate'
                        ].values[0]
                        entry.substrate = str(substrate)

                    elif i == 9:
                        pretreatmentID = re.search(r'\d+', line)
                        pretreatment = pretreatment_array.loc[
                            pretreatment_array['pretreatment_id'] == int(pretreatmentID.group(0)), 'pretreatment'
                        ].values[0]
                        entry.pretreatment = str(pretreatment)

                    elif i == 10:
                        match = re.search(r'([^"]+)', line)
                        charge_comment = match.group(1) if match else None
                        entry.charge_comment = str(charge_comment)

                    elif i == 11:
                        base_pressure = re.search(r'[\d.]+', line).group(0)
                        entry.base_pressure = float(base_pressure)

                    elif i == 12:
                        sample_quantity = re.search(r'\d+', line).group(0)
                        entry.sample_quantity = int(sample_quantity)

                    elif i == 13:
                        storage_location = re.search(r'([\w\s]+)', line).group(1)
                        entry.storage_location = str(storage_location)

                    elif i == 14:
                        sample_status = re.search(r'([\w\s]+)', line).group(1)
                        entry.sample_status = str(sample_status)

                    elif i == 15:
                        layerID = re.search(r'\d+', line).group(0)
                        entry.layer_id = int(layerID)

                    elif i == 16:
                        sputter_rateID = re.search(r'\d+', line)
                        sputter_rate = rate_array.loc[rate_array['rate_id'] == int(sputter_rateID.group(0)), 'rate [nm/min]'].values[0]
                        entry.sputter_rate = float(sputter_rate)

                        sputter_rate_uncertainty = rate_array.loc[
                            rate_array['rate_id'] == int(sputter_rateID.group(0)), 'rate_uncertainty [nm/min]'
                        ].values[0]
                        entry.sputter_rate_uncertainty = float(sputter_rate_uncertainty)

                        SET_DC_potential = rate_array.loc[
                            rate_array['rate_id'] == int(sputter_rateID.group(0)), 'setpoint voltage [V]'
                        ].values[0]
                        entry.SET_DC_potential = float(SET_DC_potential)

                        SET_gas_flow = rate_array.loc[
                            rate_array['rate_id'] == int(sputter_rateID.group(0)), 'gas flow [sscm]'
                        ].values[0]
                        entry.SET_gas_flow = float(SET_gas_flow)

                        sputter_power = rate_array.loc[
                            rate_array['rate_id'] == int(sputter_rateID.group(0)), 'sputter power [W]'
                        ].values[0]
                        entry.sputter_power = float(sputter_power)

                        material = rate_array.loc[rate_array['rate_id'] == int(sputter_rateID.group(0)), 'Material'].values[0]
                        entry.target_material = str(material)

                    elif i == 17:
                        layer_thickness = re.search(r'[\d.]+', line).group(0)
                        entry.layer_thickness = float(layer_thickness)

                    elif i == 18:
                        magnet = re.search(r'([^"]+)', line).group(0)
                        entry.magnet = str(magnet)

                    elif i == 19:
                        match = re.search(r'([^"]+)', line)
                        layer_comment = match.group(1) if match else None
                        entry.layer_comment = str(layer_comment)

            elif lines[3].startswith("Rate"):
                for i, line in enumerate(lines):
                    if i == 4:
                        sample_name = re.findall(r'\d{4}_\d{4}_?\d?', line).group(0)
                        entry.sample_name = str(sample_name)

                    elif i == 5:
                        date = re.search(r'\d{4}\-\d{2}\-\d{2}', line).group(0)
                        entry.date = str(date)

                    elif i == 6:
                        AGE_user_id = re.search(r'\d+', line)
                        user = AGE_user_array.loc[
                            AGE_user_array['AGE_user_id'] == int(AGE_user_id.group(0)), 'AGE_user'
                        ].values[0]
                        entry.user = str(user)


                    elif i == 7:
                        machineID = re.search(r'\d+', line)
                        machine = AGE_machine_array.loc[
                            AGE_machine_array['AGE_machine_id'] == int(machineID.group(0)), 'AGE_machine'
                        ].values[0]
                        entry.machine = str(machine)

                    elif i == 8:
                        substrateID = re.search(r'\d+', line)
                        substrate = substrate_array.loc[
                            substrate_array['substrate_id'] == int(substrateID.group(0)), 'substrate'
                        ].values[0]
                        entry.substrate = str(substrate)

                    elif i == 9:
                        pretreatmentID = re.search(r'\d+', line)
                        pretreatment = pretreatment_array.loc[
                            pretreatment_array['pretreatment_id'] == int(pretreatmentID.group(0)), 'pretreatment'
                        ].values[0]
                        entry.pretreatment = str(pretreatment)

                    elif i == 10:
                        match = re.search(r'([^"]+)', line)
                        charge_comment = match.group(1) if match else None
                        entry.charge_comment = str(charge_comment)

                    elif i == 11:
                        base_pressure = re.search(r'[\d.]+', line).group(0)
                        entry.base_pressure = float(base_pressure)

                    elif i == 12:
                        targetID = re.search(r'\d+', line)
                        entry.target_material = target_array.loc[
                            target_array['target_id'] == int(targetID.group(0)), 'target'
                        ].values[0]

                    elif i == 13:
                        gas = re.search(r'\d+', line)
                        entry.gas = AGE_gas_array.loc[
                            AGE_gas_array['gas_id'] == int(gas.group(0)), 'gas'
                        ].values[0]

                    elif i == 14:
                        SET_gas_flow = re.search(r'[\d.]+', line).group(0)
                        entry.SET_gas_flow = float(SET_gas_flow)

                    elif i == 15:
                        SET_DC_potential = re.search(r'[\d.]+', line).group(0)
                        entry.SET_DC_potential = float(SET_DC_potential)

                    elif i == 19:
                        magnet = re.search(r'([^"]+)', line).group(0)
                        entry.magnet = str(magnet)



        # Parse time-series data
        data_table_presputter = []
        in_data_section = False
        lines = content.split('\n')
        data_table_presputter = []
        start_idx_presputter = None
        timer_started_value = None

        for idx, line in enumerate(lines):
            if 'Timestamp' in line:
                start_idx_presputter = idx + 1  # one line after
                break

        if start_idx_presputter is not None:
            for line in lines[start_idx_presputter:]:
                if 'Timer gestartet' in line:
                    parts = line.split('\t')
                    if len(parts) > 2 and 'Timer gestartet' in parts[1]:
                        try:
                            timer_started_value = float(parts[2].replace(',', '.'))
                        except ValueError:
                            timer_started_value = None
                    continue  # skip this line for data_table_presputter

                if line.strip() and not line.startswith('#'):
                    values = line.strip().split('\t')
                    try:
                        # Only convert if all but the first column are numeric
                        converted = [values[0]] + [float(v.replace(',', '.')) for v in values[1:] if v.replace(',', '.').replace('.', '', 1).isdigit()]
                        if len(converted) == len(values):
                            data_table_presputter.append(converted)
                    except ValueError:
                        continue

        if data_table_presputter:
            data = np.array(data_table_presputter)
            datetimes = [parse_date_Z400process(s) for s in data[:, 0]]
            minutes_diff_presputter = (datetimes[-1] - datetimes[0]).total_seconds() / 60
            entry.datetime_presputter = datetimes
            entry.duration_presputter = minutes_diff_presputter
            entry.matchbox_temperature_presputter = data[:, 2].tolist()
            entry.pressure_pirani_presputter = data[:, 3].tolist()
            entry.pressure_penning_presputter = data[:, 4].tolist()
            entry.DC_Potential_presputter = data[:, 5].tolist()
            entry.power_forwarded_presputter = data[:, 6].tolist()
            entry.power_reflected_presputter = data[:, 7].tolist()
            entry.phase_presputter = data[:, 8].tolist()
            entry.tune_presputter = data[:, 9].tolist()
            entry.load_presputter = data[:, 10].tolist()




        data_table_process = []
        lines = content.split('\n')
        start_idx_process = None
        timer_ended_found = False

        # Find the line with "Timer gestartet" and start reading data after it
        for idx, line in enumerate(lines):
            if 'Timer gestartet' in line:
                start_idx_process = idx + 1  # one line after
                break

        if start_idx_process is not None:
            for line in lines[start_idx_process:]:
                if 'Timer beendet' in line:
                    timer_ended_found = True
                    break  # stop reading further lines
                if line.strip() and not line.startswith('#'):
                    values = line.strip().split('\t')
                    try:
                        # First value as string, rest as float
                        converted = [values[0]] + [float(v.replace(',', '.')) for v in values[1:]]
                        data_table_process.append(converted)
                    except ValueError:
                        continue
        # Optionally, you can log or store whether timer_ended_found is True/False
        entry.timer_ended_found = timer_ended_found


        if data_table_process:
            data = np.array(data_table_process)
            datetimes = [parse_date_Z400process(s) for s in data[:, 0]]
            entry.datetime_process = datetimes
            minutes_diff_process = (datetimes[-1] - datetimes[0]).total_seconds() / 60
            entry.duration_process = minutes_diff_process
            entry.matchbox_temperature_process = data[:, 2].tolist()
            entry.pressure_pirani_process = data[:, 3].tolist()
            entry.pressure_penning_process = data[:, 4].tolist()
            entry.DC_Potential_process = data[:, 5].tolist()
            entry.power_forwarded_process = data[:, 6].tolist()
            entry.power_reflected_process = data[:, 7].tolist()
            entry.phase_process = data[:, 8].tolist()
            entry.tune_process = data[:, 9].tolist()
            entry.load_process = data[:, 10].tolist()

        # Check if minutes_diff_process matches timer_started_value (if available)

            entry.timer_started_value = timer_started_value
            entry.duration_process_matches_timer = abs(minutes_diff_process - timer_started_value) < 1e-2  # tolerance for float comparison

        # Create a new AGE sample
        id = sample_name
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
