from nomad.metainfo import Quantity

"""
OVERVIEW OF OLD LOGS

#Problem current version:
- IDs are referring ot SQL table entries

OLD Layer logs
    * header
        - Sample name
        - date
        - UserID
        - AnlagenID
        - SubstratID
        - VorbehandlungID
        - Chargen Bemerkung
        - Base pressure
        - Sample Anzahl
        - Aufbewahrungsort
        - Status
        - SchichtID
        - SputerratenID
        - Schichtdicke
        - Magnetfeld
        - Schichten Bemerkung
        - Potential
        - Gasfluss
        - Rate
        - Material
        - ReaktivgasID
        - Reaktivgasfluss

    * table
        - Timestamp
        - Matchbox-Tmperatur [°C]
        - Druck Pirani [mbar]
        - Druck Penning [mbar]
        - DC-Potential [-V] # I don't know why -
        - Setpoint Spannung [-V]
        - Leistung Forwarded [W]
        - Leistung Reflected [W]
        - Phase [mV]
        - Magnitude [mV]
        - Tune [%]
        - Load [%]
        - Kühlwasserfluss Pumpen [l/min]
        - Kühlwasserfluss Targets [l/min]

        #Timer gestartet





OLD Rate logs
    * header
        - Sample name
        - date
        - UserID
        - AnlagenID
        - SubstratID
        - VorbehandlungID
        - Chargen Bemerkung
        - Base pressure
        - TargetID
        - GasID
        - Gasfluss
        - Potential
        - ReaktivgasID
        - Reaktivgasfluss
        - Kühlfalle
        - Magnetfeld

    * table
        - Timestamp
        - Matchbox-Tmperatur [°C]
        - Druck Pirani [mbar]
        - Druck Penning [°C]
        - DC-Potential [-V] # I don't know why -
        - Setpoint Spannung [-V]
        - Leistung Forwarded [W]
        - Leistung Reflected [W]
        - Phase [mV]
        - Magnitude [mV]
        - Tune [%]
        - Load [%]
        - Kühlwasserfluss Pumpen [l/min]
        - Kühlwasserfluss Targets [l/min]

        #Timer gestartet


OLD Machine logs
    # Userlog.txt
        - Date
        - Timestamp
        - Username/Logout

    # Pressurelog.txt
        - Date
        - Timestamp
        - pressure chamber [mbar]
        - pirani loadlock [mbar]
        - penning loadlock [mbar]

    # Ratenarray.txt
        - rate_id
        - rate [nm/min]
        - rate_uncertainty [nm/min]
        - sputter power [W]
        - gas flow [sscm]
        - date
        - setpoint voltage [V]
        - Material
        - material_id



CONFIG(labview reads and writes here)
    - Alarm-Log.txt
    - Targets.txt
    - Sputterprotokollnr.dat
    - Schichtnr.dat
    - neu
    - eingetragen
    - fehlerhaft
    - Arrays
    - Userlog.txt
    - Pressurelog.txt

    ARRAYS (labview reads this) These properties are currently as IDs in the log files
    - Userarray
    - Targetarray
    - VorbehandlungArray
    - SubstratArray
    - Chargenarray
    - Layerarray
    - Ratearray

##########################################################################################
Quantities to be defined:
- Metadata (saved upon (de)activation of standby)
    - Datetime login
    - Softwareversion
    - User
    - Targets
    - Magnet
    - Datetime logout

-
- Process data layer
    - header (set values)
        - UUID
        - Comment
        - number of substrates # should create duplicates depending on number, and make
          corresponding entries in the DB
        - substrate
        - substrate preperation
        - Charge name
        - layer number
        - setpoint Ar [sccm]
        - Setpoint Spannung [-V]
        - layer thickness [nm]
        - Target material
        - rate [nm/min]
        - rate uncertainty [nm/min]


    - table (values which change during process)
        - Timestamp
        - presputter start
        - presputter end
        - sputter start #if this is missing, something went wrong
        - sputter end #if this is missing, something went wrong
        - Matchbox-Temperatur [°C]
        - Pressure loadlock pirani [mbar]
        - Pressure loadlock penning [mbar]
        - Pressure chamber pirani [mbar]
        - Pressure chamber penning [mbar]
        - DC-Potential [-V]
        - Leistung Forwarded [W]
        - Leistung Reflected [W]
        - Phase [mV]
        - Magnitude [mV]
        - Tune [%]
        - Load [%]
        - Voltage Poti [V]
        - output Ar [sccm]
        - active target


- Ratenarray.txt
    - rate_id
    - rate [nm/min]
    - rate_uncertainty [nm/min]
    - sputter power [W]
    - gas flow [sscm]
    - date
    - setpoint voltage [V]
    - Material
    - material_id

- Standby data (pressure log)
    - Pressure loadlock pirani [mbar]
    - Pressure loadlock penning [mbar]
    - Pressure chamber pirani [mbar]
    - Pressure chamber penning [mbar]

global sample metadata
    - location of sample
    - status of sample
"""


