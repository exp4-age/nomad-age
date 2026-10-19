import os

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.basesections import (
    Analysis,
    Measurement,
    SectionReference,
)
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.metainfo import (
    JSON,
    MEnum,
    Quantity,
    SchemaPackage,
    Section,
    SubSection,
)

from nomad_age.schema_packages.age_schema import (
    AGE_CoatedSample,
    AGE_Particles,
    AGE_Sample,
    resolved,
)
from nomad_age.utils.utils import get_hash_ref

m_package = SchemaPackage(name='particle_tracking_schema')


class AGE_ParticleMicroscopy(ArchiveSection):
    """Microscope settings that the camera attributes do not contain.

    Particles and the objective are entries of their own (AGE_Particles,
    AGE_Objective) that measurements link under samples and instruments.
    """

    illumination = Quantity(
        type=MEnum(['brightfield', 'darkfield']),
        description=(
            'Illumination mode of the microscope. Guessed from the background '
            'brightness of the first video frame or sweep image; edit if wrong.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    pixel_size = Quantity(
        type=float,
        unit='µm',
        description='Edge length of one camera pixel in the sample plane.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
        a_display={'unit': 'µm'},
    )


class AGE_SampleName(ArchiveSection):
    """A sample of a measurement, by name."""

    name = Quantity(
        type=str,
        description='Name of the linked entry, or the lab_id of the sample.',
    )


class AGE_Measurement(Measurement):
    """A measurement whose samples are also listed by kind.

    A sample reference does not tell the search index what kind of entry it
    links, so particles and chips are listed apart for the search apps to filter
    by, and the spacer thickness of a coated chip is taken over. Particles and
    chips are sub-sections, as NOMAD 1.4.3 makes search quantities of scalar
    quantities only.
    """

    particles = SubSection(
        section_def=AGE_SampleName,
        repeats=True,
        description=(
            'The particle batches (Particles entries) among the samples. Filled '
            'from samples during processing; edit samples instead.'
        ),
    )

    chips = SubSection(
        section_def=AGE_SampleName,
        repeats=True,
        description=(
            'The chips among the samples: AGE Sample entries and the chips of '
            'Coated chip entries. Filled from samples during processing; edit '
            'samples instead.'
        ),
    )

    spacer_thickness = Quantity(
        type=float,
        unit='nm',
        description=(
            'Spacer layer thickness of the coated chip among the samples (the first '
            'one, if several). Filled from samples during processing; edit samples '
            'or the Coated chip entry instead.'
        ),
        a_display={'unit': 'nm'},
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.list_samples_by_kind(logger)

    def list_samples_by_kind(self, logger) -> None:
        """Fill particles, chips and spacer_thickness from the entries that
        samples reference.

        NOMAD normalizes sub-sections before their parent, so the samples have
        found the reference of their lab_id by now. Samples whose entry cannot be
        loaded are left out with a warning.
        """
        particles, chips, thicknesses = [], [], []
        for sample in self.samples:
            sample_id = sample.lab_id or sample.name
            try:
                target = resolved(sample.reference)  # loads the linked entry
            except Exception as e:
                logger.warning(
                    f'Sample {sample_id} not listed: entry not loaded: {e!r}'
                )
                continue
            if target is None:
                logger.warning(f'Sample {sample_id} not listed: it links no entry')
                continue
            if isinstance(target, AGE_Particles):
                particles.append(target.name or sample.lab_id)
            elif isinstance(target, AGE_Sample):
                chips.append(target.name or sample.lab_id)
            elif isinstance(target, AGE_CoatedSample):
                chips.append(coated_chip_name(target, sample_id, logger))
                thickness = target.spacer_thickness
                if thickness is not None:
                    thicknesses.append((sample_id, thickness.to('nm').magnitude))
        self.particles = [AGE_SampleName(name=n) for n in unique(particles)]
        self.chips = [AGE_SampleName(name=n) for n in unique(chips)]
        self.spacer_thickness = thicknesses[0][1] if thicknesses else None
        if len({thickness for _, thickness in thicknesses}) > 1:
            listed = ', '.join(f'{i}: {t:g} nm' for i, t in thicknesses)
            logger.warning(
                f'Samples have different spacer thicknesses ({listed}); '
                f'spacer_thickness is the one of {thicknesses[0][0]}'
            )


def coated_chip_name(coated_sample, sample_id, logger) -> str:
    """Name of the chip of a coated chip; its lab_id if the chip cannot be
    loaded."""
    try:
        chip = resolved(coated_sample.chip)
    except Exception as e:
        chip = None
        problem = f'entry not loaded: {e!r}'
    else:
        problem = 'it links no chip'
    if chip is None:
        logger.warning(
            f'Chip of sample {sample_id} not listed by its name: {problem}; '
            'listed by the lab_id of the coated chip'
        )
        return coated_sample.lab_id or sample_id
    return chip.name or chip.lab_id


def unique(names) -> list:
    """The names without empty and repeated ones, in order."""
    return [name for name in dict.fromkeys(names) if name]


# Normalizer output of AGE_Measurement, which the entry files do not store.
FROM_SAMPLES = tuple(
    name
    for name in AGE_Measurement.m_def.all_properties
    if name not in Measurement.m_def.all_properties
)


class AGE_ParticleTransport(AGE_ParticleMicroscopy, PlotSection, AGE_Measurement):
    """A particle transport experiment: its camera video and the tracks made from
    it share these quantities, above all the recording id."""

    lab_id = Quantity(
        type=str,
        description=(
            'Random id (attribute recording_id) that the acquisition software gives '
            'each recording; the video and the tracks made from it carry the same '
            'id. Empty for older recordings.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity, label='Recording ID'
        ),
    )

    video_file = Quantity(
        type=str,
        description='Raw camera video (HDF5) of the recording.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity,
            label='Video File',
        ),
    )

    frame_rate = Quantity(
        type=float,
        unit='Hz',
        description='Camera frame rate (attribute fps).',
        a_display={'unit': 'Hz'},
    )

    exposure_time = Quantity(
        type=float,
        unit='µs',
        description='Camera exposure time (attribute ExposureTime).',
        a_display={'unit': 'µs'},
    )

    camera_model = Quantity(
        type=str,
        description='Camera model (attribute DeviceModelName).',
    )

    n_frames = Quantity(
        type=int,
        description=(
            'Video frames; for tracks, the frames they cover (highest frame index + 1).'
        ),
    )

    camera_settings = Quantity(
        type=JSON,
        description='All HDF5 root attributes written by the acquisition software.',
    )


class AGE_ParticleTransportVideo(AGE_ParticleTransport, EntryData):
    m_def = Section(
        label='Particle Transport Video',
        description=(
            'Camera video of a particle transport experiment, as saved by '
            'harvesters_pg (HDF5 with a frames dataset). Particles and objective '
            'come from its attributes particles and objective or are added here; '
            'the tracks entries of the recording take over its samples and '
            'instruments.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                editable=dict(exclude=['lab_id', 'video_file', *FROM_SAMPLES]),
            )
        ),
    )

    frame_width = Quantity(
        type=int,
        description='Width of a video frame in pixels.',
    )

    frame_height = Quantity(
        type=int,
        description='Height of a video frame in pixels.',
    )

    duration = Quantity(
        type=float,
        unit='s',
        description='Recorded time: video frames divided by the frame rate.',
        a_display={'unit': 's'},
    )

    def normalize(self, archive, logger):
        self.method = 'Particle Transport Video'
        super().normalize(archive, logger)
        # The parser module imports this one.
        from nomad_age.parsers.particle_tracking_parser import share_with_tracks

        try:
            share_with_tracks(self, archive, logger)
        except Exception as e:
            logger.warning(f'Tracks entries not updated from this video: {e!r}')


