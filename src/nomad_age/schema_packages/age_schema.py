import os
from datetime import datetime
from typing import Optional

from nomad.config import config
from nomad.datamodel.data import ArchiveSection, EntryData
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
    CompositeSystemReference,
    EntityReference,
    Instrument,
    Process,
)
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.datamodel.metainfo.workflow import Link
from nomad.metainfo import (
    Datetime,
    MEnum,
    MProxy,
    Quantity,
    Reference,
    SchemaPackage,
    Section,
    SectionProxy,
    SubSection,
)

from nomad_age.utils import chip_refresh
from nomad_age.utils.utils import (
    LAB_TIMEZONE,
    get_reference,
    get_referencing_entries,
    newest_magnetisation_measurement,
)

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:age_schema_entry_point'
)

m_package = SchemaPackage(name='age_schema')


class AGE_InventoryItem(ArchiveSection):
    """Marks lab equipment and consumables (particle batches, objectives, ...).

    The AGE Inventory app locks to this section: NOMAD indexes the base sections
    of an entry's data, and a locked filter with several types matches only
    entries of all of them (none).
    """


class AGE_RawFile(EntryData):
    """An original data file of an upload, kept for archival. The parser writes its
    data to an editable entry file (processed_archive) and fingerprints the file
    here."""

    m_def = Section(label='AGE Raw File (Logfile)', description='AGE raw file data.')
    name = Quantity(
        type=str,
        description='Name of the file; also the name of the entry.',
    )
    file_name = Quantity(
        type=str,
        description='Path of the file relative to the raw files of the upload.',
    )
    file_type = Quantity(
        type=str,
        description=(
            'Kind of file, e.g. particle transport video, trajectories, focus sweep '
            'or field cooling log.'
        ),
    )
    file_size = Quantity(
        type=int,
        unit='byte',
        description='Size of the file.',
    )
    sha256 = Quantity(
        type=str,
        description='SHA-256 checksum of the file content, hex.',
    )
    modified = Quantity(
        type=Datetime,
        description='Modification time of the file (UTC) when it was parsed.',
    )
    processed_archive = Quantity(
        type=Activity,
    )

    def normalize(self, archive, logger):
        if self.name is None and self.file_name:
            self.name = os.path.basename(self.file_name)
        if self.name:
            archive.metadata.entry_name = self.name
        super().normalize(archive, logger)


