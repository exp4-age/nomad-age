"""Fingerprint of a raw file: size, SHA-256 and modification time."""

import hashlib
import os
from datetime import datetime, timezone

# Particle transport videos have up to ~800 MB; reading them in chunks keeps the
# memory flat.
CHUNK_SIZE = 1 << 20


def file_sha256(path: str, chunk_size: int = CHUNK_SIZE) -> str:
    """Hex SHA-256 of the content of `path`, read in chunks of `chunk_size` bytes."""
    digest = hashlib.sha256()
    buffer = bytearray(chunk_size)
    view = memoryview(buffer)
    with open(path, 'rb', buffering=0) as f:
        while n := f.readinto(buffer):
            digest.update(view[:n])
    return digest.hexdigest()


def file_fingerprint(path: str) -> dict:
    """Size (bytes), hex SHA-256 and UTC modification time of `path`, keyed as
    the quantities of AGE_RawFile."""
    stat = os.stat(path)
    return {
        'file_size': stat.st_size,
        'sha256': file_sha256(path),
        'modified': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    }
