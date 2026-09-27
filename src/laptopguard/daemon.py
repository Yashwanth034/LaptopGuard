from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from .boot_marker import BootMarker, current_boot_id
from .config import Settings
from .engine import SecurityEngine
from .monitor import journal_lines, suspicious_from_line
from .platform_support import IS_LINUX
from .tamper import CRITICAL_PATHS, MAINTENANCE_MARKER, TamperBaseline



def shutdown_guard_command() -> list[str] | None:
    inhibit = shutil.which('systemd-inhibit')
    launcher = shutil.which('laptopguard') or '/usr/local/bin/laptopguard'
    if not inhibit:
        return None
    return [
        inhibit,
        '--what=shutdown',
        '--mode=delay',
        '--who=LaptopGuard',
        '--why=Capture protected-screen power-off evidence',
        launcher,
        'shutdown-watch',
    ]


def _start_shutdown_guard():
    command = shutdown_guard_command()
    if not command:
        return None
    try:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print(f'LaptopGuard shutdown guard unavailable: {exc}', file=sys.stderr, flush=True)
        return None


def _stop_shutdown_guard(process) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass



def _tamper_changes(baseline: TamperBaseline, maintenance_marker: Path = MAINTENANCE_MARKER):
    if Path(maintenance_marker).exists():
        return []
    return baseline.check()



def _watch_auth(engine: SecurityEngine, stop: threading.Event) -> None:
    for line in journal_lines():
        if stop.is_set():
            return
        event = suspicious_from_line(line)
        if event:
            try:
                engine.handle_event(event)
            except Exception as exc:
                print(f'LaptopGuard auth event handling failed: {exc}', file=sys.stderr, flush=True)


def run(settings: Settings) -> None:
    engine = SecurityEngine(settings)
    state_dir = Path(settings.state_dir)
    stop = threading.Event()
    watcher = None
    shutdown_guard = None
    if IS_LINUX:
        watcher = threading.Thread(target=_watch_auth, args=(engine, stop), name='laptopguard-auth', daemon=True)
        watcher.start()
        shutdown_guard = _start_shutdown_guard()

    marker = BootMarker(state_dir / 'last-boot-id')
    if marker.is_new(current_boot_id()):
        engine.handle_event('boot')

    tamper = TamperBaseline(state_dir / 'tamper-baseline.json', CRITICAL_PATHS) if IS_LINUX else None
    if tamper is not None and _tamper_changes(tamper):
        engine.handle_event('tamper')
    next_flush = 0.0
    next_tamper = time.monotonic() + 300
    next_location = time.monotonic() + settings.location.tracking_interval_seconds
    next_shutdown_guard_check = time.monotonic() + 60

    try:
        while True:
            now = time.monotonic()
            if now >= next_flush:
                engine.flush_queue()
                engine.cleanup_pending_failed_auth()
                next_flush = now + 60
            if now >= next_location:
                if engine.tracking_active():
                    engine.send_location_update()
                next_location = now + max(60, settings.location.tracking_interval_seconds)
            if IS_LINUX and tamper is not None and now >= next_tamper:
                changes = _tamper_changes(tamper)
                if changes:
                    engine.handle_event('tamper')
                next_tamper = now + 300
            if IS_LINUX and now >= next_shutdown_guard_check:
                if shutdown_guard is None or shutdown_guard.poll() is not None:
                    shutdown_guard = _start_shutdown_guard()
                next_shutdown_guard_check = now + 60
            time.sleep(2)
    finally:
        stop.set()
        _stop_shutdown_guard(shutdown_guard)
