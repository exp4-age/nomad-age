from nomad.config import config
from nomad.datamodel import EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum

# from nomad.datamodel.metainfo.basesections.v2 import System
from nomad.datamodel.metainfo.basesections import CompositeSystem
from nomad.metainfo import MEnum, Quantity, SchemaPackage, Section

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:age_schema_entry_point'
)

m_package = SchemaPackage(name='age_schema')


class AGE_Sample(CompositeSystem, EntryData):
    m_def = Section(label='AGE Sample', description='AGE sample data')

    state = Quantity(
        type=MEnum(['as made', 'after FC', 'after IB']),
        description='Sample state',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )


m_package.__init_metainfo__()


class AGE_Sample_Reference(Section):
    m_def = Section(
        label='AGE Sample Reference', description='AGE sample reference data'
    )

    reference = Quantity(
        type=AGE_Sample,
        description='Reference to the AGE sample',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity,
            label='Age Sample Reference',
        ),
    )
