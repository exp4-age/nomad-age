"""
Cheap aux-file fingerprint for NOMAD's ``StagingUploadFiles.entry_hash``.

NOMAD hashes the mainfile *and the content of every other file in the mainfile's
directory* for every entry. Our uploads keep large particle-tracking videos next to
small measurement files, so each entry read gigabytes. This patch keeps hashing the
mainfile content in full but replaces the content of each aux file by a fingerprint
of its upload-relative path, size and modification time.

Install with :func:`install` (called from the plugin entry points' ``load()``).
Set ``NOMAD_AGE_FULL_ENTRY_HASH=1`` to keep NOMAD's original implementation.
"""

import hashlib
import logging
import os
import sys
import types

ENV_VAR = 'NOMAD_AGE_FULL_ENTRY_HASH'
ORIGINAL_ATTR = '_nomad_age_original_entry_hash'
PATCHED_FLAG = '_nomad_age_cheap_entry_hash'

# Separates the mainfile content from the aux file fingerprints. Paths cannot contain
# NUL bytes and sizes/mtimes are decimal numbers, so NUL separators are unambiguous.
AUX_HEADER = b'\0nomad-age-aux-fingerprint-v1\0'

_CHUNK_SIZE = 65536
_logged = set()


def full_entry_hash_requested() -> bool:
    return os.environ.get(ENV_VAR, '').strip().lower() in ('1', 'true', 'yes', 'on')


def cheap_entry_hash(self, mainfile: str, mainfile_key: str) -> str:
    """
    Hash of the mainfile content plus path, size and mtime of each aux file.

    Entries without aux files get the same hash as NOMAD's original implementation.

    Raises:
        KeyError: If the mainfile does not exist.
    """
    from nomad import utils

    entry_files = list(self.entry_files(mainfile))
    hash = hashlib.sha512()
    with open(self._raw_dir.join_file(entry_files[0]).os_path, 'rb') as f:
        for data in iter(lambda: f.read(_CHUNK_SIZE), b''):
            hash.update(data)

    aux_files = entry_files[1:]
    if aux_files:
        hash.update(AUX_HEADER + str(len(aux_files)).encode('ascii'))
        for path in aux_files:
            stat = os.stat(self._raw_dir.join_file(path).os_path)
            hash.update(
                b'\0%s\0%d\0%d' % (path.encode('utf8'), stat.st_size, stat.st_mtime_ns)
            )

    if mainfile_key:
        hash.update(mainfile_key.encode('utf8'))
    return utils.make_websave(hash)


setattr(cheap_entry_hash, PATCHED_FLAG, True)


def install() -> bool:
    """
    Replaces ``StagingUploadFiles.entry_hash`` with :func:`cheap_entry_hash`.

    Entry points can be loaded while NOMAD imports ``nomad.files`` (``nomad.files`` ->
    ``nomad.archive`` -> ``nomad.infrastructure`` -> ``nomad.parsing.parsers``), so
    ``nomad.files`` is never imported here. If it is not fully imported yet, the patch
    is applied as soon as the import system sets ``files`` on the ``nomad`` package.

    Idempotent and never raises. Returns whether the cheap hash is installed now.
    """
    try:
        return _install()
    except Exception:
        _log_once(
            'failed',
            'nomad-age: could not install cheap entry_hash, keeping NOMAD default',
            exc_info=True,
        )
        return False


class _PatchOnFilesImport(types.ModuleType):
    """Class of the ``nomad`` package until ``nomad.files`` is imported."""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == 'files':
            self.__class__ = types.ModuleType
            install()


def _install() -> bool:
    if full_entry_hash_requested():
        _log_once('disabled', f'nomad-age: {ENV_VAR} is set, keeping full entry_hash')
        return False

    staging_upload_files = getattr(
        sys.modules.get('nomad.files'), 'StagingUploadFiles', None
    )
    if staging_upload_files is None:
        nomad = sys.modules['nomad']
        if type(nomad) is types.ModuleType:
            nomad.__class__ = _PatchOnFilesImport
        return False

    if getattr(staging_upload_files.entry_hash, PATCHED_FLAG, False):
        return True

    setattr(staging_upload_files, ORIGINAL_ATTR, staging_upload_files.entry_hash)
    staging_upload_files.entry_hash = cheap_entry_hash
    logging.getLogger(__name__).info(
        'nomad-age: installed cheap entry_hash (aux files fingerprinted by path, '
        'size, mtime); set %s=1 to disable',
        ENV_VAR,
    )
    return True


def _log_once(key: str, message: str, exc_info: bool = False) -> None:
    if key in _logged:
        return
    _logged.add(key)
    logger = logging.getLogger(__name__)
    if exc_info:
        logger.warning(message, exc_info=True)
    else:
        logger.info(message)


def uninstall() -> None:
    """Restores NOMAD's original ``StagingUploadFiles.entry_hash``."""
    nomad = sys.modules.get('nomad')
    if type(nomad) is _PatchOnFilesImport:
        nomad.__class__ = types.ModuleType

    staging_upload_files = getattr(
        sys.modules.get('nomad.files'), 'StagingUploadFiles', None
    )
    if staging_upload_files is not None and ORIGINAL_ATTR in vars(staging_upload_files):
        staging_upload_files.entry_hash = vars(staging_upload_files)[ORIGINAL_ATTR]
        delattr(staging_upload_files, ORIGINAL_ATTR)
