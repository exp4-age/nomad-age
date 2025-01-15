import re
from typing import Union

import numpy
from nomad.datamodel import EntryArchive
from nomad.parsing import MatchingParser
from nomad.parsing.file_parser import DataTextParser, Quantity, TextParser

from nomad_age.schema_packages.LMOKEandVMOKESchema import LMOKEandVMOKESchema


def assign_as_single_string(value):
    """
    Converts a list, tuple, or numpy array to a single string joined by spaces.
    If the input is not a list, tuple, or numpy array, it returns the input value as is.

    Parameters:
    value (Union[list, tuple, numpy.ndarray, any]): The input value to be converted.

    Returns:
    str: A single string with elements joined by spaces if the input is a list,
         tuple, or numpy array. Otherwise, returns the input value as is.
    """
    if isinstance(value, Union[list, tuple, numpy.ndarray]):
        return ' '.join(map(str, value))
    return value


class LMOKEParser(MatchingParser):
    """
    Parser for LMOKE (Longitudinal Magneto-Optic Kerr Effect) measurement files.

    This parser extracts metadata and experimental data from LMOKE measurement files.
    The metadata is extracted using regular expressions, and the experimental data is
    processed using the DataTextParser.

    Arguments:
        mainfile: str
            The path to the main file to be parsed.
        archive: EntryArchive
            The archive object where the parsed data will be stored.
        logger: Logger
            The logger object for logging messages.
        child_archives: dict[str, EntryArchive], optional
            A dictionary of child archives, if any.
    """

    def parse(
        self,
        mainfile: str,
        archive: EntryArchive,
        logger,
        child_archives: dict[str, EntryArchive] = None,
    ) -> None:
        """
        Parses the LMOKE measurement file and extracts metadata and experimental data.

        Parameters:
            mainfile (str): The path to the main file to be parsed.
            archive (EntryArchive): The archive object to store the parsed data.
            logger (Logger): The logger object for logging messages.
            child_archives (Dict[str, EntryArchive], optional): A dictionary of child
            archives, if any.
        """
        logger.info(f'LMOKEParser called on {mainfile}')
        lmokeandvmokeschema = LMOKEandVMOKESchema()

        # Read the file content
        with open(mainfile) as f:
            content = f.read()

        # Split the content at the separator line
        try:
            _metadata_content, data_content = re.split(r'#\s-{4,}', content, maxsplit=1)
        except ValueError:
            _metadata_content = data_content = content
        tmp_data_file = 'tmp_data_file.txt'
        with open(tmp_data_file, 'w') as f:
            f.write(data_content)

        # get datetime from filename
        datetime_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})')
        matches = datetime_pattern.findall(mainfile)
        if matches:
            lmokeandvmokeschema.datetime = matches[0]
        if not matches:
            # get datetime from file creation time
            import os
            import time

            creation_time = os.path.getctime(mainfile)
            lmokeandvmokeschema.datetime = time.strftime(
                '%Y-%m-%d_%H-%M-%S', time.localtime(creation_time)
            )

        mainfile_parser.mainfile = mainfile
        mainfile_parser.parse()  # extract all metadata from the mainfile

        logger.info(f'Extracted metadata from {mainfile}')

        # Check if UUID is present to determine if it's a new file
        uuid = mainfile_parser.get('UUID')
        if uuid is None:
            # Old files (before 2025): use hardcoded values for missing quantities
            lmokeandvmokeschema.uuid = 'None'
            lmokeandvmokeschema.device = 'LMOKE'
            lmokeandvmokeschema.field_angle = 0.0
            lmokeandvmokeschema.temperature = 300.0
            lmokeandvmokeschema.calibration = 'None'
            lmokeandvmokeschema.polarization = 's'
            lmokeandvmokeschema.X = 0.0  # TODO: Extract from filename
            lmokeandvmokeschema.Y = 0.0  # TODO: Extract from filename
        else:
            # New files (starting from 2025): use parsed values
            lmokeandvmokeschema.uuid = uuid
            lmokeandvmokeschema.device = mainfile_parser.get('Device')
            lmokeandvmokeschema.field_angle = mainfile_parser.get('Field angle')
            lmokeandvmokeschema.temperature = mainfile_parser.get('Temperature')
            lmokeandvmokeschema.calibration = mainfile_parser.get('Calibration')
            lmokeandvmokeschema.polarization = mainfile_parser.get('Polarization')
            lmokeandvmokeschema.X = mainfile_parser.get('X')
            lmokeandvmokeschema.Y = mainfile_parser.get('Y')

        lmokeandvmokeschema.user = assign_as_single_string(mainfile_parser.get('User'))
        lmokeandvmokeschema.sample = mainfile_parser.get('Sample')
        lmokeandvmokeschema.sample_state = assign_as_single_string(
            mainfile_parser.get('Sample State')
        )
        lmokeandvmokeschema.meas_type = mainfile_parser.get('Meas. type')
        lmokeandvmokeschema.profile = mainfile_parser.get('Profile')
        lmokeandvmokeschema.sample_angle = mainfile_parser.get('Sample angle')
        lmokeandvmokeschema.H_start = mainfile_parser.get('Hstart')
        lmokeandvmokeschema.H_end = mainfile_parser.get('Hend')
        lmokeandvmokeschema.pts_per_branch = mainfile_parser.get('Pts/branch')
        lmokeandvmokeschema.time_per_point = mainfile_parser.get('Time/pt')
        lmokeandvmokeschema.delay_time = mainfile_parser.get('Delay time')
        lmokeandvmokeschema.nCycles = mainfile_parser.get('nCycles')
        lmokeandvmokeschema.cycle = mainfile_parser.get('Cycle')
        lmokeandvmokeschema.H_stop = mainfile_parser.get('Hstop')
        lmokeandvmokeschema.wait_time = mainfile_parser.get('Wait time')
        lmokeandvmokeschema.nSched = mainfile_parser.get('nSched')
        lmokeandvmokeschema.nMinorLoops = mainfile_parser.get('nMinorLoops')
        lmokeandvmokeschema.nX = mainfile_parser.get('nX')
        lmokeandvmokeschema.nY = mainfile_parser.get('nY')
        lmokeandvmokeschema.DeltaX = mainfile_parser.get('DeltaX')
        lmokeandvmokeschema.DeltaY = mainfile_parser.get('DeltaY')

        lmokeandvmokeschema.avg_raster = False
        if mainfile_parser.get('Avg. raster') is not None:
            if 'no' not in mainfile_parser.get('Avg. raster').lower():
                lmokeandvmokeschema.avg_raster = True

        # Comment is over several lines which is not supported by the mainfile_parser
        # (flags?!)
        with open(mainfile) as f:
            content = f.read()
            comment_pattern = re.compile(
                r'#\sComment\s+(.*?)(?=\n#\sMeas\.\stype|\n#\s-{4,})', re.DOTALL
            )
            matches = comment_pattern.findall(content)
            if matches:
                comment_lines = matches[0].split('\n')
                # remove "# " at the beginning of each line
                processed_comment_lines = [
                    line.lstrip('# ').strip() for line in comment_lines
                ]
                lmokeandvmokeschema.comment = '\n'.join(processed_comment_lines)
            else:
                lmokeandvmokeschema.comment = 'None'

        # Process the experimental data using DataTextParser
        experimental_data_parser.mainfile = tmp_data_file
        experimental_data_parser.parse()

        lmokeandvmokeschema.magnetic_field = experimental_data_parser.get(
            'Longitudinal magnetic field'
        )
        lmokeandvmokeschema.intensity = experimental_data_parser.get(
            'Longitudinal detector signal'
        )

        archive.data = lmokeandvmokeschema
        logger.info(f'Stored metadata in {archive}')


