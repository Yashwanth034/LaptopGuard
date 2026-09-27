from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import subprocess
from typing import Callable


class BrightnessController:
    def __init__(self, runner: Callable = subprocess.run, command: str = 'brightnessctl', device: str | None = None):
        self.runner = runner
        self.command = command
        self.device = device or self._discover_device()

    def _discover_device(self) -> str | None:
        devices = []
        for path in Path('/sys/class/backlight').glob('*'):
            try:
                maximum = int((path / 'max_brightness').read_text().strip())
            except Exception:
                maximum = 0
            devices.append((maximum, path.name))
        return max(devices)[1] if devices else None

    def _base(self) -> list[str]:
        return [self.command, '-d', self.device] if self.device else [self.command, '-c', 'backlight']

    def get_raw(self) -> tuple[int, int]:
        if not self.device:
            raise RuntimeError('no display backlight device')
        current = self.runner([*self._base(), 'g'], capture_output=True, text=True, check=True)
        maximum = self.runner([*self._base(), 'm'], capture_output=True, text=True, check=True)
        return int(current.stdout.strip()), int(maximum.stdout.strip())

    def set_raw(self, value: int) -> None:
        self.runner([*self._base(), 'set', str(max(1, int(value)))], capture_output=True, text=True, check=True)

    def get_percent(self) -> int:
        if self.device:
            current, maximum = self.get_raw()
            return int(round(current * 100 / maximum)) if maximum else 0
        result = self.runner([self.command, '-m', '-c', 'backlight'], capture_output=True, text=True, check=True)
        match = re.search(r'(\d+)%', result.stdout)
        if not match:
            raise RuntimeError('could not read display brightness')
        return max(0, min(100, int(match.group(1))))

    def set_percent(self, percent: int) -> None:
        value = max(1, min(100, int(percent)))
        if self.device:
            _, maximum = self.get_raw()
            self.set_raw(max(1, round(maximum * value / 100)))
            return
        self.runner([self.command, '-c', 'backlight', 'set', f'{value}%'], capture_output=True, text=True, check=True)

    @contextmanager
    def boosted(self, percent: int = 100):
        if self.device:
            previous, maximum = self.get_raw()
            boosted = max(1, round(maximum * max(1, min(100, int(percent))) / 100))
            self.set_raw(boosted)
            try:
                yield previous
            finally:
                self.set_raw(previous)
            return
        previous = self.get_percent()
        self.set_percent(percent)
        try:
            yield previous
        finally:
            self.set_percent(previous)
