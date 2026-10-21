from nomad.config import config
from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.basesections import Process

# from nomad.datamodel.metainfo.basesections.v2 import Process
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.datamodel.metainfo.workflow import Link
from nomad.metainfo import Quantity, SchemaPackage, Section

from nomad_age.schema_packages.age_schema import AGE_FromRawFile

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:field_cooling_schema_entry_point'
)

m_package = SchemaPackage(name='field_cooling_schema')


class AGE_FieldCooling(PlotSection, AGE_FromRawFile, Process, EntryData):
    m_def = Section(
        label='Field Cooling',
        description='A Field Cooling process.',
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['lab_id']),
                editable=dict(exclude=['data_file']),
            )
        ),
    )

    blocking_temperature = Quantity(
        type=float,
        unit='°C',
        description='Blocking temperature',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': '°C'},
    )

    plateau_duration = Quantity(
        type=float,
        unit='minute',
        description='Plateau duration',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 'minute'},
    )

    cooling_rate = Quantity(
        type=float,
        unit='°C / minute',
        description=(
            'Cooling rate set in the log; 0 means natural cooling (heater off, '
            'no added cooling).'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': '°C / minute'},
    )

    cooling_mode = Quantity(
        type=str,
        description=(
            "'natural' if the set cooling rate is 0 (heater off, no added "
            "cooling), else 'controlled'."
        ),
    )

    field_source = Quantity(
        type=str,
        default='permanent magnet',
        description='What applies the magnetic field during cooling.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity, label='Field source'
        ),
    )

    field_direction = Quantity(
        type=str,
        description=(
            'Direction of the field relative to the chip, e.g. "in-plane, along '
            'the conductor lines" or "out of plane".'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity, label='Field direction'
        ),
    )

    field_strength = Quantity(
        type=float,
        unit='mT',
        description='Magnetic field at the sample, if known (not measured so far).',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity,
            label='Field strength',
            defaultDisplayUnit='mT',
        ),
    )

    max_temperature = Quantity(
        type=float,
        unit='°C',
        description='Highest measured temperature (from the data).',
    )

    measured_plateau_duration = Quantity(
        type=float,
        unit='minute',
        description=(
            'Time the measured temperature was within ±5 K of the blocking '
            'temperature (from the data).'
        ),
    )

    measured_cooling_rate = Quantity(
        type=float,
        unit='°C / minute',
        description=(
            'Mean cooling rate from the end of the plateau (last point within '
            '±5 K of the blocking temperature) to the end of the log (from the '
            'data). Natural cooling is not linear: fast at first, slow at the end.'
        ),
    )

    min_penning_pressure = Quantity(
        type=float,
        unit='mbar',
        description='Lowest Penning pressure (from the data).',
    )

    time = Quantity(
        type=float,
        shape=['*'],
        unit='s',
        description='Time series',
    )

    measured_temperature = Quantity(
        type=float,
        shape=['*'],
        unit='°C',
        description='Measured temperature',
    )

    target_temperature = Quantity(
        type=float,
        shape=['*'],
        unit='°C',
        description='Target temperature',
        a_display={'visible': False},
    )

    pirani_pressure = Quantity(
        type=float,
        shape=['*'],
        unit='mbar',
        description='Pirani pressure',
    )

    penning_pressure = Quantity(
        type=float,
        shape=['*'],
        unit='mbar',
        description='Penning pressure',
    )

    data_file = Quantity(
        type=str,
        description='Name of the log file of the process.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity,
            label='Field Cooling Log File',
        ),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.method = 'Field Cooling'
        archive.workflow2.inputs = [
            Link(name=sample.name, section=sample.reference) for sample in self.samples
        ]


m_package.__init_metainfo__()
