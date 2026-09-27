from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable

from .session import active_session


class ScreenIlluminator:
    def __init__(self, session_provider: Callable = active_session, popen: Callable = subprocess.Popen):
        self.session_provider = session_provider
        self.popen = popen

    @contextmanager
    def active(self):
        process = None
        session = self.session_provider()
        script = Path(__file__).with_name('white_screen.py')
        if session is not None and shutil.which('runuser') and script.is_file():
            env_args = [f'{k}={v}' for k, v in session.environment().items()]
            try:
                process = self.popen(
                    ['runuser', '-u', session.user, '--', 'env', *env_args, '/usr/bin/python3', str(script)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.2)
            except Exception:
                process = None
        try:
            yield
        finally:
            if process is not None:
                try:
                    process.terminate()
                    process.wait(timeout=1)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