class AGE_FromRawFile(ArchiveSection):
    """An entry that a parser writes from an original data file."""

    raw_file = Quantity(
        type=AGE_RawFile,
        description=(
            'Entry of the original data file that this entry is parsed from, with '
            'its size, SHA-256 checksum and modification time. Set by the parser.'
        ),
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


# Label of the chip figure of its newest magnetisation measurement.
MAGNETISATION_FIGURE_LABEL = 'Newest magnetisation measurement'


class AGE_Sample(PlotSection, CompositeSystem, EntryData):
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

    latest_magnetisation_measurement = Quantity(
        type=Reference(SectionProxy('AGE_MagnetisationMeasurement')),
        description=(
            'The newest magnetisation measurement of the chip, whose plot the chip '
            'shows. Set on processing; all measurements are under Referenced by.'
        ),
    )

    latest_magnetisation_time = Quantity(
        type=Datetime,
        description='Time of the newest magnetisation measurement. Set on processing.',
    )

    latest_magnetisation_technique = Quantity(
        type=str,
        description=(
            'Technique of the newest magnetisation measurement, e.g. L-MOKE. Set on '
            'processing.'
        ),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.show_newest_magnetisation(archive, logger)
        referencing = get_referencing_entries(self)
        if not referencing:
            return
        # Coated chips and other samples that reference a chip have no method.
        used_methods = [
            (entry.get('data') or {}).get('method') for entry in referencing
        ]
        if 'Helium Ion Bombardment' in used_methods:
            self.state = 'after IB'
        elif 'Field Cooling' in used_methods:
            self.state = 'after FC'
        else:
            pass  # TODO: Either this or maybe set to "as made"?

    def show_newest_magnetisation(self, archive, logger):
        """Show the plot of the newest magnetisation measurement that references
        the chip (in any upload its main author sees), replacing the plot and
        latest_* values that the chip shows; on errors, keep them."""
        metadata = archive.metadata
        try:
            author = metadata.main_author
            newest = newest_magnetisation_measurement(
                metadata.entry_id, author.user_id if author else None
            )
            figure = None
            if newest is not None:
                measurement = archive.m_context.load_archive(
                    newest['entry_id'], newest['upload_id'], None
                ).data
                figure = measurement.magnetisation_figure()
        except Exception as e:
            logger.warning(f'Could not show the newest magnetisation plot: {e!r}')
            return
        # Users save chips in the ELN with the values of the last processing.
        for index in reversed(range(len(self.figures))):
            if self.figures[index].label == MAGNETISATION_FIGURE_LABEL:
                self.m_remove_sub_section(PlotSection.figures, index)
        if newest is None:
            self.latest_magnetisation_measurement = None
            self.latest_magnetisation_time = None
            self.latest_magnetisation_technique = None
        else:
            self.latest_magnetisation_measurement = (
                f'{get_reference(newest["upload_id"], newest["entry_id"])}#data'
            )
            self.latest_magnetisation_time = newest['measurement_time']
            self.latest_magnetisation_technique = (
                measurement.technique or newest['technique']
            )
            if figure is None:
                logger.warning('The newest magnetisation measurement has no plot.')
            else:
                self.figures.append(
                    PlotlyFigure(label=MAGNETISATION_FIGURE_LABEL, figure=figure)
                )
        try:
            chip_refresh.postpone_while_source_busy(
                metadata.upload_id, metadata.entry_id, logger
            )
        except Exception as e:
            logger.warning(f'Could not postpone the chip plot refresh: {e!r}')


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


class AGE_MagnetisationMeasurement(ArchiveSection):
    """Base of all magnetisation measurements of chips (L-MOKE, V-MOKE, VSM, Kerr
    microscopy). A chip finds them by this section and shows the plot of the
    newest one; every entry type of such a measurement derives from it."""

    samples = SubSection(
        section_def=AGE_Sample_Reference,
        repeats=True,
        description='The measured chips, in the AGE Samples upload.',
    )

    measurement_time = Quantity(
        type=Datetime,
        description='Time of the measurement.',
    )

    technique = Quantity(
        type=str,
        description='Measurement technique, e.g. L-MOKE or V-MOKE.',
    )

    def magnetisation_title(self) -> str:
        """Short title of the plot: technique and lab time of the measurement."""
        parts = [self.technique or 'Magnetisation']
        if self.measurement_time is not None:
            parts.append(f'{local_time(self.measurement_time):%Y-%m-%d %H:%M}')
        return ', '.join(parts)

    def magnetisation_figure(self) -> Optional[dict]:
        """Plotly figure (JSON dict) that chips show of this measurement; None if
        there is nothing to plot. Each measurement type overrides it."""
        return None

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        chip_refresh.request_chip_refreshes(self, archive, logger)


def local_time(time: datetime) -> datetime:
    """`time` in the time zone of the lab."""
    return time.astimezone(LAB_TIMEZONE)


class AGE_Particles(CompositeSystem, EntryData, AGE_InventoryItem):
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


class AGE_Objective(Instrument, EntryData, AGE_InventoryItem):
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


class AGE_CoatedSample(CompositeSystem, EntryData):
    """A chip in one coated state: the chip with one spacer layer on it."""

    m_def = Section(
        label='Coated chip',
        description=(
            'A chip (AGE Sample) with a spacer layer, e.g. PMMA, spin coated on it. '
            'Each layer is an entry of its own: once it is removed and a new one is '
            'coated, the chip gets a new coated chip entry. Recordings link the '
            'coated chip they were measured on under samples. Name its lab_id '
            '<chip>_PMMA<n>, e.g. 2023_0418_PMMA2 for the second PMMA layer of '
            'chip 2023_0418.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['datetime']),
                order=[
                    'name',
                    'lab_id',
                    'chip',
                    'spacer_material',
                    'spacer_thickness',
                    'spacer_thickness_uncertainty',
                    'thickness_method',
                    'n_thickness_points',
                    'date_coated',
                    'date_removed',
                    'description',
                ],
            )
        ),
    )

    chip = Quantity(
        type=AGE_Sample,
        description='The chip that the layer is coated on.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Chip'
        ),
    )

    spacer_material = Quantity(
        type=str,
        default='PMMA',
        description='Material of the spacer layer, e.g. PMMA.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    spacer_thickness = Quantity(
        type=float,
        unit='nm',
        description=(
            'Thickness of the spacer layer: the mean over the points measured, e.g. '
            'by profilometry on a scratch in the layer.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 'nm'},
    )

    spacer_thickness_uncertainty = Quantity(
        type=float,
        unit='nm',
        description=(
            'Standard error of the mean of spacer_thickness over the profilometry '
            'points.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 'nm'},
    )

    thickness_method = Quantity(
        type=MEnum(['profilometry (scratch)', 'other']),
        description=(
            'How spacer_thickness was measured; profilometry (scratch): profile '
            'height of a scratch in the layer at several points.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    n_thickness_points = Quantity(
        type=int,
        description='Points that spacer_thickness is the mean of.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )

    date_coated = Quantity(
        type=Datetime,
        description='Date the layer was spin coated.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.DateEditQuantity),
    )

    date_removed = Quantity(
        type=Datetime,
        description='Date the layer was removed; empty while it is on the chip.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.DateEditQuantity),
    )


def resolved(reference):
    """The section that a reference quantity value links; loads its entry if
    needed. Raises if the entry cannot be loaded."""
    if isinstance(reference, MProxy):
        return reference.m_proxy_resolve()
    return reference


class AGE_SpinCoating(Process, EntryData):
    """Spin coating of a spacer layer on a chip."""

    m_def = Section(
        label='Spin coating',
        description=(
            'Spin coating of a spacer layer, e.g. PMMA, on a chip; its datetime is '
            'the coating date. Its input is the chip, its output the coated chip '
            'entry that describes the layer.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                editable=dict(exclude=['samples']),
                order=[
                    'name',
                    'datetime',
                    'chip',
                    'coated_sample',
                    'resist',
                    'spin_speed',
                    'acceleration',
                    'spin_time',
                    'n_layers',
                    'bake_temperature',
                    'bake_time',
                    'description',
                ],
            )
        ),
    )

    chip = Quantity(
        type=AGE_Sample,
        description='The chip that is coated (input).',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Chip'
        ),
    )

    coated_sample = Quantity(
        type=AGE_CoatedSample,
        description='The coated chip entry of the layer (output).',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Coated chip'
        ),
    )

    resist = Quantity(
        type=str,
        description='Resist, e.g. PMMA 950K A11.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    spin_speed = Quantity(
        type=float,
        unit='1/minute',
        description='Spin speed in revolutions per minute (rpm).',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity, label='Spin speed (rpm)'
        ),
        a_display={'unit': '1/minute'},
    )

    acceleration = Quantity(
        type=float,
        unit='1/minute/second',
        description='Spin acceleration in rpm per second.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity,
            label='Acceleration (rpm/s)',
        ),
        a_display={'unit': '1/minute/second'},
    )

    spin_time = Quantity(
        type=float,
        unit='s',
        description='Time at spin speed.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 's'},
    )

    n_layers = Quantity(
        type=int,
        description='Resist layers coated on top of each other.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity, label='Layers'
        ),
    )

    bake_temperature = Quantity(
        type=float,
        unit='celsius',
        description='Hotplate temperature of the bake after coating.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 'celsius'},
    )

    bake_time = Quantity(
        type=float,
        unit='s',
        description='Duration of the bake after coating.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 's'},
    )

    def normalize(self, archive, logger):
        self.method = 'Spin coating'
        chip = process_sample('Chip', self.chip, logger)
        coated_sample = process_sample('Coated chip', self.coated_sample, logger)
        self.samples = [*chip, *coated_sample]
        super().normalize(archive, logger)
        # Process makes all samples outputs; the chip is the input.
        archive.workflow2.inputs = [
            Link(name=s.name, section=s.reference) for s in chip
        ]
        archive.workflow2.outputs = [
            Link(name=s.name, section=s.reference) for s in coated_sample
        ]


def process_sample(name: str, reference, logger) -> list:
    """The sample entry of a process as CompositeSystemReference, in a list; empty
    without reference."""
    if reference is None:
        return []
    try:
        lab_id = resolved(reference).lab_id
    except Exception as e:
        logger.warning(f'{name} of the spin coating not loaded: {e!r}')
        lab_id = None
    return [CompositeSystemReference(name=name, lab_id=lab_id, reference=reference)]


m_package.__init_metainfo__()