"""
# This is the mainfile parser for LMOKE measurements (similar to VMOKEs parser).
# The mainfile contains all the metadata (and data) of the measurement.
# The metadata is extracted using regular expressions.
# The metadata is then stored in a schema object.
"""
mainfile_parser = TextParser(
    quantities=[
        ## General (most important) metadata
        # Extracts the first and last name of the user
        Quantity(
            'User', r'#\sUser\s+([A-Z][a-z]+\s[A-Z][a-z]+)', repeats=False, dtype=str
        ),
        # Extracts the sample name, E for External, Z for Z400 and P for Prevac
        Quantity('Sample', r'([EZP]?\d{4}_\d{4}_\d)', repeats=False, dtype=str),
        # Extracts the sample state, typically "as made", "after FC" or "after IB"
        Quantity('Sample State', r'#\sState\s+([a-zA-Z\s]+)', repeats=False, dtype=str),
        # Extracts the UUID of the measurement likely consisting of the experiment and
        # a measurement number
        Quantity('UUID', r'#\sUUID\s+([a-zA-Z0-9]+)', repeats=False, dtype=str),
        ## Important measurement quantities for EVERY measurement
        # Extracts the measurement type, e.g. "Hysteresis", "Minor loops", "Raster" etc
        Quantity(
            'Meas. type',
            r'#\sMeas\.\stype\s+([a-zA-Z_\-\.]+)',
            repeats=False,
            dtype=str,
        ),
        # Extracts the profile name during the measurement. Can be any profile txt,
        # which can be altered later or during the measurement. Not very informative.
        Quantity(
            'Profile', r'#\sProfile\s+([a-zA-Z0-9_\-\.]+)', repeats=False, dtype=str
        ),
        # Extracts the sample angle in degrees. Typically 0, sometimes 90 or 45 but can
        # be any angle. Measured according to sputter deposition direction vs plane of
        # incidence in direction of light.
        Quantity(
            'Sample angle',
            r'#\s(?:Sample\s)?angle\s\(deg\)\s+([0-9\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Extracts the device used for the measurement, e.g. "LMOKE" or "VMOKE"
        Quantity('Device', r'#\sDevice\s+([a-zA-Z0-9\s]+)', repeats=False, dtype=str),
        # Extracts the field angle in degrees, relative to the plane of incidence.
        # For LMOKE always 0, for VMOKE mostly 0 and 90.
        Quantity(
            'Field angle',
            r'#\sField\sangle\s\(deg\)\s+([0-9\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Extracts the temperature in Kelvin. Typically room temperature (300 K) as not
        # yet measured.
        Quantity(
            'Temperature',
            r'#\sTemperature\s\(K\)\s+([0-9\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Extracts the calibration file used for the measurement. Typically "default"
        # or "none". Not yet used.
        Quantity(
            'Calibration',
            r'#\sCalibration\s+([a-zA-Z0-9_\-\.]+)',
            repeats=False,
            dtype=str,
        ),
        # Extracts the polarization of the light used for the measurement. Typically
        # "s" for LMOKE and "p" for VMOKE.
        Quantity(
            'Polarization', r'#\sPolarization\s+([spSP]+)', repeats=False, dtype=str
        ),
        # Extracts the starting field in kA/m.
        Quantity(
            'Hstart',
            r'#\s(?:Hmin|Hstart)\s\(kA/m\)\s+([0-9\-\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Extracts the ending field in kA/m (of the first branch). The measurement
        # finally stops at the starting field.
        Quantity(
            'Hend',
            r'#\s(?:Hmax|Hend)\s\(kA/m\)\s+([0-9\-\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Extracts the number of points per branch.
        Quantity('Pts/branch', r'#\spts\./branch\s+([0-9]+)', repeats=False, dtype=int),
        # Extracts the time per point in seconds.
        Quantity(
            'Time/pt', r'#\stime/pt\.\s\(s\)\s+([0-9\.]+)', repeats=False, dtype=float
        ),
        # Extracts the delay time (equilibration tima after a new field) in seconds.
        Quantity(
            'Delay time', r'#\sdt\s\(s\)\s+([0-9\.]+)', repeats=False, dtype=float
        ),
        # Extracts the number of cycles/measurement repetitions.
        Quantity('nCycles', r'#\snCycles\s+([0-9]+)', repeats=False, dtype=int),
        # Extracts the current/last cycle number.
        Quantity('Cycle', r'#\sCycle\s+([0-9]+)', repeats=False, dtype=int),
        # Should only extract the first value of for example 2/3 being Cycle/nCycles
        # TODO: Implement this for all modes (e.q. Raster mode)
        # Extracts everything between Comment and the next "Meas. type" or "----";
        # non-greedy match
        Quantity(
            'Comment',
            r'#\sComment\s+(.*?)(?=\n#\sMeas\.\stype|\n#\s-{4,})',
            repeats=False,
            dtype=str,
            flags=re.DOTALL,
        ),
        ## Optional quantities, depending on the measurement type
        # Extracts the stopping field in kA/m. Only present in FORC and Minor
        # loops measurements.
        Quantity(
            'Hstop', r'#\sHstop\s\(kA/m\)\s+([0-9\-\.]+)', repeats=False, dtype=float
        ),
        # Extracts the wait time between subsequent measurements in seconds. Only
        # present in Scheduled measurements.
        Quantity(
            'Wait time', r'#\swait\s\(s\)\s+([0-9\.]+)', repeats=False, dtype=float
        ),
        # Extracts the number of scheduled measurements. Only present in Scheduled
        # measurements.
        Quantity('nSched', r'#\snSched\s+([0-9]+)', repeats=False, dtype=int),
        # Extracts the number of minor loops. Only present in Minor loops and FORC
        # measurements. TODO: test if this works for FORC measurements
        Quantity(
            'nMinorLoops_nFORCs', r'#\snMinorLoops\s+([0-9]+)', repeats=False, dtype=int
        ),
        # Extracts the number of X raster points. Only present in Raster measurements.
        Quantity('nX', r'#\snX\s+([0-9]+)', repeats=False, dtype=int),
        # Extracts the number of Y raster points. Only present in Raster measurements.
        Quantity('nY', r'#\snY\s+([0-9]+)', repeats=False, dtype=int),
        # Extracts total X raster step size in mm. Only present in Raster measurements.
        Quantity(
            'DeltaX',
            r'#\s(?:DeltaX|dx)\s\(mm\)\s+([0-9\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Extracts total Y raster step size in mm. Only present in Raster measurements.
        Quantity(
            'DeltaY',
            r'#\s(?:DeltaY|dy)\s\(mm\)\s+([0-9\.]+)',
            repeats=False,
            dtype=float,
        ),
        # Exracts the current raster position in X. Only present in Raster measurements.
        Quantity(
            'X',
            r'#\sRaster\s+\(([0-9]+),[0-9]+\)/\([0-9]+,[0-9]+\)',
            repeats=False,
            dtype=str,
        ),
        # Exracts the current raster position in Y. Only present in Raster measurements.
        Quantity(
            'Y',
            r'#\sRaster\s+\([0-9]+,([0-9]+)\)/\([0-9]+,[0-9]+\)',
            repeats=False,
            dtype=str,
        ),
        # Extracts boolean information if a raster scan should be averaged at the end.
        # Only present in Raster measurements.
        Quantity(
            'Avg. raster',
            r'#\savg\.\sraster\s+([a-zA-Z0-9]+)',
            repeats=False,
            dtype=str,
        ),
    ]
)

"""
# This is the experimental data parser for LMOKE and VMOKE measurements.
# The experimental data is extracted using regular expressions
# (The tabular parser did not work).
# The data is then stored in a schema object.
"""
experimental_data_parser = DataTextParser(
    quantities=[
        Quantity(
            'Longitudinal magnetic field',
            r'([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s+[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?',
            repeats=True,
            dtype=float,
        ),
        Quantity(
            'Longitudinal detector signal',
            r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?\s+([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)',
            repeats=True,
            dtype=float,
        ),
    ]
)
