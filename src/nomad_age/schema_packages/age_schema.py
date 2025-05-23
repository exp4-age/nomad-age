from nomad.config import config
from nomad.datamodel import EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum

# from nomad.datamodel.metainfo.basesections.v2 import System
from nomad.datamodel.metainfo.basesections import (
    Activity,
    CompositeSystem,
    EntityReference,
)
from nomad.metainfo import MEnum, Quantity, SchemaPackage, Section

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:age_schema_entry_point'
)

m_package = SchemaPackage(name='age_schema')


class AGE_RawFile(EntryData):
    m_def = Section(label='AGE Raw File (Logfile)', description='AGE raw file data.')
    processed_archive = Quantity(
        type=Activity,
    )


class AGE_RawFile_Reference(EntryData):
    m_def = Section(
        label='AGE Raw File Reference', description='AGE raw file reference.'
    )
    reference = Quantity(
        type=AGE_RawFile,
        description='Reference to the AGE raw file',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity,
            label='AGE Raw File Reference',
        ),
    )


class AGE_Sample(CompositeSystem, EntryData):
    m_def = Section(label='AGE Sample', description='AGE sample data')

    state = Quantity(
        type=MEnum(['as made', 'after FC', 'after IB']),
        description='Sample state',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)


class AGE_Sample_Reference(EntityReference):
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


m_package.__init_metainfo__()
