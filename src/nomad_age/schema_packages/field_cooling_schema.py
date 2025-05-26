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

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:field_cooling_schema_entry_point'
)

m_package = SchemaPackage(name='field_cooling_schema')


class AGE_FieldCooling(PlotSection, Process, EntryData):
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
        description='Cooling rate',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': '°C / minute'},
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