class AGE_ParticleTracking(AGE_ParticleTransport, EntryData):
    m_def = Section(
        label='Particle Tracking',
        description=(
            'Particle trajectories tracked with trackpy in a microscope video, '
            'unfiltered; the filter of an upload is documented in its Trajectory '
            'filtering entry. If the video of the recording has an entry in the '
            'same folder, samples (chips, particles) and instruments (objective) '
            'come from it and are edited there.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                editable=dict(
                    exclude=['lab_id', 'tracks_file', 'video_file', *FROM_SAMPLES]
                ),
            )
        ),
    )

    video = Quantity(
        type=AGE_ParticleTransportVideo,
        description='Entry of the video that the trajectories were tracked in.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Video'
        ),
    )

    tracks_file = Quantity(
        type=str,
        description=(
            'trackpy trajectory table of the recording: the unfiltered *_trajs.h5, '
            'or *_filtered_trajs.h5 for recordings uploaded without it.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity,
            label='Tracks File',
        ),
    )

    n_particles = Quantity(
        type=int,
        description='Distinct particles in the tracks file.',
    )

    n_localizations = Quantity(
        type=int,
        description='Localizations (table rows) in the tracks file.',
    )

    def normalize(self, archive, logger):
        self.method = 'Particle Tracking'
        super().normalize(archive, logger)


