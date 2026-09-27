from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable


def hardware_ready(runner: Callable = subprocess.run) -> bool:
    if not list(Path('/dev').glob('video*')):
        return False
    if shutil.which('nmcli'):
        try:
            result = runner(['nmcli', '-t', '-f', 'STATE', 'general'], capture_output=True, text=True, timeout=3, check=False)
            if result.returncode != 0:
                return False
        except Exception:
            return False
    return True


def wait_for_hardware(timeout: float = 12.0, interval: float = 0.5, predicate: Callable[[], bool] = hardware_ready) -> bool:
    deadline = time.monotonic() + max(0, timeout)
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
