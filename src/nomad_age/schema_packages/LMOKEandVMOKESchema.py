from nomad.datamodel import ArchiveSection
from nomad.metainfo import Quantity, Datetime, SubSection, Section, Package

lmoke_vmoke_package = Package(name='lmoke_vmoke_nomadmetainfo_json', description='None')

"""
Quantities to be defined:

##### Device / Sample Specific
- **User**: The user who performed the measurement.
- **Sample**: The sample being measured.
- **Sample State**: The state of the sample (e.g., "as made", "after FC", "after IB").
- **Device**: The device used for the measurement.
- **Datetime**: The date and time of the measurement.
- **UUID**: The unique identifier of the measurement.

##### Measurement Metadata
- **Meas. type**: The type of measurement (e.g., "Hysteresis", "Minor loops", "Raster").
- **Profile**: The profile used during the measurement.
- **Sample Angle**: The angle of the sample (clockwise).
- **Field Angle**: The angle of the field (clockwise).
- **Temperature**: The temperature during the measurement.
- **Calibration**: The calibration used for the measurement.
- **Polarization**: The polarization of the light used for the measurement.
- **Hmin**: The minimum magnetic field.
- **Hmax**: The maximum magnetic field.
- **Pts/branch**: The number of points per branch.
- **Time/pt**: The time per point.
- **Delay Time**: The delay time between measurements.
- **nCycles**: The number of cycles.
- **Cycle**: The current cycle.
- **Comment**: Additional comments about the measurement.

##### Optional Metadata
- **Hstop**: The stopping magnetic field.
- **Wait Time**: The wait time between measurements.
- **nSched**: The number of schedules.
- **nMinorLoops**: The number of minor loops (also Forc. loops).
- **nX**: The number of points in the X direction.
- **nY**: The number of points in the Y direction.
- **DeltaX**: The total size in the X direction.
- **DeltaY**: The total size in the Y direction.
- **X**: The current position in the X direction.
- **Y**: The current position in the Y direction.
- **Avg. Raster**: Whether the raster is averaged.
- **Max Voltage Correction**: TODO: What is this?
- **Training Effect Elimination**: TODO: What is this?

##### Measurement Data
- **Longitudinal Magnetic Field**: The longitudinal magnetic field.
- **Transversal Magnetic Field**: The transversal magnetic field (only for VMOKE).
- **Total Field**: The total magnetic field (for LMOKE, equal to longitudinal).
- **Field Angle**: The angle of the magnetic field.
- **Longitudinal Intensity**: The intensity of the longitudinal detector signal.
- **Transversal Intensity**: The intensity of the transversal detector signal (only for VMOKE).
- **Diff. Intensity Longitudinal**: The differential intensity of the longitudinal detector signal (only for VMOKE).
- **Longitudinal Magnetization**: The longitudinal magnetization.
- **Transversal Magnetization**: The transversal magnetization (only for VMOKE).
"""