class AGE_TrajectoryFiltering(Analysis, EntryData):
    m_def = Section(
        label='Trajectory filtering',
        description=(
            'The filter that the trajectories of an upload are analysed with; the '
            'filtered trajectories are not stored, as the filter reproduces them '
            'from the unfiltered ones. A particle is kept if its trajectory has at '
            'least min_frames points and moves farther than min_net_displacement '
            'between its first and last point. Without inputs, all tracks entries '
            '(*_trajs.h5) of the upload are its inputs.'
        ),
    )

    min_frames = Quantity(
        type=int,
        description=(
            'Trajectories with fewer frames are dropped: '
            'trackpy.filter_stubs(trajs, min_frames) keeps those with at least '
            'min_frames points.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity, label='Minimum frames'
        ),
    )

    min_net_displacement = Quantity(
        type=float,
        description=(
            'In pixels. Particles are kept if the net displacement between the first '
            'and the last point of their trajectory, on displacement_axes, is '
            'strictly greater.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity,
            label='Minimum net displacement (px)',
        ),
    )

    displacement_axes = Quantity(
        type=MEnum('x', 'y', 'z'),
        shape=['*'],
        description=(
            'Axes of the net displacement: |Δx| for [x], the Euclidean distance over '
            'the listed axes otherwise.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.EnumEditQuantity, label='Displacement axes'
        ),
    )

    software = Quantity(
        type=str,
        description='Software that filters, with version, e.g. trackpy 0.7.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    script_file = Quantity(
        type=str,
        description='Filter script, a file of the upload.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity, label='Script file'
        ),
    )

    def normalize(self, archive, logger):
        self.method = 'Trajectory filtering'
        if not self.inputs:
            self.link_tracks_entries(archive, logger)
        super().normalize(archive, logger)

    def link_tracks_entries(self, archive, logger) -> None:
        """Make all tracks entries of the upload the inputs. The raw files are
        listed, not searched: during processing the index lags behind."""
        # The parser module imports this one.
        from nomad_age.parsers.particle_tracking_parser import tracks_entry_files

        upload_id = archive.metadata.upload_id if archive.metadata else None
        try:
            entry_files = tracks_entry_files(archive.m_context)
        except Exception as e:
            logger.warning(f'Tracks entries of the upload not listed: {e!r}')
            return
        if upload_id is None or entry_files is None:
            logger.warning('Tracks entries not linked: upload or its files unknown')
            return
        for entry_file in entry_files:
            name = os.path.basename(entry_file)[: -len('.archive.yaml')]
            self.inputs.append(
                SectionReference(
                    name=name, reference=get_hash_ref(upload_id, entry_file)
                )
            )


class AGE_FocusSweep(AGE_ParticleMicroscopy, PlotSection, AGE_Measurement, EntryData):
    m_def = Section(
        label='Focus Sweep',
        description=(
            'Microscope z sweep: one image and one Tenengrad sharpness value per '
            'stage position.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['lab_id']),
                editable=dict(exclude=['data_file', *FROM_SAMPLES]),
            )
        ),
    )

    data_file = Quantity(
        type=str,
        description='HDF5 file of the focus sweep.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity,
            label='Focus Sweep File',
        ),
    )

    n_images = Quantity(
        type=int,
        description='Images in the sweep.',
    )

    z_position = Quantity(
        type=float,
        shape=['*'],
        unit='µm',
        description='Stage z position of each image (dataset poss).',
        a_display={'unit': 'µm'},
    )

    tenengrad = Quantity(
        type=float,
        shape=['*'],
        description='Tenengrad sharpness of each image (dataset tgs).',
    )

    max_focus_position = Quantity(
        type=float,
        unit='µm',
        description='z position of best focus (attribute maxfocus).',
        a_display={'unit': 'µm'},
    )

    max_slope_position = Quantity(
        type=float,
        unit='µm',
        description='z position of the steepest sharpness slope (attribute maxslope).',
        a_display={'unit': 'µm'},
    )

    last_position = Quantity(
        type=float,
        unit='µm',
        description='z position stored as attribute last_position.',
        a_display={'unit': 'µm'},
    )

    def normalize(self, archive, logger):
        self.method = 'Focus Sweep'
        super().normalize(archive, logger)


m_package.__init_metainfo__()
