from nomad.config import config
from nomad.datamodel import EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)

# from nomad.datamodel.metainfo.basesections.v2 import System
from nomad.datamodel.metainfo.basesections import (
    Activity,
    CompositeSystem,
    EntityReference,
    Instrument,
)
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, Section

from nomad_age.utils.utils import get_referencing_entries

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
        type=MEnum(['as made', 'after FC', 'after IB', 'other', 'destroyed']),
        description='Sample state',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.EnumEditQuantity, label='Sample State'
        ),
    )

    location = Quantity(
        type=MEnum(['Sample box', 'Sample cabinet', 'Archive', 'External', 'Trash']),
        description='Location of the sample',
        label='Sample Location',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.EnumEditQuantity,
            label='Sample Location',
        ),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        referencing = get_referencing_entries(self)
        if not referencing:
            return
        used_methods = [entry['data']['method'] for entry in referencing]
        if 'Helium Ion Bombardment' in used_methods:
            self.state = 'after IB'
        elif 'Field Cooling' in used_methods:
            self.state = 'after FC'
        else:
            pass  # TODO: Either this or maybe set to "as made"?


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


class AGE_Particles(CompositeSystem, EntryData):
    """Particles of one batch; measurements link it under samples."""

    m_def = Section(
        label='Particles',
        description='A batch of particles, e.g. one charge of M270 beads.',
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['datetime']),
                order=[
                    'name',
                    'lab_id',
                    'particle_type',
                    'batch',
                    'batch_date',
                    'description',
                ],
            )
        ),
    )

    particle_type = Quantity(
        type=str,
        description='Particle type, e.g. M270.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    batch = Quantity(
        type=str,
        description='Batch (Charge) or lot number of the particles.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity, label='Batch (Charge)'
        ),
    )

    batch_date = Quantity(
        type=Datetime,
        description='Date of the batch, e.g. delivery or preparation date.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.DateEditQuantity),
    )


class AGE_Objective(Instrument, EntryData):
    """Microscope objective; measurements link it under instruments."""

    m_def = Section(
        label='Objective',
        description='A microscope objective.',
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['datetime']),
                order=[
                    'name',
                    'lab_id',
                    'magnification',
                    'numerical_aperture',
                    'description',
                ],
            )
        ),
    )

    magnification = Quantity(
        type=float,
        description='Nominal magnification, e.g. 20.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )

    numerical_aperture = Quantity(
        type=float,
        description='Numerical aperture (NA).',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )


m_package.__init_metainfo__()
