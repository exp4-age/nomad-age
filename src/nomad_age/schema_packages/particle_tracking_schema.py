from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.basesections import Measurement
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.metainfo import JSON, MEnum, Quantity, SchemaPackage, Section

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


class AGE_ParticleTracking(AGE_ParticleMicroscopy, PlotSection, Measurement, EntryData):
    m_def = Section(
        label='Particle Tracking',
        description='Particle trajectories tracked with trackpy in a microscope video.',
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                editable=dict(
                    exclude=[
                        'lab_id',
                        'tracks_file',
                        'filtered_tracks_file',
                        'video_file',
                    ]
                ),
            )
        ),
    )

    lab_id = Quantity(
        type=str,
        description=(
            'Random id (attribute recording_id) that the acquisition software gives '
            'each recording and the tracking scripts copy into the tracks. Empty '
            'for older recordings.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity, label='Recording ID'
        ),
    )

    tracks_file = Quantity(
        type=str,
        description='trackpy trajectory table (*_trajs.h5) of the recording.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity,
            label='Tracks File',
        ),
    )

    filtered_tracks_file = Quantity(
        type=str,
        description='Filtered trajectory table (*_filtered_trajs.h5) of the recording.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity,
            label='Filtered Tracks File',
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
        description='Video frames covered by the tracks (highest frame index + 1).',
    )

    n_particles = Quantity(
        type=int,
        description='Distinct particles in the unfiltered tracks.',
    )

    n_localizations = Quantity(
        type=int,
        description='Localizations (table rows) in the unfiltered tracks.',
    )

    n_particles_filtered = Quantity(
        type=int,
        description='Distinct particles in the filtered tracks.',
    )

    n_localizations_filtered = Quantity(
        type=int,
        description='Localizations (table rows) in the filtered tracks.',
    )

    camera_settings = Quantity(
        type=JSON,
        description='All HDF5 root attributes written by the acquisition software.',
    )

    def normalize(self, archive, logger):
        self.method = 'Particle Tracking'
        super().normalize(archive, logger)


class AGE_FocusSweep(AGE_ParticleMicroscopy, PlotSection, Measurement, EntryData):
    m_def = Section(
        label='Focus Sweep',
        description=(
            'Microscope z sweep: one image and one Tenengrad sharpness value per '
            'stage position.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['lab_id']),
                editable=dict(exclude=['data_file']),
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
