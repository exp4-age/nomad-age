"""Parser for the hysteresis loops of the home-built VSM (LabVIEW VSM_1.0beta),
<measurement no>_VSM_<chip>.asc, e.g. 188225_VSM_2019_0333_1.asc.

Latin-1, decimal comma, header lines padded with tabs. The header is the record
that the VSM program inserts into the lab database, one value per line:

    ####, VSM Messdaten, ####,
    ChargenID, ProbenID, Messzeitpunkt, AnlagenID, Messungen_Datum,
    Hys_HEB_rechts, Hys_HC_rechts, Hys_HEB_links, Hys_HC_links,
    Hys_Kom (0..n lines), Hys_User, Hys_Winkel,
    ####, column titles, ####, data rows (B-Feld [V], Ms-Probe [V], B-Feld [kA/m])

A single-loop fit is written to the left slots; a component whose centre and
half width are both 0 is not fitted.
"""

import os
import re
from datetime import datetime
from typing import Callable, Optional

from nomad.config import config
from nomad.datamodel import EntryArchive
from nomad.parsing import MatchingParser

from nomad_age.schema_packages.age_schema import AGE_RawFile, AGE_Sample_Reference
from nomad_age.schema_packages.vsm_schema import (
    AGE_VSM,
    MIN_PLOT_POINTS,
    VSM_TECHNIQUE,
)
from nomad_age.utils.fingerprint import file_fingerprint
from nomad_age.utils.utils import (
    create_archive,
    find_chip_reference,
    get_entry_id,
    get_hash_ref,
    lab_time_to_utc,
    normalize_sample_id,
    update_entry,
)

configuration = config.get_plugin_entry_point(
    'nomad_age.parsers:vsm_parser_entry_point'
)

FILENAME_RE = re.compile(r'^(\d+)_VSM_(.+)\.asc$', re.IGNORECASE)
SEPARATOR_RE = re.compile(r'^#{5,}\s*$')
COLUMNS_RE = re.compile(r'^B-Feld\s*\[V\]\t')
# 0-based line indices of the fixed header values
FIXED_LINES = {
    'db_charge_id': 3,
    'db_chip_number': 4,
    'sample_state': 5,
    'db_instrument_id': 6,
    'date': 7,
    'centre_right': 8,
    'hc_right': 9,
    'centre_left': 10,
    'hc_left': 11,
}
FIRST_FREE_LINE = 12  # comment lines, then user id and angle


def to_float(text: str) -> float:
    return float(text.strip().replace(',', '.'))


def to_int(text: str) -> int:
    return int(text.strip())


def to_date(text: str) -> datetime:
    return datetime.strptime(text.strip(), '%Y-%m-%d')


def read_value(text: Optional[str], convert: Callable, what: str, logger):
    """`text` converted, None with a warning if it is missing or unparsable."""
    try:
        return convert(text)
    except (AttributeError, ValueError):
        logger.warning(f'VSM header: unparsable {what} {text!r}; not stored.')
        return None


def read_header(lines: list, logger) -> tuple:
    """(header values, index of the column title line or None) of the lines of
    a VSM file, trailing whitespace removed."""
    columns = next(
        (
            i
            for i in range(FIRST_FREE_LINE + 1, len(lines))
            if COLUMNS_RE.match(lines[i]) and SEPARATOR_RE.match(lines[i - 1])
        ),
        None,
    )
    if len(lines) < 2 or 'VSM Messdaten' not in lines[1]:
        logger.warning('VSM file without the "VSM Messdaten" title line.')

    def fixed(key):
        index = FIXED_LINES[key]
        return lines[index] if index < len(lines) else None

    header = {
        'db_charge_id': read_value(fixed('db_charge_id'), to_int, 'ChargenID', logger),
        'db_chip_number': read_value(
            fixed('db_chip_number'), to_int, 'ProbenID', logger
        ),
        'sample_state': (fixed('sample_state') or '').strip() or None,
        'db_instrument_id': read_value(
            fixed('db_instrument_id'), to_int, 'AnlagenID', logger
        ),
        'date': read_value(fixed('date'), to_date, 'Messungen_Datum', logger),
    }
    for key, what in (
        ('centre_right', 'Hys_HEB_rechts'),
        ('hc_right', 'Hys_HC_rechts'),
        ('centre_left', 'Hys_HEB_links'),
        ('hc_left', 'Hys_HC_links'),
    ):
        header[key] = read_value(fixed(key), to_float, what, logger)

    if columns is None:
        logger.warning('VSM file without the column titles; no user, angle or data.')
        return header, None
    free = [line.strip() for line in lines[FIRST_FREE_LINE : columns - 1]]
    if len(free) < 2:
        logger.warning('VSM header without user id and sample angle lines.')
    else:
        header['user_id'] = read_value(free[-2], to_int, 'Hys_User', logger)
        header['sample_angle'] = read_value(free[-1], to_float, 'Hys_Winkel', logger)
        # older program versions write an empty comment as '0'
        comment = '\n'.join(line for line in free[:-2] if line and line != '0')
        header['comment'] = comment or None
    return header, columns


