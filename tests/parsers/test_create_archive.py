import json
from unittest import mock

import numpy as np
import pytest
import yaml
from nomad.datamodel.context import ClientContext

from nomad_age.parsers.utils import create_archive
from nomad_age.parsers.utils import get_hash_ref as parsers_get_hash_ref
from nomad_age.schema_packages.age_schema import AGE_Sample
from nomad_age.utils import utils

ENTRY = {'data': {'name': 'S1', 'values': [1.0, 2.5], 'nested': {'a': [1, 2]}}}


class FakeContext:
    """Server-like context on a directory; records the files processed again."""

    def __init__(self, directory):
        self.directory = directory
        self.upload_id = 'test_upload'
        self.upload = mock.Mock()

    def raw_path_exists(self, path):
        return (self.directory / path).exists()

    def raw_file(self, path, mode='r'):
        return open(self.directory / path, mode)

    def process_updated_raw_file(self, path, allow_modify=False):
        self.upload.process_updated_raw_file(path, allow_modify)


def store(context, filename, data, file_type):
    """Write `data` formatted unlike create_archive, to see whether it rewrites."""
    with context.raw_file(filename, 'w') as f:
        if file_type == 'json':
            json.dump(data, f, indent=2)
        else:
            yaml.dump(data, f, default_flow_style=True)
    return (context.directory / filename).read_text()


def load(context, filename, file_type):
    with context.raw_file(filename) as f:
        return json.load(f) if file_type == 'json' else yaml.safe_load(f)


@pytest.fixture(params=['json', 'yaml'])
def file_type(request):
    return request.param


@pytest.fixture
def context(tmp_path):
    return FakeContext(tmp_path)


def test_missing_file_is_written_and_processed(context, file_type):
    filename = f'entry.archive.{file_type}'
    logger = mock.Mock()

    ref = create_archive(ENTRY, context, filename, file_type, logger)

    assert ref == parsers_get_hash_ref('test_upload', filename)
    assert load(context, filename, file_type) == ENTRY
    context.upload.process_updated_raw_file.assert_called_once_with(
        filename, allow_modify=True
    )
    logger.error.assert_not_called()


@pytest.mark.parametrize('overwrite', [False, True])
@pytest.mark.parametrize(
    'entry, stored',
    [
        pytest.param(ENTRY, ENTRY, id='same'),
        pytest.param(
            {'data': {'x': float('nan'), 'y': [float('nan'), 1.0]}},
            {'data': {'x': float('nan'), 'y': [float('nan'), 1.0]}},
            id='nan',
        ),
        pytest.param(
            {'data': {'shape': (2, 3), 'pairs': [(1, 'a')]}},
            {'data': {'shape': [2, 3], 'pairs': [[1, 'a']]}},
            id='tuple-vs-list',
        ),
        pytest.param(
            {'data': {'t': np.float64(1.5), 'n': np.int64(3)}},
            {'data': {'t': 1.5, 'n': 3}},
            id='numpy-scalars',
        ),
    ],
)
def test_unchanged_file_is_neither_written_nor_processed(
    context, file_type, entry, stored, overwrite
):
    filename = f'entry.archive.{file_type}'
    stored_text = store(context, filename, stored, file_type)
    logger = mock.Mock()

    ref = create_archive(
        entry, context, filename, file_type, logger, overwrite=overwrite
    )

    assert ref == parsers_get_hash_ref('test_upload', filename)
    assert (context.directory / filename).read_text() == stored_text
    context.upload.process_updated_raw_file.assert_not_called()
    logger.error.assert_not_called()


def test_changed_file_is_overwritten_and_processed(context, file_type):
    filename = f'entry.archive.{file_type}'
    store(context, filename, {'data': {'name': 'old'}}, file_type)
    logger = mock.Mock()

    create_archive(ENTRY, context, filename, file_type, logger, overwrite=True)

    assert load(context, filename, file_type) == ENTRY
    context.upload.process_updated_raw_file.assert_called_once_with(
        filename, allow_modify=True
    )
    logger.error.assert_not_called()


def test_changed_file_without_overwrite_is_kept_and_logged(context, file_type):
    filename = f'entry.archive.{file_type}'
    stored_text = store(context, filename, {'data': {'name': 'old'}}, file_type)
    logger = mock.Mock()

    ref = create_archive(ENTRY, context, filename, file_type, logger)

    assert ref == parsers_get_hash_ref('test_upload', filename)
    assert (context.directory / filename).read_text() == stored_text
    context.upload.process_updated_raw_file.assert_not_called()
    logger.error.assert_called_once()


def test_nan_differs_from_number(context, file_type):
    filename = f'entry.archive.{file_type}'
    store(context, filename, {'data': {'x': float('nan')}}, file_type)

    create_archive(
        {'data': {'x': 1.0}}, context, filename, file_type, mock.Mock(), overwrite=True
    )

    assert load(context, filename, file_type) == {'data': {'x': 1.0}}
    context.upload.process_updated_raw_file.assert_called_once()


def test_client_context_writes_nothing(tmp_path):
    context = ClientContext(local_dir=str(tmp_path))

    assert create_archive(ENTRY, context, 'e.archive.yaml', 'yaml', mock.Mock()) is None
    assert not (tmp_path / 'e.archive.yaml').exists()


def entry_archive(context):
    return mock.Mock(m_context=context)


def test_entry_file_is_written_and_processed_only_when_it_changes(context):
    archive = entry_archive(context)
    process = context.upload.process_updated_raw_file
    filename = 'S1.archive.yaml'

    assert utils.create_archive(AGE_Sample(name='S1', lab_id='S1'), archive, filename)
    process.assert_called_once_with(filename, False)
    written = (context.directory / filename).read_text()

    process.reset_mock()
    sample = AGE_Sample(name='S1', lab_id='S1')
    assert not utils.create_archive(sample, archive, filename)
    assert not utils.create_archive(sample, archive, filename, overwrite=True)
    process.assert_not_called()
    assert (context.directory / filename).read_text() == written

    changed = AGE_Sample(name='S1 renamed', lab_id='S1')
    assert utils.create_archive(changed, archive, filename, overwrite=True)
    process.assert_called_once_with(filename, True)
    assert load(context, filename, 'yaml')['data']['name'] == 'S1 renamed'


def test_entry_file_written_by_pure_python_dumper_counts_as_unchanged(context):
    """Files written before the switch to libyaml are not rewritten."""
    sample = AGE_Sample(name='S1', lab_id='S1')
    filename = 'S1.archive.yaml'
    with context.raw_file(filename, 'w') as f:
        yaml.dump({'data': sample.m_to_dict(with_root_def=True)}, f)

    assert not utils.create_archive(
        sample, entry_archive(context), filename, overwrite=True
    )
    context.upload.process_updated_raw_file.assert_not_called()


def test_entry_json_file_is_compared_as_json(context):
    sample = AGE_Sample(name='S1', lab_id='S1')
    filename = 'S1.archive.json'
    store(context, filename, {'data': sample.m_to_dict(with_root_def=True)}, 'json')

    assert not utils.create_archive(
        sample, entry_archive(context), filename, overwrite=True
    )
    context.upload.process_updated_raw_file.assert_not_called()
