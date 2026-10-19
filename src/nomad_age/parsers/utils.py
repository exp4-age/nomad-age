import math


def get_reference(upload_id, entry_id):
    return f'../uploads/{upload_id}/archive/{entry_id}'


def get_entry_id(upload_id, filename):
    from nomad.utils import hash

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


def create_archive(
    entry_dict, context, filename, file_type, logger, *, overwrite: bool = False
):
    """Write `entry_dict` as `file_type` ('json' or 'yaml') file `filename` and
    process it; an existing file only with `overwrite` and only if its content
    changes, as NOMAD processes the file again on every write."""
    from nomad.datamodel.context import ClientContext

    from nomad_age.utils.utils import (
        archive_file_holds,
        dump_archive,
        write_archive_file,
    )

    if isinstance(context, ClientContext):
        return None
    text = dump_archive(entry_dict, file_type)
    if context.raw_path_exists(filename):
        if archive_file_holds(context, filename, entry_dict, text, file_type):
            return get_hash_ref(context.upload_id, filename)
        if not overwrite:
            logger.error(
                f'{filename} archive file already exists. '
                f'You are trying to overwrite it with a different content. '
                f'To do so, remove the existing archive and click reprocess again.'
            )
            return get_hash_ref(context.upload_id, filename)
    write_archive_file(context, filename, entry_dict, text, file_type)
    context.upload.process_updated_raw_file(filename, allow_modify=True)
    return get_hash_ref(context.upload_id, filename)
