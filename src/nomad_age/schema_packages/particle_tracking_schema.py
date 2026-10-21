import os
from datetime import date, datetime, time

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.basesections import (
    Analysis,
    CompositeSystemReference,
    InstrumentReference,
    Measurement,
    SectionReference,
)
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.metainfo import (
    JSON,
    MEnum,
    MProxy,
    Quantity,
    SchemaPackage,
    Section,
    SubSection,
)

from nomad_age.schema_packages.age_schema import (
    AGE_CoatedSample,
    AGE_FromRawFile,
    AGE_Objective,
    AGE_Particles,
    AGE_Sample,
    resolved,
)
from nomad_age.utils.utils import (
    LAB_TIMEZONE,
    as_utc,
    find_coated_samples,
    get_hash_ref,
    get_reference,
    parse_reference,
)

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


def links_objective(reference) -> bool:
    """Whether a reference value links an Objective entry; False if the entry
    cannot be loaded."""
    try:
        return isinstance(resolved(reference), AGE_Objective)
    except Exception:
        return False  # name_instruments reports entries that do not load


def linked_entry(reference):
    """(upload id, entry id) of the entry that a reference value links, or the
    linked section if the value names no entry; None if it cannot be loaded."""
    ids = parse_reference(reference)
    if ids is not None or reference is None:
        return ids
    try:
        target = resolved(reference)
    except Exception:
        return None
    metadata = getattr(target.m_root(), 'metadata', None)
    if metadata is not None and metadata.entry_id:
        return (metadata.upload_id, metadata.entry_id)
    return target


def reference_value(reference):
    """A reference value to set on another quantity: the text it was given as
    (e.g. ../uploads/<upload>/archive/<entry>#data), else the linked section."""
    return getattr(reference, 'm_proxy_value', None) or reference


def entry_reference(ids: tuple) -> str:
    """Reference to the data of the entry with (upload id, entry id) `ids`."""
    return f'{get_reference(*ids)}#data'


def replace_links(links: list, replaced: list, kept) -> list:
    """`links` with `kept` in place of the first of the `replaced` ones (at the end
    if none is among them) and without the other `replaced` ones."""
    result = []
    for link in links:
        if link not in replaced:
            result.append(link)
        elif kept not in result:
            result.append(kept)
    if kept not in result:
        result.append(kept)
    return result


class AGE_ObjectiveLink(ArchiveSection):
    """A measurement whose objective is picked on its overview page.

    objective is the user's choice; instruments, which the search apps filter by
    and the tracks entries of a video take over, follow it. AGE_Measurement
    syncs the two on normalize, see link_objective.
    """

    objective = Quantity(
        type=AGE_Objective,
        description=(
            'The microscope objective entry (Inventory) used for this measurement. '
            'Instruments link the same entry: picking another objective here '
            'replaces the objective among the instruments. Filled from the '
            'instruments (e.g. the objective attribute of the file) if empty; a '
            'choice made here stays when the file is processed again.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Objective'
        ),
    )

    def link_objective(self, logger) -> None:
        """Make instruments link exactly the objective of `objective`.

        With objective set, the instruments that link an Objective entry are
        replaced by one that links it (an existing one that links it already is
        kept); other instruments stay. Without objective, it is taken from the
        first instrument that links an Objective entry: one the parser linked
        from the objective attribute of the file, or one of an older entry.
        """
        if isinstance(self.objective, MProxy) and '/' not in str(
            self.objective.m_proxy_value
        ):
            logger.warning(
                f'Objective {self.objective.m_proxy_value!r} is text, not an '
                'Objective entry (as entries stored it before objectives were '
                'entries); dropped'
            )
            self.objective = None
        objectives = [i for i in self.instruments if links_objective(i.reference)]
        if self.objective is None:
            if not objectives:
                return
            self.objective = reference_value(objectives[0].reference)
        try:
            target = resolved(self.objective)
        except Exception as e:
            logger.warning(f'Objective not loaded: {e!r}; instruments left as they are')
            return
        if not isinstance(target, AGE_Objective):
            logger.warning(
                'Objective links no Objective entry; instruments left as they are'
            )
            return
        wanted = linked_entry(self.objective)
        objectives += [
            i
            for i in self.instruments
            if i not in objectives and linked_entry(i.reference) == wanted
        ]
        kept = next(
            (i for i in objectives if linked_entry(i.reference) == wanted), None
        )
        if kept is None:
            # named after the entry by name_instruments, as linked by the parser
            kept = InstrumentReference(
                name=target.lab_id,
                lab_id=target.lab_id,
                reference=reference_value(self.objective),
            )
        instruments = replace_links(self.instruments, objectives, kept)
        if [id(i) for i in instruments] != [id(i) for i in self.instruments]:
            self.instruments = instruments