class LMOKEandVMOKESchema(ArchiveSection):
    m_def = Section()

    ###### Device / Sample specfic + uuid
    user = Quantity(
        type=str,
        description='User name. Name and surname of the person who performed the measurement.',
    )

    sample = Quantity(
        type=str,
        description='Sample name. The letter describes its origin.', # e.g. P2024_0123
    )

    sample_state = Quantity(
        type=str,
        description='The state of the sample during the measurement.', # as made, after FC, after IB, etc.
    )

    device = Quantity(
        type=str,
        description='Measurement device.', #LMOKE or VMOKE
    )

    datetime = Quantity(
        type=str,
        description='Date and time of the measurement. Typically at its end.',
    )

    uuid = Quantity(
        type=str,
        description='UUID of the measurement. Not yet implemented in all machines.',
    )

    ###### Measurement metadata/parameters
    meas_type = Quantity(
        type=str,
        description='Measurement type. E.g. Hystersis, FORC, etc.',
    )

    profile = Quantity(
        type=str,
        description='Measurement profile (may differ from meas. parameters)',
    )

    sample_angle = Quantity(
        type=float,
        description='Sample angle in degrees (clockwise, realtive to beam path direction)',
        unit='degree',
    )

    field_angle = Quantity(
        type=float,
        description='Field angle in degrees (clockwise, realtive to beam path direction)',
        unit='degree',
    )

    temperature = Quantity(
        type=float,
        description='Temperature in K. Typically 300K as not always tracked/controlled.',
        unit = 'K',
    )

    calibration = Quantity(
        type=str,
        description='Calibration file of the measurement.',
    )

    polarization = Quantity(
        type=str,
        description='Polarization of the measurement. Typically s or p. Maybe more complex in the future.', #s for s-polarized (LMOKE), p for p-polarized (VMOKE)
    )

    H_start = Quantity(
        type=float,
        description='Starting field of the measurement in **mT**, kA/m or Oe. Typically larger than Hend', #old files may use kA/m
        unit = 'mT',
    )

    H_end = Quantity(
        type=float,
        description='Final field of the first branch in **mT**, kA/m or Oe', #old files may use kA/m
        unit = 'mT',
    )

    pts_per_branch = Quantity(
        type=int,
        description='Number of points per branch. I.e. resolution of the measurement with respect to the field.',
    )

    time_per_point = Quantity(
        type=float,
        description='Detector integration time per point in s.',
        unit = 's',
    )

    delay_time = Quantity(
        type=float,
        description='Delay time between points in s. I.e. equilibration time after a new field is applied.',
        unit = 's',
    )

    nCycles = Quantity(
        type=int,
        description='Number of loop measurements (cycles) to be averaged per hysteresis (e.g. see Scheduled or Raster mode).',
    )

    cycle = Quantity(
        type=int,
        description='Current/Last saved cycle number.',
    )

    comment = Quantity(
        type=str,
        description='Comment on the measurement.',
    )


    ###### Optional metadata
    H_stop = Quantity(
        type=float,
        description='Stopping field of MinorLoops/FORC measurements in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    wait_time = Quantity(
        type=float,
        description='Wait time of scheduled mode (LMOKE) between measurements in s.',
        unit = 's',
    )

    nSched = Quantity(
        type=int,
        description='Number of scheduled measurements (typ. major loops).',
    )

    nMinorLoops_nFORCs = Quantity(
        type=int,
        description='Number of measurements for minor loops or FORC loops',
    )

    nX = Quantity(
        type=int,
        description='Total number of points in X', #Only LMOKE
    )

    nY = Quantity(
        type=int,
        description='Total number of points in Y', #Only LMOKE
    )

    DeltaX = Quantity(
        type=float,
        description='Total size in X in mm', #Only LMOKE
        unit = 'mm',
    )

    DeltaY = Quantity(
        type=float,
        description='Total size in Y in mm', #Only LMOKE
        unit = 'mm',
    )

    X = Quantity(
        type=int,
        description='Current position in X as point number (1-based index)', #Only LMOKE
    )

    Y = Quantity(
        type=int,
        description='Current position in Y as point number (1-based index)', #Only LMOKE
    )

    avg_raster = Quantity(
        type = bool,
        description='True if the measurement is averaged over a raster', #old mode, still usable but not recommended
    )

    max_voltage_correction = Quantity(
        type=bool, # TODO: Check if this is correct
        description='Maximum voltage correction for the measurement', #Only VMOKE
    )

    training_effect_elimination = Quantity(
        type=bool,
        description='True if training effect elimination is applied', #Only VMOKE
    )

    ###### Measurement Data
    # Maybe instead of defining all these quantities together, a single quantity for each
    # of the following is defined:
    # magnetic field with shape [longitudinal, transversal, total]
    # intensity with shape [longitudinal, transversal, diff_longitudinal]
    # magnetization with shape [longitudinal, transversal, total]

    # Magnetic field
    magnetic_field = Quantity(
        type=float,
        shape = [None], # either [longitudinal, transversal, total] or [longitudinal]
        description='Magnetic fields / field components in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    # Intensity
    intensity = Quantity(
        type=float,
        shape = [None], # either [longitudinal, transversal, diff_longitudinal] or [longitudinal]
        description='Intensity measured at the detectors in detector voltage representing light intensity.',
        unit = 'V',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Magnetization
    magnetization = Quantity(
        type=float,
        shape = [None], # either [longitudinal, transversal, total] or [longitudinal]
        description='Magnetization in arbitrary units (typically normalized).',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    ####### Evaluated values
    # Coercivity
    HC = Quantity(
        type=float,
        description='Coercivity in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    dHC = Quantity(
        type=float,
        description='Uncertainty of the coercivity in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    # Exchange bias
    HEB = Quantity(
        type=float,
        description='Exchange bias in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    dHEB = Quantity(
        type=float,
        description='Uncertainty of the exchange bias in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    # Magnetization saturation
    MS = Quantity(
        type=float,
        description='Saturation magnetization in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    dMS = Quantity(
        type=float,
        description='Uncertainty of the saturation magnetization in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Remanent magnetization
    MR = Quantity(
        type=float,
        shape = [3],
        description='Remanent magnetization in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    dMR = Quantity(
        type=float,
        description='Uncertainty of the remanent magnetization in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Magnetization at exchange bias
    MHEB = Quantity(
        type=float,
        shape = [3],
        description='Magnetization at exchange bias in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    dMHEB = Quantity(
        type=float,
        description='Uncertainty of the magnetization at exchange bias in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Integral of the hysteresis loop
    integral = Quantity(
        type=float,
        description='Integral of the hysteresis loop in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    dintegral = Quantity(
        type=float,
        description='Uncertainty of the integral of the hysteresis loop in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Saturation fields
    saturation_fields = Quantity(
        type=float,
        shape = [2],
        description='Saturation fields in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    dsaturation_fields = Quantity(
        type=float,
        shape = [2],
        description='Uncertainty of the saturation fields in **mT**, kA/m or Oe.',
        unit = 'mT',
    )

    # Slope at HC
    slope_atHC = Quantity(
        type=float,
        description='Slope at the coercivity in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    dslope_atHC = Quantity(
        type=float,
        description='Uncertainty of the slope at the coercivity in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Slope at HEB
    slope_atHEB = Quantity(
        type=float,
        description='Slope at the exchange bias in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    dslope_atHEB = Quantity(
        type=float,
        description='Uncertainty of the slope at the exchange bias in arb. u.',
        a_eln=dict(defaultDisplayUnit='arb. u.'),
    )

    # Angle enclosed by the hysteresis loop slopes
    alpha = Quantity(
        type=float,
        description='Angle enclosed by the hysteresis loop slopes (at HC and HEB) in degrees.',
    )

    dalpha = Quantity(
        type=float,
        description='Uncertainty of the angle enclosed by the hysteresis loop slopes (at HC and HEB) in degrees.',
    )

    # Rectangularity
    rectangularity = Quantity(
        type=float,
        description='Normalized rectangularity of the hysteresis loop.',
    )

    drectangularity = Quantity(
        type=float,
        description='Uncertainty of the norm. rectangularity of the hysteresis loop.',
    )

lmoke_vmoke_package.__init_metainfo__()