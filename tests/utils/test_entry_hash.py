import builtins
import contextlib
import hashlib
import os
import sys
import types

import pytest
from nomad import utils
from nomad.config.models.plugins import (
    NormalizerEntryPoint,
    ParserEntryPoint,
    SchemaPackageEntryPoint,
)

import nomad_age.normalizers
import nomad_age.parsers
import nomad_age.schema_packages
from nomad_age.utils import entry_hash


class _RawDir:
    def __init__(self, os_path):
        self.os_path = os_path

    def join_file(self, path):
        return types.SimpleNamespace(os_path=os.path.join(self.os_path, path))


class _NomadStagingUploadFiles:
    """
    The parts of nomad.files.StagingUploadFiles (nomad-lab 1.3.13) used by
    entry_hash. The devcontainer's nomad-lab lacks the infrastructure extras that
    nomad.files needs (e.g. zipstream).
    """

    def __init__(self, raw_os_path):
        self._raw_dir = _RawDir(raw_os_path)

    def entry_files(self, mainfile):
        mainfile_os_path = self._raw_dir.join_file(mainfile).os_path
        if not os.path.exists(mainfile_os_path):
            raise KeyError(mainfile)
        entry_dir = os.path.dirname(mainfile_os_path)
        entry_relative_dir = entry_dir[len(self._raw_dir.os_path) + 1 :]
        aux_files = [
            os.path.join(entry_relative_dir, name)
            for name in sorted(os.listdir(entry_dir))
            if name != os.path.basename(mainfile)
            and os.path.isfile(os.path.join(entry_dir, name))
        ]
        return [mainfile] + sorted(aux_files)

    def entry_hash(self, mainfile, mainfile_key):
        hash = hashlib.sha512()
        for filepath in self.entry_files(mainfile):
            with open(self._raw_dir.join_file(filepath).os_path, 'rb') as f:
                for data in iter(lambda: f.read(65536), b''):
                    hash.update(data)
        if mainfile_key:
            hash.update(mainfile_key.encode('utf8'))
        return utils.make_websave(hash)


NOMAD_ENTRY_HASH = _NomadStagingUploadFiles.entry_hash

ENTRY_POINTS = [
    entry_point
    for module in (
        nomad_age.parsers,
        nomad_age.schema_packages,
        nomad_age.normalizers,
    )
    for entry_point in vars(module).values()
    if isinstance(
        entry_point, (ParserEntryPoint, SchemaPackageEntryPoint, NormalizerEntryPoint)
    )
]


@pytest.fixture
def staging_cls(monkeypatch):
    """A fresh StagingUploadFiles class served as nomad.files for each test."""
    cls = type('StagingUploadFiles', (_NomadStagingUploadFiles,), {})
    monkeypatch.setitem(
        sys.modules, 'nomad.files', types.SimpleNamespace(StagingUploadFiles=cls)
    )
    monkeypatch.delenv(entry_hash.ENV_VAR, raising=False)
    yield cls
    entry_hash.uninstall()
    assert cls.entry_hash is NOMAD_ENTRY_HASH


@pytest.fixture
def upload(tmp_path, staging_cls):
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'data').mkdir()
    (raw / 'data' / 'sample_LMOKE.txt').write_bytes(b'# Meas. type LMOKE\n1 2\n')
    (raw / 'data' / 'video.h5').write_bytes(b'v' * 1000)
    (raw / 'data' / 'video_trajs.h5').write_bytes(b't' * 100)
    (raw / 'other.txt').write_bytes(b'not in the entry directory')
    assert entry_hash.install()
    return staging_cls(str(raw))


MAINFILE = 'data/sample_LMOKE.txt'


def test_mainfile_content_changes_hash(upload):
    before = upload.entry_hash(MAINFILE, None)
    mainfile = os.path.join(upload._raw_dir.os_path, MAINFILE)
    with open(mainfile, 'ab') as f:
        f.write(b'3 4\n')
    assert upload.entry_hash(MAINFILE, None) != before


def test_missing_mainfile_raises_key_error(upload):
    with pytest.raises(KeyError):
        upload.entry_hash('data/missing.txt', None)


def test_aux_size_changes_hash(upload):
    video = os.path.join(upload._raw_dir.os_path, 'data', 'video.h5')
    stat = os.stat(video)
    before = upload.entry_hash(MAINFILE, None)
    with open(video, 'ab') as f:
        f.write(b'v')
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert upload.entry_hash(MAINFILE, None) != before


def test_aux_mtime_changes_hash(upload):
    video = os.path.join(upload._raw_dir.os_path, 'data', 'video.h5')
    stat = os.stat(video)
    before = upload.entry_hash(MAINFILE, None)
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
    assert upload.entry_hash(MAINFILE, None) != before


