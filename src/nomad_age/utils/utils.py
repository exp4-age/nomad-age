import json
import math
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import yaml
from nomad.datamodel.data import ArchiveSection
from nomad.utils import hash

# libyaml is much faster than pure Python on large entries; NOMAD reads the files
# with a safe loader, so write them with a safe dumper.
YAML_LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
YAML_DUMPER = getattr(yaml, 'CSafeDumper', yaml.SafeDumper)

# Lab software (camera, field cooling) writes wall-clock times without a zone.
LAB_TIMEZONE = ZoneInfo('Europe/Berlin')

# Chips: one central upload holds all AGE_Sample entries; parsers only link them.
AGE_SAMPLE_SCHEMA = 'nomad_age.schema_packages.age_schema.AGE_Sample'
# A chip in one coated state; it references its chip (AGE_Sample).
AGE_COATED_SAMPLE_SCHEMA = 'nomad_age.schema_packages.age_schema.AGE_CoatedSample'
# A particle batch (Inventory); measurements link it under particle_batches.
AGE_PARTICLES_SCHEMA = 'nomad_age.schema_packages.age_schema.AGE_Particles'
# A chip has far fewer coated states (spacer layers) than this.
MAX_COATED_SAMPLES = 1000
# Base section of all magnetisation measurements (L-MOKE, V-MOKE, ...); NOMAD indexes
# the base sections of an entry's data, so one filter finds every technique.
AGE_MAGNETISATION_SCHEMA = (
    'nomad_age.schema_packages.age_schema.AGE_MagnetisationMeasurement'
)
# A chip shows its newest measurement; it has far fewer than this many.
MAX_MAGNETISATION_MEASUREMENTS = 1000
# A sputter run <year>_<number>; its samples are <run>_1, <run>_2, ...
SPUTTER_RUN_RE = re.compile(r'\d{4}_\d{4}')
# A reference to an entry of an upload, as get_reference writes it.
REFERENCE_RE = re.compile(
    r'\.\./uploads/(?P<upload_id>[^/]+)/archive/(?P<entry>[^/#]+)'
)


def get_reference(upload_id, entry_id):
    return f'../uploads/{upload_id}/archive/{entry_id}'


def get_entry_id(upload_id, filename):
    return hash(upload_id, filename)


def parse_reference(reference) -> Optional[tuple]:
    """(upload id, entry id) of a reference to an entry such as get_reference
    writes it, given as text or as unresolved reference value; None otherwise."""
    url = reference if isinstance(reference, str) else None
    if url is None:
        url = getattr(reference, 'm_proxy_value', None)
    match = REFERENCE_RE.match(url) if isinstance(url, str) else None
    return (match['upload_id'], match['entry']) if match else None


