from nomad.config import config
from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.basesections import Process

# from nomad.datamodel.metainfo.basesections.v2 import Process
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.datamodel.metainfo.workflow import Link
from nomad.metainfo import Quantity, SchemaPackage, Section

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:Z400_schema_entry_point'
)

m_package = SchemaPackage(name='Z400_schema')


class AGE_Z400(PlotSection, Process, EntryData):
    m_def = Section(
        label='Z400',
        description='A Z400 sputter process',
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['lab_id']),
                editable=dict(exclude=['data_file']),
            )
        ),
    )

    charge_name = Quantity(
        type=str,
        description='name of the charge.',
    )

    date = Quantity(
        type=str,
        description='date of the sputter process.',
    )

    user = Quantity(
        type=str,
        description='user performing the sputter process.'
    )

    machine = Quantity(
        type=str,
        description='machine used for the sputter process.'
    )

    substrate = Quantity(
        type=int,
        description='substrate used in the sputter process.'
    )

    pretreatment = Quantity(
        type=str,
        description='pretreatment applied to the substrate.'
    )

    charge_comment = Quantity(
        type=str,
        description='comments regarding the charge created in the sputter process.'
    )

    base_pressure = Quantity(
        type=float,
        description='base pressure in the chamber before the sputter process.'
    )

    sample_quantity = Quantity(
        type=int,
        description='number of samples processed in this sputter run.'
    )


    storage_location = Quantity(
        type=str,
        description='location where the samples are stored after the sputter process.'
    )

    sample_status = Quantity(
        type=str,
        description='status of the sample after the sputter process.',
    )

    layer_id = Quantity(
        type=int,
        label='Layer',
        description='identifier for the layer in the sputter process.',
    )

    sputter_rate = Quantity(
        type=float,
        description='sputter rate used for the process.'
    )

    layer_thickness = Quantity(
        type=float,
        description='thickness of the layer deposited during the sputter process.'
    )

    magnet = Quantity(
        type = str,
        description="Sputtered with or without permanent magnet"
    )

    layer_comment = Quantity(
        type=str,
        description='comments regarding the layer created in the sputter process.'
    )

    SET_DC_potential = Quantity(
        type=float,
        description='DC potential which should be applied during the sputter process.',
        unit='V',
    )

    SET_gas_flow = Quantity(
        type=float,
        description='gas flow rate which the sputter process should have.',
        unit='sccm',
    )


    sputter_rate_uncertainty = Quantity(
        type=float,
        description='uncertainty of the sputter rate used for the sputter process.',
        unit='nm/min',
    )

    target_material = Quantity(
        type=str,
        description='material of the target used in the sputter process of the layer.'
    )

    sputter_power = Quantity(
        type=str,
        description='sputter power used for the layer.',
        unit='W',
    )

    gas = Quantity(
        type=str,
        description='gas used in the sputter process.',
    )



    matchbox_temperature_process = Quantity(
        type=float,
        shape=['*'],
        unit='°C',
        description='Temperature of the matchbox during the sputter process.',
    )

    pressure_pirani_process = Quantity(
        type=float,
        shape=['*'],
        unit='mbar',
        description='Pirani pressure during the sputter process.',
    )

    pressure_penning_process = Quantity(
        type=float,
        shape=['*'],
        unit='mbar',
        description='Penning pressure during the sputter process.',
    )

    DC_Potential_process = Quantity(
        type=float,
        shape=['*'],
        unit='V',
        description='DC potential applied during the sputter process.',
    )

    power_forwarded_process = Quantity(
        type=float,
        shape=['*'],
        unit='W',
        description='Forwarded power during the sputter process.',
    )

    power_reflected_process = Quantity(
        type=float,
        shape=['*'],
        unit='W',
        description='Reflected power during the sputter process.',
    )

    phase_process = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Phase of the ac signal.',
    )

    magnitude_process = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Magnitude of the ac signal.',
    )

    tune_process = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Tuning of the capacitor.',
    )

    load_process = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Load of the capacitor.',
    )

    matchbox_temperature_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='°C',
        description='Temperature of the matchbox during the sputter process.',
    )

    pressure_pirani_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='mbar',
        description='Pirani pressure during the sputter process.',
    )

    pressure_penning_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='mbar',
        description='Penning pressure during the sputter process.',
    )

    DC_Potential_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='V',
        description='DC potential applied during the sputter process.',
    )

    power_forwarded_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='W',
        description='Forwarded power during the sputter process.',
    )

    power_reflected_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='W',
        description='Reflected power during the sputter process.',
    )

    phase_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Phase of the ac signal.',
    )

    magnitude_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Magnitude of the ac signal.',
    )

    tune_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Tuning of the capacitor.',
    )

    load_presputter = Quantity(
        type=float,
        shape=['*'],
        unit='mV',
        description='Load of the capacitor.',
    )



    datetime_presputter = Quantity(
        type=str,
        shape=['*'],
        description='Date and time of the presputter process.',
    )

    duration_presputter = Quantity(
        type=float,
        description='Duration of the presputter process in minutes.',
        unit='min',
    )

    datetime_process = Quantity(
        type=str,
        shape=['*'],
        description='Date and time of the sputter process.',
    )

    duration_process = Quantity(
        type=float,
        description='Duration of the process in minutes.',
        unit='min',
    )

    timer_ended_found = Quantity(
        type=bool,
        description='Indicates if the timer ended successfully.'
    )

    timer_started_value = Quantity(
        type=float,
        description='Set timer value for the process in minutes.',
        unit='min',
    )

    duration_process_matches_timer = Quantity(
        type=bool,
        description='Indicates if the duration of the process matches the timer value.'
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.method = 'Z400'
        archive.workflow2.inputs = [
            Link(name=sample.name, section=sample.reference) for sample in self.samples
        ]


m_package.__init_metainfo__()

# LAYER
#     Sample name
# - date
# - UserID
# - AnlagenID
# - SubstratID
# - VorbehandlungID
# - Chargen Bemerkung
# - Base pressure
# - Sample Anzahl
# - Aufbewahrungsort
# - Status
# - SchichtID
# - SputerratenID
# - Schichtdicke
# - Magnetfeld
# - Schichten Bemerkung
# - Potential
# - Gasfluss
# - Rate
# - Material
# - ReaktivgasID
# - Reaktivgasfluss

#RATE
# - Sample name
# - date
# - UserID
# - AnlagenID
# - SubstratID
# - VorbehandlungID
# - Chargen Bemerkung
# - Base pressure
# - TargetID
# - GasID
# - Gasfluss
# - Potential
# - ReaktivgasID
# - Reaktivgasfluss
# - Kühlfalle
# - Magnetfeld