def lab_day(moment: datetime) -> date:
    """The date of `moment` in the time zone of the lab."""
    return moment.astimezone(LAB_TIMEZONE).date()


def is_date_only(moment: datetime) -> bool:
    """Whether `moment` is midnight in UTC or lab time: a date entered without a
    time, e.g. date_coated of a Coated chip."""
    return any(t.time() == time(0) for t in (moment, moment.astimezone(LAB_TIMEZONE)))


def on_chip_at(coated_sample, moment: datetime) -> bool:
    """Whether the layer of a coated chip was on its chip at `moment`: from
    date_coated until before date_removed, or still if date_removed is empty.

    A date without a time counts as the whole day (lab time), so on the day one
    layer is removed and the next one coated, both count. A coated chip without
    date_coated counts never.
    """
    coated = as_utc(coated_sample.date_coated)
    removed = as_utc(coated_sample.date_removed)
    if coated is None:
        return False
    day = lab_day(moment)
    if lab_day(coated) > day if is_date_only(coated) else coated > moment:
        return False
    if removed is None:
        return True
    return day <= lab_day(removed) if is_date_only(removed) else moment < removed


def coated_sample_at(coated_samples: list, moment: datetime, chip_name, logger):
    """The (reference, section) among `coated_samples` whose layer was on the chip
    at `moment`; the newest one, with a warning, if several were (on the day one
    is removed and the next one coated); None, with a warning, if none was."""
    on_chip = [(ref, c) for ref, c in coated_samples if on_chip_at(c, moment)]
    if not on_chip:
        logger.warning(
            f'None of the {len(coated_samples)} coated chips of chip {chip_name} '
            f'was on it at {moment:%Y-%m-%d %H:%M} UTC, the datetime of the '
            'measurement; the bare chip is linked as sample'
        )
        return None
    newest = max(on_chip, key=lambda rc: (as_utc(rc[1].date_coated), rc[0]))
    if len(on_chip) > 1:
        listed = ', '.join(c.lab_id or c.name or ref for ref, c in on_chip)
        logger.warning(
            f'Coated chips {listed} of chip {chip_name} were all on it on '
            f'{lab_day(moment)}, the day of the measurement (by date); the newest, '
            f'{newest[1].lab_id or newest[1].name or newest[0]}, is linked as sample'
        )
    return newest


