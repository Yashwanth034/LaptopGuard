from __future__ import annotations

import os
from pathlib import Path


class StorageReserve:
    def __init__(self, path: Path, bytes_to_reserve: int = 4 * 1024 * 1024):
        self.path = Path(path)
        self.bytes_to_reserve = max(0, int(bytes_to_reserve))

    def ensure(self) -> None:
        if self.path.exists() or self.bytes_to_reserve <= 0:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if hasattr(os, 'posix_fallocate'):
                os.posix_fallocate(fd, 0, self.bytes_to_reserve)
            else:
                os.write(fd, b'\0' * self.bytes_to_reserve)
            os.fsync(fd)
        finally:
            os.close(fd)

    def release(self) -> None:
        self.path.unlink(missing_ok=True)
