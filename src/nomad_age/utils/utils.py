import math

from nomad.app.v1.models.models import MetadataResponse
from nomad.search import search
from nomad.utils import hash


def get_reference(upload_id, entry_id):
    return f'../uploads/{upload_id}/archive/{entry_id}'


def get_entry_id(upload_id, filename):
    return hash(upload_id, filename)


def get_hash_ref(upload_id, filename):
    return f'{get_reference(upload_id, get_entry_id(upload_id, filename))}#data'


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


def find_existing_AGE_sample(lab_id: str) -> MetadataResponse:
    """Searches all entries in the database for matching lab_id."""
    query = {'results.eln.lab_ids': lab_id}
    search_result = search(query=query, owner='visible')
    return search_result
