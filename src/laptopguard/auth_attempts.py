from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable


@dataclass(frozen=True)
class FailedAuthAttempt:
    count: int
    trigger: bool


class FailedAuthTracker:
    def __init__(
        self,
        path: Path,
        threshold: int = 2,
        window_seconds: int = 120,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.threshold = max(1, int(threshold))
        self.window_seconds = max(1, int(window_seconds))
        self.clock = clock

    def _load(self) -> tuple[int, float]:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return int(data.get('count', 0)), float(data.get('first_at', 0.0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0, 0.0

    def _save(self, count: int, first_at: float) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.failed-auth-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump({'count': count, 'first_at': first_at}, fh, separators=(',', ':'))
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass

    def reset(self) -> None:
        self.path.unlink(missing_ok=True)

    def register(self) -> FailedAuthAttempt:
        now = self.clock()
        count, first_at = self._load()
        if count <= 0 or first_at <= 0 or now - first_at > self.window_seconds:
            count = 0
            first_at = now
        count += 1
        trigger = count >= self.threshold
        if trigger:
            self.reset()
        else:
            self._save(count, first_at)
        return FailedAuthAttempt(count=count, trigger=trigger)