class AGE_ChipLink(ArchiveSection):
    """A measurement whose chip is picked on its overview page.

    chip is the user's choice of the bare chip (AGE_Sample). Its coating at the
    time of the measurement, the Coated chip whose layer was on it then, is
    derived from date_coated and date_removed and linked under samples, which the
    search apps filter by and the tracks entries of a video take over. A coating
    is not picked directly: NOMAD's reference dropdown cannot filter by date, so
    it would offer layers that did not exist at the time. AGE_Measurement syncs
    chip, coating and samples on normalize, see link_chip.
    """

    chip = Quantity(
        type=AGE_Sample,
        description=(
            'The chip (AGE Sample) measured on. Samples link its coated chip of the '
            'time of the measurement (datetime), or the bare chip if no layer was on '
            'it then: picking another chip here replaces the chip among the '
            'samples. Filled from the samples if empty; a choice made here stays '
            'when the file is processed again.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Chip'
        ),
    )

    coating = Quantity(
        type=AGE_CoatedSample,
        description=(
            'The coated chip of chip at the datetime of the measurement, between its '
            'date_coated and date_removed; empty if no layer was on the chip then. '
            'Derived on processing; pick the chip or edit the dates of the Coated '
            'chip entries instead.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Coating'
        ),
    )

    def link_chip(self, archive, logger) -> None:
        """Make the samples link exactly the coated chip (or the bare chip) of
        `chip` at the datetime of the measurement, and set coating to it.

        With chip set, the samples that link a chip (AGE Sample) or a coated chip
        are replaced by one that links it (an existing one that links it already
        is kept); other samples, e.g. particles, stay. Without chip, it is taken
        from the samples: the chip they link directly or as chip of a coated chip;
        if they link several chips, nothing changes. Without datetime the bare
        chip is linked. If the chip or its coated chips cannot be looked up, the
        samples stay as they are.
        """
        self.coating = None
        linked = []  # samples that link a chip or coated chip, and their chip
        for sample in self.samples:
            try:
                target = resolved(sample.reference)
            except Exception:
                continue  # list_samples_by_kind reports it
            if isinstance(target, AGE_Sample):
                linked.append((sample, linked_entry(sample.reference)))
            elif isinstance(target, AGE_CoatedSample):
                linked.append((sample, linked_entry(target.chip)))
        if self.chip is None:
            chips = unique(ids for _, ids in linked if isinstance(ids, tuple))
            if not chips:
                return
            if len(chips) > 1:
                listed = ', '.join(unique(s.lab_id or s.name for s, _ in linked))
                logger.warning(
                    f'Samples {listed} are on {len(chips)} different chips; chip not '
                    'set, samples left as they are'
                )
                return
            self.chip = entry_reference(chips[0])
        try:
            chip = resolved(self.chip)
        except Exception as e:
            logger.warning(f'Chip not loaded: {e!r}; samples left as they are')
            return
        chip_ids = linked_entry(self.chip)
        if not isinstance(chip, AGE_Sample) or not isinstance(chip_ids, tuple):
            logger.warning('Chip links no AGE Sample entry; samples left as they are')
            return
        chip_name = chip.lab_id or chip.name
        wanted = (entry_reference(chip_ids), chip)
        moment = as_utc(self.datetime)
        if moment is None:
            logger.warning(
                f'The measurement has no datetime, so the coating of chip '
                f'{chip_name} at its time is unknown; the bare chip is linked as '
                'sample'
            )
        else:
            try:
                coated_samples = coated_samples_of(chip_ids, archive)
            except Exception as e:
                logger.warning(
                    f'Coated chips of chip {chip_name} not looked up: {e!r}; samples '
                    'left as they are'
                )
                return
            wanted = (
                coated_sample_at(coated_samples, moment, chip_name, logger) or wanted
            )
        reference, target = wanted
        wanted_ids = parse_reference(reference)
        kept = next(
            (s for s, _ in linked if linked_entry(s.reference) == wanted_ids), None
        )
        if kept is None:
            kept = CompositeSystemReference(
                name=target.lab_id or target.name,
                lab_id=target.lab_id,
                reference=reference,
            )
        samples = replace_links(self.samples, [s for s, _ in linked], kept)
        if [id(s) for s in samples] != [id(s) for s in self.samples]:
            self.samples = samples
        if isinstance(target, AGE_CoatedSample):
            self.coating = reference


class AGE_ParticlesLink(ArchiveSection):
    """A measurement whose particle batches are picked on its overview page.

    particle_batches is the user's choice; the samples, which the search apps
    filter by and the tracks entries of a video take over, follow it.
    AGE_Measurement syncs the two on normalize, see link_particles.
    """

    particle_batches = Quantity(
        type=AGE_Particles,
        shape=['*'],
        description=(
            'The particle batch entries (Inventory) used for this measurement; '
            'several for a mix. Samples link the same entries: picking other '
            'batches here replaces the particles among the samples. Filled from '
            'the samples (e.g. the particles attribute of the file) if empty; a '
            'choice made here stays when the file is processed again.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.ReferenceEditQuantity, label='Particles'
        ),
    )

    def link_particles(self, logger) -> None:
        """Make the samples link exactly the batches of `particle_batches`.

        With batches picked, the samples that link a particle entry are replaced
        by one per picked batch, in its order (an existing one that links it
        already is kept); other samples, e.g. the chip, stay. Without batches,
        they are taken from the samples that link a particle entry. If a picked
        batch cannot be loaded, the samples stay as they are.
        """
        linked = []
        for sample in self.samples:
            try:
                if isinstance(resolved(sample.reference), AGE_Particles):
                    linked.append(sample)
            except Exception:
                continue  # list_samples_by_kind reports it
        picked = list(self.particle_batches or [])
        if not picked:
            if linked:
                self.particle_batches = unique(
                    reference_value(s.reference) for s in linked
                )
            return
        wanted = []  # (entry ids, reference, section), no duplicates
        for batch in picked:
            try:
                target = resolved(batch)
            except Exception as e:
                logger.warning(f'Particles not loaded: {e!r}; samples left as they are')
                return
            if not isinstance(target, AGE_Particles):
                logger.warning(
                    'Particles link no particle entry; samples left as they are'
                )
                return
            ids = linked_entry(batch)
            if all(ids != w[0] for w in wanted):
                wanted.append((ids, reference_value(batch), target))
        kept = []
        for ids, reference, target in wanted:
            sample = next((s for s in linked if linked_entry(s.reference) == ids), None)
            if sample is None:
                sample = CompositeSystemReference(
                    name=target.lab_id or target.name,
                    lab_id=target.lab_id,
                    reference=reference,
                )
            kept.append(sample)
        samples, placed = [], False
        for sample in self.samples:
            if sample not in linked:
                samples.append(sample)
            elif not placed:
                samples.extend(kept)
                placed = True
        if not placed:
            samples.extend(kept)
        if [id(x) for x in samples] != [id(x) for x in self.samples]:
            self.samples = samples
        if len(wanted) != len(picked):
            self.particle_batches = [reference for _, reference, _ in wanted]


