from nomad.config import config
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    Filter,
    SectionProperties,
)
from nomad.datamodel.metainfo.basesections import Process
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.datamodel.metainfo.workflow import Link
from nomad.metainfo import (
    Datetime,
    Quantity,
    SchemaPackage,
    Section,
    SubSection,
)

from nomad_age.schema_packages.age_schema import AGE_FromRawFile

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:ion_bombardment_schema_entry_point'
)

m_package = SchemaPackage(name='ion_bombardment_schema')

# Method name the chip looks for to set its state to 'after IB'.
ION_BOMBARDMENT_METHOD = 'Helium Ion Bombardment'


class AGE_IonBombardmentPoint(ArchiveSection):
    """One position of the bombardment table at the end of the ISA log."""

    m_def = Section(label='Bombarded position')

    name = Quantity(type=str, description='Name in the log, e.g. Point3.')

    number = Quantity(type=int, description='Number of the position in the log.')

    reference_spot = Quantity(
        type=bool,
        description=(
            'A position with a wanted dose of 0 that still got a short shot; '
            'not counted in min/max dose.'
        ),
    )

    x = Quantity(type=float, unit='cm', description='x position of the stage.')

    y = Quantity(type=float, unit='cm', description='y position of the stage.')

    dose_wanted = Quantity(
        type=float,
        unit='1 / cm**2',
        description='Dose set for this position (ions/cm²).',
    )

    dose_bombarded = Quantity(
        type=float,
        unit='1 / cm**2',
        description=(
            'Dose applied (ions/cm²): the last of the listed doses (PyBeamer adds '
            'one per dose check, e.g. again after a pause; clipped to what the beam '
            'allows), 0 if not bombarded. In area mode it is on Point1.'
        ),
    )

    dose_record = Quantity(
        type=str,
        description='The bombarded dose exactly as listed in the log.',
    )

    assigned = Quantity(type=bool, description='Position assigned in the software.')

    bombarded = Quantity(type=bool, description='Position bombarded.')

    bombardment_time = Quantity(
        type=float, unit='s', description='Actual bombardment time of a point.'
    )

    velocity = Quantity(
        type=float,
        unit='cm / s',
        description=(
            'Scan velocity in area, line and gradient mode (same log column as '
            'the bombardment time of a point).'
        ),
    )


class AGE_IonBombardment(PlotSection, AGE_FromRawFile, Process, EntryData):
    m_def = Section(
        label='Helium Ion Bombardment',
        description=(
            'A helium ion bombardment (ISA) of a chip, parsed from the logger.txt of '
            'the ISA software.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                visible=Filter(exclude=['lab_id']),
                editable=dict(exclude=['data_file', 'log_format_version']),
            )
        ),
    )

    log_format_version = Quantity(
        type=str,
        description=(
            'Format version of the ISA log that the parser recognised (1 = ISA '
            'software as used 2025-2026, without a version line).'
        ),
    )

    end_time = Quantity(type=Datetime, description='Time of the last log line.')

    ion_energy = Quantity(
        type=float,
        unit='keV',
        description='Energy of the helium ions. Not in the log; enter it by hand.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity, defaultDisplayUnit='keV'
        ),
    )

    number_of_points = Quantity(
        type=int, description='Number of positions in the bombardment table.'
    )

    number_bombarded = Quantity(type=int, description='Number of bombarded positions.')

    number_reference_spots = Quantity(
        type=int, description='Bombarded points with a wanted dose of 0.'
    )

    bombardment_mode = Quantity(
        type=str,
        description=(
            "'multi point', 'area' (rectangle between Point1 and Point2, e.g. the "
            "whole sample) or 'line or gradient'; derived, the log does not name it."
        ),
    )

    min_dose = Quantity(
        type=float,
        unit='1 / cm**2',
        description='Smallest non-zero bombarded dose, without reference spots.',
    )

    max_dose = Quantity(
        type=float, unit='1 / cm**2', description='Largest bombarded dose.'
    )

    max_beam_current = Quantity(
        type=float, unit='A', description='Highest beam current in the log.'
    )

    mean_chamber_pressure = Quantity(
        type=float, unit='mbar', description='Mean chamber pressure.'
    )

    source_setpoint = Quantity(
        type=float,
        unit='mbar',
        description='Median source pressure setpoint.',
    )

    lens_setpoint = Quantity(type=float, unit='V', description='Median lens setpoint.')

    magnet_setpoint = Quantity(
        type=float, unit='A', description='Median magnet setpoint.'
    )

    points = SubSection(
        section_def=AGE_IonBombardmentPoint,
        repeats=True,
        description='The bombardment table of the log.',
    )

    time = Quantity(
        type=float, shape=['*'], unit='s', description='Time since the first line.'
    )

    pre_pressure = Quantity(type=float, shape=['*'], unit='mbar')
    chamber_pressure = Quantity(type=float, shape=['*'], unit='mbar')
    source_pressure = Quantity(type=float, shape=['*'], unit='mbar')
    beam_current = Quantity(type=float, shape=['*'], unit='A')
    magnet_current = Quantity(type=float, shape=['*'], unit='A')
    plasma_current = Quantity(type=float, shape=['*'], unit='A')
    plasma_voltage = Quantity(type=float, shape=['*'], unit='V')
    x_position = Quantity(type=float, shape=['*'], unit='cm')
    y_position = Quantity(type=float, shape=['*'], unit='cm')

    data_file = Quantity(
        type=str,
        description='Name of the ISA log file.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity, label='ISA log file'
        ),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.method = ION_BOMBARDMENT_METHOD
        archive.workflow2.inputs = [
            Link(name=sample.name, section=sample.reference)
            for sample in self.samples
            if sample.reference is not None
        ]


m_package.__init_metainfo__()
