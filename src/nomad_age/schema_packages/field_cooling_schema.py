from nomad.config import config
from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.metainfo import Datetime, Quantity, SchemaPackage, Section, SubSection

from nomad_age.schema_packages.age_schema import Sample

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:field_cooling_schema_entry_point'
)

m_package = SchemaPackage(name='field_cooling_schema')


class FieldCoolingEntry(PlotSection, EntryData):
    m_def = Section(
        label='Field Cooling',
        description='A Field Cooling process.',
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                editable=Filter(
                    exclude=[
                        'experiment_date',
                        'blocking_temperature',
                        'plateau_duration',
                        'cooling_rate',
                    ]
                )
            )
        ),
    )

    samples = SubSection(
        sub_section=Sample,
        description='All the samples field cooled in this process.',
        repeats=True,
        a_eln=ELNAnnotation(label='Samples', overview=True),
    )

    experiment_date = Quantity(
        type=Datetime,
        description='Experiment timestamp',
        a_eln=ELNAnnotation(component=ELNComponentEnum.DateTimeEditQuantity),
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


m_package.__init_metainfo__()