def test_aux_content_with_same_size_and_mtime_keeps_hash(upload):
    video = os.path.join(upload._raw_dir.os_path, 'data', 'video.h5')
    stat = os.stat(video)
    before = upload.entry_hash(MAINFILE, None)
    with open(video, 'wb') as f:
        f.write(b'w' * stat.st_size)
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert upload.entry_hash(MAINFILE, None) == before


def test_aux_file_added_or_removed_changes_hash(upload):
    entry_dir = os.path.join(upload._raw_dir.os_path, 'data')
    before = upload.entry_hash(MAINFILE, None)

    with open(os.path.join(entry_dir, 'notes.txt'), 'wb'):
        pass
    added = upload.entry_hash(MAINFILE, None)
    assert added != before

    os.remove(os.path.join(entry_dir, 'notes.txt'))
    assert upload.entry_hash(MAINFILE, None) == before

    os.remove(os.path.join(entry_dir, 'video_trajs.h5'))
    assert upload.entry_hash(MAINFILE, None) not in (before, added)


def test_aux_file_rename_changes_hash(upload):
    entry_dir = os.path.join(upload._raw_dir.os_path, 'data')
    before = upload.entry_hash(MAINFILE, None)
    os.rename(os.path.join(entry_dir, 'video.h5'), os.path.join(entry_dir, 'video2.h5'))
    assert upload.entry_hash(MAINFILE, None) != before


def test_only_mainfile_is_opened(upload, monkeypatch):
    opened = []
    real_open = builtins.open

    def spy_open(file, *args, **kwargs):
        opened.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', spy_open)
    upload.entry_hash(MAINFILE, None)
    assert opened == [os.path.join(upload._raw_dir.os_path, MAINFILE)]


def test_mainfile_key_changes_hash(upload):
    assert upload.entry_hash(MAINFILE, 'a') != upload.entry_hash(MAINFILE, None)
    assert upload.entry_hash(MAINFILE, 'a') != upload.entry_hash(MAINFILE, 'b')


def test_without_aux_files_hash_equals_nomad_hash(upload):
    mainfile = 'single/only.txt'
    os.makedirs(os.path.join(upload._raw_dir.os_path, 'single'))
    with open(os.path.join(upload._raw_dir.os_path, mainfile), 'wb') as f:
        f.write(b'x' * 200000)
    for key in (None, 'key'):
        assert upload.entry_hash(mainfile, key) == NOMAD_ENTRY_HASH(
            upload, mainfile, key
        )
    assert upload.entry_hash(MAINFILE, None) != NOMAD_ENTRY_HASH(upload, MAINFILE, None)


def test_install_is_idempotent(staging_cls):
    assert entry_hash.install()
    assert entry_hash.install()
    assert staging_cls.entry_hash is entry_hash.cheap_entry_hash
    assert staging_cls._nomad_age_original_entry_hash is NOMAD_ENTRY_HASH
    entry_hash.uninstall()
    assert staging_cls.entry_hash is NOMAD_ENTRY_HASH


def test_env_var_disables_patch(staging_cls, monkeypatch):
    monkeypatch.setenv(entry_hash.ENV_VAR, '1')
    assert not entry_hash.install()
    assert staging_cls.entry_hash is NOMAD_ENTRY_HASH
    assert '_nomad_age_original_entry_hash' not in vars(staging_cls)


def test_install_defers_until_nomad_files_is_imported(staging_cls, monkeypatch):
    files = sys.modules['nomad.files']
    package = types.ModuleType('nomad')
    with monkeypatch.context() as m:
        m.setitem(sys.modules, 'nomad', package)
        m.delitem(sys.modules, 'nomad.files')
        assert not entry_hash.install()
        assert not entry_hash.install()
        assert staging_cls.entry_hash is NOMAD_ENTRY_HASH

        # What the import system does once nomad.files is executed.
        m.setitem(sys.modules, 'nomad.files', files)
        package.files = files
        assert staging_cls.entry_hash is entry_hash.cheap_entry_hash
        assert type(package) is types.ModuleType


def test_install_failure_does_not_raise(staging_cls, monkeypatch):
    with monkeypatch.context() as m:
        m.delitem(sys.modules, 'nomad.files')
        m.delitem(sys.modules, 'nomad')
        assert not entry_hash.install()
    assert staging_cls.entry_hash is NOMAD_ENTRY_HASH


@pytest.mark.parametrize('entry_point', ENTRY_POINTS, ids=lambda ep: ep.name)
def test_entry_point_load_installs_patch(entry_point, staging_cls):
    # Some load()s fail here for unrelated reasons (template entry points that are
    # not registered, evaluix needing Python >= 3.10); the patch must be installed
    # before the plugin code is imported anyway.
    with contextlib.suppress(Exception):
        entry_point.load()
    assert staging_cls.entry_hash is entry_hash.cheap_entry_hash
