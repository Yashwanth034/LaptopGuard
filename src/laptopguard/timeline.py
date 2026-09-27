from __future__ import annotations

from datetime import datetime, timezone
import os

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None
from pathlib import Path
import time
from typing import Callable

from .platform_support import boot_identifier


def current_boot_id() -> str:
    return boot_identifier()


class EventTimeline:
    def __init__(self, state_dir: Path, boot_id_provider: Callable[[], str] = current_boot_id, monotonic_ns: Callable[[], int] = time.monotonic_ns):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.counter = self.state_dir / 'event-sequence'
        self.boot_id_provider = boot_id_provider
        self.monotonic_ns = monotonic_ns

    def next(self) -> dict:
        fd = os.open(self.counter, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'r+', encoding='utf-8') as fh:
            windows_lock = False
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX)
            elif msvcrt is not None:
                fh.seek(0, os.SEEK_END)
                if fh.tell() == 0:
                    fh.write('0')
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                windows_lock = True
            try:
                fh.seek(0)
                raw = fh.read().strip()
                sequence = int(raw or '0') + 1
                fh.seek(0)
                fh.truncate()
                fh.write(str(sequence))
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                if windows_lock:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'sequence': sequence,
            'boot_id': self.boot_id_provider(),
            'monotonic_ns': self.monotonic_ns(),
        }
