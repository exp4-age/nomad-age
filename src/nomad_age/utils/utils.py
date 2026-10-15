import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nomad.datamodel.data import ArchiveSection
from nomad.utils import hash

# Lab software (camera, field cooling) writes wall-clock times without a zone.
LAB_TIMEZONE = ZoneInfo('Europe/Berlin')


def get_reference(upload_id, entry_id):
    return f'../uploads/{upload_id}/archive/{entry_id}'


def get_entry_id(upload_id, filename):
    return hash(upload_id, filename)


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


def create_archive(entity, archive, file_name, *, overwrite: bool = False):
    import json

    import yaml

    if not archive.m_context.raw_path_exists(file_name) or overwrite:
        entity_entry = entity.m_to_dict(with_root_def=True)
        with archive.m_context.raw_file(file_name, 'w') as outfile:
            if file_name.endswith('.yaml'):
                yaml.dump({'data': entity_entry}, outfile)
            elif file_name.endswith('.json'):
                json.dump({'data': entity_entry}, outfile)
        archive.m_context.process_updated_raw_file(file_name, allow_modify=overwrite)
        return True
    return False


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


def merge_stored_values(fresh: dict, stored, editable: set) -> dict:
    """The fresh parse plus the stored values that users may have changed.

    Stored values win for editable keys and for keys the parser does not set;
    parsed values such as numbers, figures and file links come from `fresh`.
    """
    merged = dict(fresh)
    for key, value in stored.items():
        if key in editable or key not in merged:
            merged[key] = value
    return merged


def update_entry(entry, eid, archive, logger):
    """`entry` merged with the stored entry `eid`, see merge_stored_values."""
    from nomad import files
    from nomad.search import search

    query = {
        'entry_id': eid,
    }
    search_result = search(
        owner='all', query=query, user_id=archive.metadata.main_author.user_id
    )
    new_entry_dict = entry.m_to_dict()
    res = search_result.data[0]
    try:
        # Open Archives
        with files.UploadFiles.get(upload_id=res['upload_id']).read_archive(
            entry_id=res['entry_id']
        ) as ar:
            entry_id = res['entry_id']
            entry_data = ar[entry_id]['data']
            entry_data.pop('m_def', None)
            new_entry_dict = merge_stored_values(
                new_entry_dict, entry_data, user_editable_keys(type(entry).m_def)
            )
    except Exception as e:
        logger.error('Error in processing data: ', e)
    return type(entry).m_from_dict(new_entry_dict)


def find_existing_AGE_sample(lab_id: str, user_id=None):
    """Searches all entries in the database for matching lab_id."""
    from nomad.search import search

    query = {'results.eln.lab_ids': lab_id}
    search_result = search(query=query, owner='visible', user_id=user_id)
    return search_result


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
