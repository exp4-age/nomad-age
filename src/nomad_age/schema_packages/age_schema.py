from nomad.config import config
from nomad.datamodel import EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.metainfo import MEnum, Quantity, SchemaPackage, Section

configuration = config.get_plugin_entry_point(
    "nomad_age.schema_packages:age_schema_entry_point"
)

m_package = SchemaPackage(name="age_schema")


class Sample(EntryData):
    m_def = Section(
        a_eln=ELNAnnotation(
            properties=SectionProperties(editable=Filter(exclude=["name"]))
        ),
    )
    name = Quantity(
        type=str,
        description="Sample name or identifier",
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    comment = Quantity(
        type=str,
        description="Sample comment / description",
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    state = Quantity(
        type=MEnum(["as made", "after FC", "after IB"]),
        description="Sample state",
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
        default="as made",
    )


m_package.__init_metainfo__()