def as_utc(value) -> Optional[datetime]:
    """A datetime or ISO text as timezone aware datetime; naive times are UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def get_hash_ref(upload_id, filename):
    return f'{get_reference(upload_id, get_entry_id(upload_id, filename))}#data'


def lab_time_to_utc(local_time: datetime) -> datetime:
    """UTC time of a naive wall-clock time written by lab software in Kassel."""
    return local_time.replace(tzinfo=LAB_TIMEZONE).astimezone(timezone.utc)


def nan_equal(a, b):
    """
    Compare two values with NaN values.
    """
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    elif isinstance(a, dict) and isinstance(b, dict):
        return dict_nan_equal(a, b)
    elif isinstance(a, list) and isinstance(b, list):
        return list_nan_equal(a, b)
    else:
        return a == b


def list_nan_equal(list1, list2):
    """
    Compare two lists with NaN values.
    """
    if len(list1) != len(list2):
        return False
    for a, b in zip(list1, list2):
        if not nan_equal(a, b):
            return False
    return True


def dict_nan_equal(dict1, dict2):
    """
    Compare two dictionaries with NaN values.
    """
    if set(dict1.keys()) != set(dict2.keys()):
        return False
    for key in dict1:
        if not nan_equal(dict1[key], dict2[key]):
            return False
    return True


def dump_archive(data, file_type: str) -> Optional[str]:
    """`data` as JSON (file_type 'json') or YAML text; None if JSON or safe YAML
    cannot represent it."""
    try:
        if file_type == 'json':
            return json.dumps(data)
        return yaml.dump(data, Dumper=YAML_DUMPER)
    except (TypeError, ValueError, yaml.YAMLError):
        return None


def load_archive(text: str, file_type: str):
    if file_type == 'json':
        return json.loads(text)
    return yaml.load(text, Loader=YAML_LOADER)


def archive_file_holds(context, file_name: str, data, text, file_type: str) -> bool:
    """Whether the existing raw file `file_name` holds `data`; `text` is
    dump_archive(data, file_type).

    Compared after a round trip through `text`, so that e.g. tuples equal lists
    and NaN equals NaN.
    """
    with context.raw_file(file_name, 'r') as f:
        stored_text = f.read()
    if stored_text == text:
        return True
    try:
        stored = load_archive(stored_text, file_type)
        new = data if text is None else load_archive(text, file_type)
    except (ValueError, yaml.YAMLError):
        return False
    return nan_equal(stored, new)


def write_archive_file(context, file_name: str, data, text, file_type: str) -> None:
    """Write `data` with its dump_archive `text`; without text (types that safe
    YAML cannot represent) as before, with the full YAML dumper."""
    with context.raw_file(file_name, 'w') as f:
        if text is not None:
            f.write(text)
        elif file_type == 'json':
            json.dump(data, f)
        else:
            yaml.dump(data, f)


def create_archive(entity, archive, file_name, *, overwrite: bool = False) -> bool:
    """Write `entity` as entry file `file_name` and process it; an existing file
    only with `overwrite` and only if its content changes, as NOMAD processes the
    file again on every write. True if the file was written."""
    context = archive.m_context
    exists = context.raw_path_exists(file_name)
    if exists and not overwrite:
        return False
    data = {'data': entity.m_to_dict(with_root_def=True)}
    file_type = 'json' if file_name.endswith('.json') else 'yaml'
    text = dump_archive(data, file_type)
    if exists and archive_file_holds(context, file_name, data, text, file_type):
        return False
    write_archive_file(context, file_name, data, text, file_type)
    context.process_updated_raw_file(file_name, allow_modify=overwrite)
    return True


def user_editable_keys(section_def) -> set:
    """Quantities and subsections of a section that users edit in the GUI.

    A quantity counts if it has an ELN component and the section's ELN
    properties do not exclude it from editing; a subsection counts if any of its
    quantities has an ELN component (e.g. samples, but not figures).
    """

    def has_component(quantity):
        return getattr(quantity.m_annotations.get('eln'), 'component', None) is not None

    properties = getattr(section_def.m_annotations.get('eln'), 'properties', None)
    editable = getattr(properties, 'editable', None)
    included = getattr(editable, 'include', None)
    excluded = getattr(editable, 'exclude', None) or []
    keys = {
        name
        for name, quantity in section_def.all_quantities.items()
        if has_component(quantity)
        and name not in excluded
        and (not included or name in included)
    }
    keys.update(
        name
        for name, sub_section in section_def.all_sub_sections.items()
        if any(map(has_component, sub_section.sub_section.all_quantities.values()))
    )
    return keys


def merge_stored_values(fresh: dict, stored, editable: set, parser_owned=()) -> dict:
    """The fresh parse plus the stored values that users may have changed.

    Stored values win for editable keys and for keys the parser does not set,
    except for the keys in `parser_owned`, which only the parse sets; parsed
    values such as numbers, figures and file links come from `fresh`.
    """
    merged = dict(fresh)
    for key, value in stored.items():
        if key in parser_owned:
            continue
        if key in editable or key not in merged:
            merged[key] = value
    return merged


def update_entry(entry, eid, archive, logger, parsed_wins=(), parser_owned=()):
    """`entry` merged with the stored entry `eid` of the same upload, see
    merge_stored_values; for the keys in `parsed_wins` the parsed value wins even
    if users may edit it. Stored keys that the schema no longer defines are
    dropped.

    The stored archive is read directly, not via the search index: NOMAD 1.4.3
    parses each file of a new upload twice, and on the second run the entry
    written by the first one is often not searchable yet.
    """
    from nomad import files

    new_entry_dict = entry.m_to_dict()
    try:
        upload_files = files.UploadFiles.get(upload_id=archive.metadata.upload_id)
        with upload_files.read_archive(entry_id=eid) as ar:
            entry_data = ar[eid]['data']
            entry_data.pop('m_def', None)
            editable = user_editable_keys(type(entry).m_def) - set(parsed_wins)
            merged = merge_stored_values(
                new_entry_dict, entry_data, editable, parser_owned
            )
            defined = type(entry).m_def.all_properties
            new_entry_dict = {k: v for k, v in merged.items() if k in defined}
    except Exception as e:
        logger.error(f'Stored entry {eid} could not be merged: {e!r}')
    return type(entry).m_from_dict(new_entry_dict)


def normalize_sample_id(lab_id: str) -> str:
    """The lab id of a chip: a bare sputter run such as 2023_0418 means its first
    sample 2023_0418_1; ids with suffixes and other lab ids stay as they are."""
    lab_id = lab_id.strip()
    return f'{lab_id}_1' if SPUTTER_RUN_RE.fullmatch(lab_id) else lab_id


def find_by_lab_id(lab_id: str, schema: str, user_id=None):
    """Entries of section definition `schema` with `lab_id` that the user with
    `user_id` sees (own, shared or published; without user id only published
    ones)."""
    from nomad.search import search

    query = {
        'results.eln.lab_ids': lab_id,
        'section_defs.definition_qualified_name': schema,
    }
    return search(query=query, owner='visible', user_id=user_id)


def find_existing_AGE_sample(lab_id: str, user_id=None):
    """AGE_Sample entries with `lab_id`, see find_by_lab_id."""
    return find_by_lab_id(lab_id, AGE_SAMPLE_SCHEMA, user_id)


def find_existing_particles(lab_id: str, user_id=None):
    """AGE_Particles entries with `lab_id`, see find_by_lab_id."""
    return find_by_lab_id(lab_id, AGE_PARTICLES_SCHEMA, user_id)


def main_author_id(archive) -> Optional[str]:
    """User id of the main author of `archive`; None if it has none."""
    metadata = getattr(archive, 'metadata', None)
    main_author = metadata.main_author if metadata is not None else None
    return main_author.user_id if main_author else None


def find_chip_reference(lab_id: str, archive, logger) -> Optional[str]:
    """Reference to the data of the chip (AGE_Sample) with the normalized `lab_id`
    in any upload the main author of `archive` sees; None if there is no such
    chip or more than one. Parsers never create chips: they live in the AGE
    Samples upload."""
    lab_id = normalize_sample_id(lab_id)
    hits = find_existing_AGE_sample(lab_id, user_id=main_author_id(archive)).data
    if not hits:
        logger.warning(
            f'No AGE sample with lab_id {lab_id} found; not linked. Create the chip '
            'in the AGE Samples upload, then reprocess this entry.'
        )
        return None
    if len(hits) > 1:
        logger.error(f'Found {len(hits)} AGE samples with lab_id {lab_id}; not linked.')
        return None
    return f'{get_reference(hits[0]["upload_id"], hits[0]["entry_id"])}#data'


def find_particles(lab_id: str, archive) -> list:
    """References to the data of the particle batches (AGE_Particles) with
    `lab_id` in any upload the main author of `archive` sees."""
    hits = find_existing_particles(lab_id.strip(), user_id=main_author_id(archive))
    return [f'{get_reference(h["upload_id"], h["entry_id"])}#data' for h in hits.data]


def find_particles_reference(lab_id: str, archive, logger) -> Optional[str]:
    """Reference to the data of the particle batch (AGE_Particles) with `lab_id`,
    see find_particles; None if there is no such batch or more than one.
    Parsers never create particle batches: they live in the AGE Inventory."""
    references = find_particles(lab_id, archive)
    if not references:
        logger.warning(
            f'No particle batch (Particles entry) with lab_id {lab_id} found; not '
            'linked. Create it in the AGE Inventory, then reprocess this entry.'
        )
        return None
    if len(references) > 1:
        logger.error(
            f'Found {len(references)} particle batches with lab_id {lab_id}; not '
            'linked.'
        )
        return None
    return references[0]


def is_chip_lab_id(lab_id: str) -> bool:
    """Whether a lab id names a chip or coated chip: these start with their
    sputter run, e.g. 2023_0418_1 or 2023_0418_1_PMMA5."""
    return bool(re.match(rf'{SPUTTER_RUN_RE.pattern}(?!\d)', lab_id.strip()))


def find_coated_samples(chip_entry_id: str, user_id=None) -> list:
    """(upload id, entry id) of the coated chips (AGE_CoatedSample) that reference
    the chip entry `chip_entry_id` and that the user with `user_id` sees, in any
    upload."""
    from nomad.search import MetadataPagination, MetadataRequired, search

    results = search(
        owner='visible',
        user_id=user_id,
        query={
            'entry_references.target_entry_id': chip_entry_id,
            'section_defs.definition_qualified_name': AGE_COATED_SAMPLE_SCHEMA,
        },
        required=MetadataRequired(include=['entry_id', 'upload_id']),
        pagination=MetadataPagination(page_size=MAX_COATED_SAMPLES),
    )
    return [(hit['upload_id'], hit['entry_id']) for hit in results.data]


def get_referencing_entries(archive: ArchiveSection) -> list:
    """
    Find all entries in the archive that reference the given archive.
    """
    from nomad.search import search

    query = {
        'entry_references.target_entry_id:all': [archive.m_parent.entry_id],
    }
    results = search(
        query=query,
        owner='visible',
        # user_id=archive.metadata.main_author.user_id,
    )
    entry_list = results.data

    return entry_list


def _magnetisation_summary(hit: dict) -> dict:
    """entry_id, upload_id, measurement_time and technique of a search hit of a
    magnetisation measurement; the data quantities come from its search quantities,
    which NOMAD indexes with the definitions of the base section."""
    values = {}
    for quantity in hit.get('search_quantities') or []:
        definition = quantity.get('definition') or ''
        if definition.startswith(f'{AGE_MAGNETISATION_SCHEMA}.'):
            name = definition[len(AGE_MAGNETISATION_SCHEMA) + 1 :]
            values[name] = quantity.get('datetime_value', quantity.get('str_value'))
    return {
        'entry_id': hit['entry_id'],
        'upload_id': hit['upload_id'],
        'measurement_time': as_utc(values.get('measurement_time')),
        'technique': values.get('technique'),
    }


def find_magnetisation_measurements(chip_entry_id: str, user_id=None) -> list:
    """The magnetisation measurements that reference the chip entry `chip_entry_id`
    and that the user with `user_id` sees, as _magnetisation_summary dicts."""
    from nomad.search import MetadataPagination, MetadataRequired, search

    results = search(
        owner='visible',
        user_id=user_id,
        query={
            'entry_references.target_entry_id': chip_entry_id,
            'section_defs.definition_qualified_name': AGE_MAGNETISATION_SCHEMA,
        },
        # a wildcard returns the indexed data quantities; NOMAD validates only
        # include patterns without one
        required=MetadataRequired(
            include=['entry_id', 'upload_id', 'search_quantities*']
        ),
        pagination=MetadataPagination(page_size=MAX_MAGNETISATION_MEASUREMENTS),
    )
    return [_magnetisation_summary(hit) for hit in results.data]


def newest_magnetisation_measurement(chip_entry_id: str, user_id=None):
    """The newest (by measurement_time, then entry id) magnetisation measurement of
    the chip entry, see find_magnetisation_measurements; None if it has none with a
    measurement time."""
    measurements = [
        m
        for m in find_magnetisation_measurements(chip_entry_id, user_id)
        if m['measurement_time'] is not None
    ]
    if not measurements:
        return None
    return max(measurements, key=lambda m: (m['measurement_time'], m['entry_id']))
