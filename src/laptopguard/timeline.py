from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import time
from typing import Callable


def current_boot_id() -> str:
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()
    except OSError:
        return 'unknown'


class EventTimeline:
    def __init__(self, state_dir: Path, boot_id_provider: Callable[[], str] = current_boot_id, monotonic_ns: Callable[[], int] = time.monotonic_ns):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.counter = self.state_dir / 'event-sequence'
        self.boot_id_provider = boot_id_provider
        self.monotonic_ns = monotonic_ns

    def next(self) -> dict:
        fd = os.open(self.counter, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            with os.fdopen(fd, 'r+', encoding='utf-8') as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                raw = fh.read().strip()
                sequence = int(raw or '0') + 1
                fh.seek(0)
                fh.truncate()
                fh.write(str(sequence))
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            pass
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'sequence': sequence,
            'boot_id': self.boot_id_provider(),
            'monotonic_ns': self.monotonic_ns(),
        }
