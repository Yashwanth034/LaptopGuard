from pathlib import Path
import os
import threading

from laptopguard.daemon import _watch_auth
from laptopguard.evidence import capture_screenshot
from laptopguard.session import ActiveSession


class R:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ''


def test_screenshot_does_not_use_session_runtime_dir_for_temporary_file(tmp_path: Path, monkeypatch):
    target = tmp_path / 'evidence' / 'screenshot.png'
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    session = ActiveSession('2', 'alice', os.getuid(), 'x11', ':0', str(runtime))
    seen_sources = []

    monkeypatch.setattr('laptopguard.evidence.shutil.which', lambda name: '/usr/bin/gnome-screenshot' if name == 'gnome-screenshot' else None)

    def runner(args, **kwargs):
        source = Path(args[-1])
        seen_sources.append(source)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'png')
        return R(returncode=0)

    result = capture_screenshot(target, session_provider=lambda: session, runner=runner)

    assert result == target
    assert target.read_bytes() == b'png'
    assert seen_sources
    assert all(source.parent != runtime for source in seen_sources)


def test_auth_watcher_continues_after_one_event_handler_exception(monkeypatch):
    import laptopguard.daemon as daemon

    monkeypatch.setattr(daemon, 'journal_lines', lambda: iter(['first', 'second']))
    monkeypatch.setattr(daemon, 'suspicious_from_line', lambda line: 'failed_auth')

    class Engine:
        def __init__(self):
            self.calls = []

        def handle_event(self, event):
            self.calls.append(event)
            if len(self.calls) == 1:
                raise OSError('simulated evidence failure')

    engine = Engine()
    _watch_auth(engine, threading.Event())

    assert engine.calls == ['failed_auth', 'failed_auth']