class Z400Schema:
    # - Metadata (saved upon (de)activation of standby)
    user = Quantity(
        type=str,
        description=(
            'User name. Name and surname of the person who deactivated the standby.'
        ),
    )

    datetime_login = Quantity(
        type=str,
        description=('Datetime when the standby was deactivated.'),
    )

    software_version = Quantity(
        type=str,
        description=('Software version of the Z400 software.'),
    )

    targets = Quantity(
        type=str,
        description=('Targets currently present in the machine.'),
        shape=['*'],  # should be exactly 4
    )

    magnet = Quantity(
        type=bool,
        description=('Whether the magnet is installed or not.'),
    )

    datetime_logout = Quantity(
        type=str,
        description=('Datetime when the standby was activated.'),
    )

    # global sample metadata
    sample_location = Quantity(
        type=str,
        description=('Location of the sample.'),
    )

    sample_state = Quantity(
        type=str,
        description=('State of the sample.'),
    )

    # process_data header
    uuid = Quantity(
        type=str,
        description=('UUID of the sputter process, for the respective layer.'),
    )

    comment = Quantity(
        type=str,
        description=('Comment for the sputter process.'),
    )

    number_of_substrates = Quantity(
        type=int,
        description=('Number of substrates on the sample holder.'),
    )

    substrate = Quantity(
        type=str,
        description=('Name of the substrate.'),
    )

    substrate_preperation = Quantity(
        type=str,
        description=('Name of the substrate preperation (cleaning).'),
    )

    Charge_name = Quantity(
        type=str,
        description=('Name of the charge.'),
    )

    layer_number = Quantity(
        type=int,
        description=('Number of the current layer.'),
    )
    setpoint_Ar = Quantity(
        type=float,
        description=('Setpoint for the Ar flow.'),
        unit='sccm',
    )

    setpoint_voltage = Quantity(
        type=float,
        description=('Setpoint voltage for the sputter process.'),
        unit='V',
    )

    layer_thickness = Quantity(
        type=float,
        description=('Layer thickness for the sputter process.'),
        unit='nm',
    )

    target_material = Quantity(
        type=str,
        description=('Material of the target.'),
    )
    rate = Quantity(
        type=float,
        description=('Rate for the sputter process.'),
        unit='nm/min',
    )
    uncertainty_rate = Quantity(
        type=float,
        description=('Uncertainty of the rate for the sputter process.'),
        unit='nm/min',
    )

    uncertainty_thickness = Quantity(
        type=float,
        description=('Uncertainty of the layer thickness for the sputter process.'),
        unit='nm',
    )

    # process_data table

    date_time_process = Quantity(
        type=str,
        description=('Datetime of the process.'),
    )

    matchbox_temperature = Quantity(
        type=float,
        description=('Temperature of the matchbox.'),
        unit='°C',
    )

    pressure_loadlock_pirani = Quantity(
        type=float,
        description=('Pressure in the loadlock, measured by the pirani sensor.'),
        unit='mbar',
    )

    pressure_loadlock_penning = Quantity(
        type=float,
        description=('Pressure in the loadlock, measured by the penning sensor.'),
        unit='mbar',
    )

    pressure_chamber = Quantity(
        type=float,
        description=(
            'Pressure in the chamber, measured by the either pirani or penning sensor.'
        ),
        unit='mbar',
    )

    DC_potential = Quantity(
        type=float,
        description=('DC potential of the sputter process.'),
        unit='V',
    )

    tune = Quantity(
        type=float,
        description=('Tune of the sputter process.'),
        unit='%',
    )

    load = Quantity(
        type=float,
        description=('Load of the sputter process.'),
        unit='%',
    )

    phase = Quantity(
        type=float,
        description=('Phase of the sputter process.'),
        unit='mV',
    )

    magnitude = Quantity(
        type=float,
        description=('Magnitude of the sputter process.'),
        unit='mV',
    )

    sputter_power_forwarded = Quantity(
        type=float,
        description=('Forwarded sputter power of the sputter process.'),
        unit='W',
    )

    sputter_power_reflected = Quantity(
        type=float,
        description=('Reflected sputter power of the sputter process.'),
        unit='W',
    )

    voltage_poti = Quantity(
        type=float,
        description=('Voltage of the poti.'),
        unit='V',
    )

    output_Ar = Quantity(
        type=float,
        description=('Output of the Ar flow.'),
        unit='sccm',
    )

    # if any of these below are missing, something went wrong
    # - presputter start
    # - presputter end
    # - sputter start
    # - sputter end

    # unsure about these:
    # - active target?
