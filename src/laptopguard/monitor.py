from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator

from .events import classify_auth_event


def suspicious_from_line(line: str) -> str | None:
    event = classify_auth_event(line)
    return event.kind if event.suspicious else None


def journal_lines() -> Iterator[str]:
    while True:
        process = None
        try:
            process = subprocess.Popen(
                ['journalctl', '-f', '-n', '0', '-o', 'short-iso'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                yield line.rstrip('\n')
        except Exception:
            time.sleep(2)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
