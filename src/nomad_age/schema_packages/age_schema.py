from nomad.metainfo import Section, Quantity, SubSection, SchemaPackage, MSection, MEnum
from nomad.datamodel import EntryData
from nomad.config import config
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum, SectionProperties, Filter
from nomad.datamodel.metainfo.basesections.v2 import System

configuration = config.get_plugin_entry_point(
    "nomad_age.schema_packages:age_schema_entry_point"
)

m_package = SchemaPackage(name="age_schema")


class AGE_Sample(System, EntryData):
    m_def = Section()

    state = Quantity(
        type=MEnum(["as made", "after FC", "after IB"]),
        description="Sample state",
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
        default="as made",
    )

m_package.__init_metainfo__()