def coated_samples_of(chip_ids: tuple, archive) -> list:
    """(reference, section) of the coated chips of the chip entry with (upload
    id, entry id) `chip_ids` that the main author of `archive` sees. Raises if
    the search or loading one of them fails."""
    main_author = archive.metadata.main_author if archive.metadata else None
    user_id = main_author.user_id if main_author else None
    coated_samples = []
    for ids in find_coated_samples(chip_ids[1], user_id):
        upload_id, entry_id = ids
        data = archive.m_context.load_archive(entry_id, upload_id, None).data
        if isinstance(data, AGE_CoatedSample) and linked_entry(data.chip) == chip_ids:
            coated_samples.append((entry_reference(ids), data))
    return coated_samples


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
        # before the base normalizer, which makes the workflow inputs of the
        # samples and sets an empty datetime to now
        if isinstance(self, AGE_ChipLink):
            self.link_chip(archive, logger)
        if isinstance(self, AGE_ParticlesLink):
            self.link_particles(logger)
        super().normalize(archive, logger)
        self.list_samples_by_kind(logger)
        if isinstance(self, AGE_ObjectiveLink):
            self.link_objective(logger)
        self.name_instruments(logger)

    def name_instruments(self, logger) -> None:
        """Name each instrument after the entry it links, so the search apps can
        show and filter by e.g. 'Zeiss Epiplan 20x/0.40 HD' instead of the lab_id.

        Falls back to the lab_id if the entry has no name; a name set by hand
        (other than the lab_id) is kept.
        """
        for instrument in self.instruments:
            if instrument.name and instrument.name != instrument.lab_id:
                continue
            try:
                target = resolved(instrument.reference)
            except Exception as e:
                logger.warning(
                    f'Instrument {instrument.lab_id} not named: entry not loaded: {e!r}'
                )
                continue
            name = getattr(target, 'name', None) if target is not None else None
            instrument.name = name or instrument.lab_id

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


# Normalizer output of AGE_Measurement and AGE_ChipLink, which the entry files do
# not store.
FROM_SAMPLES = (
    *(
        name
        for name in AGE_Measurement.m_def.all_properties
        if name not in Measurement.m_def.all_properties
    ),
    'coating',
)


class AGE_ParticleTransport(
    AGE_ParticleMicroscopy, AGE_FromRawFile, PlotSection, AGE_Measurement
):
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


class AGE_ParticleTransportVideo(
    AGE_ParticleTransport, AGE_ChipLink, AGE_ParticlesLink, AGE_ObjectiveLink, EntryData
):
    m_def = Section(
        label='Particle Transport Video',
        description=(
            'Camera video of a particle transport experiment, as saved by '
            'harvesters_pg (HDF5 with a frames dataset). Particles and objective '
            'come from its attributes particles and objective or are picked here '
            '(Particles, Objective); the chip comes from the file name or is picked '
            'here (Chip), its coating at the time of the video is derived. The '
            'tracks entries of the recording take over its samples and instruments.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                editable=dict(exclude=['lab_id', 'video_file', *FROM_SAMPLES]),
                order=[
                    'name',
                    'datetime',
                    'chip',
                    'coating',
                    'particle_batches',
                    'objective',
                ],
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


class AGE_FocusSweep(
    AGE_ParticleMicroscopy,
    AGE_FromRawFile,
    PlotSection,
    AGE_Measurement,
    AGE_ChipLink,
    AGE_ParticlesLink,
    AGE_ObjectiveLink,
    EntryData,
):
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
                order=[
                    'name',
                    'datetime',
                    'chip',
                    'coating',
                    'particle_batches',
                    'objective',
                ],
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
