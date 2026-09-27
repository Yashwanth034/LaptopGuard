from __future__ import annotations

import time
from typing import Callable


class RateLimiter:
    def __init__(self, window_seconds: int, clock: Callable[[], float] = time.monotonic):
        self.window_seconds = max(0, int(window_seconds))
        self.clock = clock
        self._last: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        previous = self._last.get(key)
        if previous is not None and now - previous < self.window_seconds:
            return False
        self._last[key] = now
        return True