def read_data(lines: list, logger) -> list:
    """Rows (field voltage, signal, field) of the data lines; unparsable rows
    are skipped with one warning."""
    rows, bad = [], 0
    for line in lines:
        if not line.strip() or SEPARATOR_RE.match(line):
            continue
        cells = [cell for cell in line.split('\t') if cell.strip()]
        try:
            if len(cells) != 3:
                raise ValueError
            rows.append(tuple(map(to_float, cells)))
        except ValueError:
            bad += 1
    if bad:
        logger.warning(f'VSM data: skipped {bad} unparsable rows.')
    return rows


def fit_component(centre: Optional[float], hc: Optional[float]) -> dict:
    """loop_shift, HC and HEB = -loop_shift of a fitted loop component; all None
    if it is not fitted (centre and half width both 0)."""
    if centre == 0 and hc == 0:
        return {'loop_shift': None, 'HC': None, 'HEB': None}
    return {
        'loop_shift': centre,
        'HC': hc,
        'HEB': None if centre is None else 0.0 - centre,
    }


def parse_vsm_file(mainfile: str, logger) -> dict:
    """Values of AGE_VSM from a VSM file and its name."""
    with open(mainfile, encoding='latin1') as f:
        lines = [line.rstrip() for line in f.read().splitlines()]
    header, columns = read_header(lines, logger)
    values = {
        key: header.get(key)
        for key in (
            'db_charge_id',
            'db_chip_number',
            'sample_state',
            'db_instrument_id',
            'user_id',
            'sample_angle',
            'comment',
        )
    }
    if header['date'] is not None:
        values['measurement_time'] = lab_time_to_utc(header['date'])
    for side in ('left', 'right'):
        component = fit_component(header[f'centre_{side}'], header[f'hc_{side}'])
        for name, value in component.items():
            values[f'{name}_{side}'] = value

    rows = [] if columns is None else read_data(lines[columns + 1 :], logger)
    if len(rows) < MIN_PLOT_POINTS:
        logger.warning(f'VSM file with only {len(rows)} data rows; no loop plot.')
    if rows:
        field_voltage, signal, field = map(list, zip(*rows))
        values.update(field_voltage=field_voltage, signal=signal, magnetic_field=field)

    match = FILENAME_RE.match(os.path.basename(mainfile))
    if match:
        values['measurement_number'] = int(match.group(1))
        values['sample'] = normalize_sample_id(match.group(2))
    else:
        logger.warning(
            'VSM file name is not <measurement no>_VSM_<chip>.asc; no measurement '
            'number or chip.'
        )
    return {key: value for key, value in values.items() if value is not None}


class VSMParser(MatchingParser):
    def parse(self, mainfile: str, archive: EntryArchive, logger):
        logger.info(
            f'VSMParser called on {mainfile}',
            configuration=configuration.parameter if configuration else None,
        )
        uid = archive.metadata.upload_id
        entry_file_name = f'{os.path.basename(mainfile)}.archive.yaml'
        eid = get_entry_id(uid, entry_file_name)
        entry = AGE_VSM(technique=VSM_TECHNIQUE, **parse_vsm_file(mainfile, logger))
        parts = ['VSM', entry.measurement_number, entry.sample, entry.sample_state]
        entry.name = ' '.join(str(p) for p in parts if p is not None)

        # Chips live in the AGE Samples upload: link them, never create them.
        if entry.sample:
            entry.samples.append(
                AGE_Sample_Reference(
                    name=entry.sample,
                    lab_id=entry.sample,
                    reference=find_chip_reference(entry.sample, archive, logger),
                )
            )

        rel_mainfile = archive.metadata.mainfile or os.path.basename(mainfile)
        archive.data = AGE_RawFile(
            file_name=rel_mainfile,
            file_type='VSM measurement',
            processed_archive=get_hash_ref(uid, entry_file_name),
            **file_fingerprint(mainfile),
        )
        entry.raw_file = get_hash_ref(uid, rel_mainfile)
        if not create_archive(entry, archive, entry_file_name):
            # The chip comes from the file name; the plot from the data on
            # processing, so a stored one must not survive the merge.
            new_entry = update_entry(
                entry,
                eid,
                archive,
                logger,
                parsed_wins=('samples',),
                parser_owned=('figures',),
            )
            if new_entry is not None:
                create_archive(new_entry, archive, entry_file_name, overwrite=True)
