import hashlib
import os
from datetime import datetime, timezone

import pytest

from nomad_age.utils.fingerprint import CHUNK_SIZE, file_fingerprint, file_sha256

ABC_SHA256 = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
EMPTY_SHA256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


@pytest.mark.parametrize('content, sha256', [(b'abc', ABC_SHA256), (b'', EMPTY_SHA256)])
def test_sha256_of_known_content(tmp_path, content, sha256):
    path = tmp_path / 'f.bin'
    path.write_bytes(content)
    assert file_sha256(str(path)) == sha256


@pytest.mark.parametrize('chunk_size', [1, 7, 4096, CHUNK_SIZE])
def test_sha256_does_not_depend_on_chunks(tmp_path, chunk_size):
    # not a multiple of any chunk size, larger than the default one
    content = os.urandom(CHUNK_SIZE * 2 + 12345 if chunk_size > 1 else 10001)
    path = tmp_path / 'f.bin'
    path.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert file_sha256(str(path), chunk_size) == expected


def test_fingerprint_has_size_checksum_and_utc_mtime(tmp_path):
    path = tmp_path / 'f.bin'
    path.write_bytes(b'abc')
    os.utime(path, (0, 1700000000.5))
    assert file_fingerprint(str(path)) == {
        'file_size': 3,
        'sha256': ABC_SHA256,
        'modified': datetime(2023, 11, 14, 22, 13, 20, 500000, timezone.utc),
    }
