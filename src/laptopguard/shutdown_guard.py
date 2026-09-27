from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Callable

from .config import Settings
from .engine import SecurityEngine
from .session import active_session, run_as_session


SHUTDOWN_PUSH_DEADLINE_SECONDS = 5.0


class LockStateTracker:
    """Thread-safe cached lock state observed before shutdown teardown starts."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.locked: bool | None = None
        self.source = 'unknown'

    def update(self, locked: bool, source: str) -> None:
        with self._guard:
            self.locked = bool(locked)
            self.source = str(source or 'unknown')

    def snapshot(self) -> tuple[bool | None, str]:
        with self._guard:
            return self.locked, self.source

    def handle_logind_signal(self, signal_name: str) -> None:
        if signal_name == 'Lock':
            self.update(True, 'logind-lock')
        elif signal_name == 'Unlock':
            self.update(False, 'logind-unlock')


def cached_or_probe_lock_state(tracker: LockStateTracker, probe: Callable[[], bool]) -> bool:
    locked, _source = tracker.snapshot()
    if locked is not None:
        return bool(locked)
    return bool(probe())


def parse_user_lock_watch_line(line: str) -> tuple[bool, str] | None:
    parts = str(line or '').strip().split()
    if len(parts) < 3 or parts[0] != 'LOCKED' or parts[1] not in {'0', '1'}:
        return None
    return parts[1] == '1', parts[2]


def user_lock_watch_command(session, launcher: str | None = None) -> list[str]:
    launcher = launcher or shutil.which('laptopguard') or '/usr/local/bin/laptopguard'
    env_args = [f'{k}={v}' for k, v in session.environment().items()]
    return ['runuser', '-u', session.user, '--', 'env', *env_args, launcher, 'lock-watch-user']


def run_user_lock_watch() -> int:
    """Emit lock transitions from the graphical user's session bus.

    This helper intentionally runs as the logged-in user. The root shutdown
    guard consumes its stdout and caches the state before shutdown teardown can
    make desktop lock APIs disappear or return stale values.
    """
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()

    def callback(_connection, _sender, _object_path, interface, _signal, parameters, _user_data):
        try:
            unpacked = parameters.unpack()
            if not unpacked:
                return
            active = bool(unpacked[0])
            source = 'cinnamon' if interface == 'org.cinnamon.ScreenSaver' else 'gnome'
            print(f'LOCKED {1 if active else 0} {source}', flush=True)
        except Exception:
            return

    subscriptions = []
    for interface in ('org.cinnamon.ScreenSaver', 'org.gnome.ScreenSaver'):
        subscriptions.append(bus.signal_subscribe(
            None,
            interface,
            'ActiveChanged',
            None,
            None,
            Gio.DBusSignalFlags.NONE,
            callback,
            None,
        ))
    try:
        loop.run()
    finally:
        for subscription in subscriptions:
            bus.signal_unsubscribe(subscription)
    return 0


def _watch_user_lock_state(tracker: LockStateTracker, stop_event: threading.Event) -> None:
    """Keep a session-bus lock watcher attached to the active graphical user."""
    current_key = None
    process = None
    while not stop_event.is_set():
        session = active_session()
        if session is None:
            stop_event.wait(2.0)
            continue
        key = (session.session_id, session.uid, session.runtime_dir)
        if process is None or process.poll() is not None or key != current_key:
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass
            try:
                process = subprocess.Popen(
                    user_lock_watch_command(session),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                current_key = key
            except Exception:
                process = None
                stop_event.wait(2.0)
                continue

        line = ''
        try:
            if process.stdout is not None:
                line = process.stdout.readline()
        except Exception:
            line = ''
        if not line:
            if process.poll() is not None:
                process = None
            else:
                stop_event.wait(0.25)
            continue
        parsed = parse_user_lock_watch_line(line)
        if parsed is not None:
            locked, source = parsed
            tracker.update(locked, f'{source}-active-changed')
            print(f'LaptopGuard lock-state cache: locked={locked} source={source}-active-changed', flush=True)

    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass


def _start_user_lock_state_watcher(tracker: LockStateTracker, stop_event: threading.Event):
    thread = threading.Thread(
        target=_watch_user_lock_state,
        args=(tracker, stop_event),
        name='laptopguard-lock-state',
        daemon=True,
    )
    thread.start()
    return thread


def shutdown_type_from_metadata(metadata: dict | None) -> str:
    if not isinstance(metadata, dict):
        return ''
    value = metadata.get('type', '')
    try:
        if hasattr(value, 'unpack'):
            value = value.unpack()
    except Exception:
        pass
    value = str(value or '').strip().lower()
    # systemd's public documentation spells this 'power-off', while the
    # v255 implementation used by Ubuntu/Mint emits 'poweroff'. Normalize
    # both forms so the guard works across distro/systemd variants.
    if value in {'poweroff', 'power-off', 'power off'}:
        return 'poweroff'
    return value


def should_alert_for_shutdown(
    start: bool, metadata: dict | None, locked: bool, login_screen: bool = False
) -> bool:
    return (
        bool(start)
        and shutdown_type_from_metadata(metadata) == 'poweroff'
        and (bool(locked) or bool(login_screen))
    )


def shutdown_event_for_signal(
    start: bool,
    metadata: dict | None,
    *,
    locked: bool,
    login_screen: bool,
    push_enabled: bool,
) -> str | None:
    # Push delivery must never widen the security policy. LaptopGuard reacts
    # only to a real power-off that starts while the machine is already locked
    # or while the display manager is showing the login screen. Reboots and
    # ordinary unlocked shutdowns are lifecycle events and are ignored.
    del push_enabled  # retained in the signature for compatibility with callers/tests
    if not start or shutdown_type_from_metadata(metadata) != 'poweroff':
        return None
    if locked:
        return 'lockscreen_shutdown'
    if login_screen:
        return 'login_screen_shutdown'
    return None


def run_with_deadline(action: Callable[[], object], timeout: float = 5.0) -> tuple[bool, object | None]:
    result: dict[str, object] = {}

    def worker() -> None:
        try:
            result['value'] = action()
        except BaseException as exc:
            result['error'] = exc

    thread = threading.Thread(target=worker, name='laptopguard-shutdown-deadline', daemon=True)
    thread.start()
    thread.join(max(0.0, float(timeout)))
    if thread.is_alive():
        return False, None
    error = result.get('error')
    if isinstance(error, BaseException):
        raise error
    return True, result.get('value')


def login_screen_active(runner: Callable = subprocess.run) -> bool:
    """Return True when the active local display is a login greeter.

    Prefer logind's greeter class because it is display-manager agnostic.
    Linux Mint's LightDM/Slick Greeter is also detected by process name as a
    fallback because some LightDM builds do not expose a greeter session via
    logind during the shutdown transition.
    """
    try:
        listing = runner(
            ['loginctl', 'list-sessions', '--no-legend'],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except Exception:
        listing = None

    for line in (getattr(listing, 'stdout', '') or '').splitlines():
        parts = line.split()
        if not parts:
            continue
        sid = parts[0]
        try:
            detail = runner(
                ['loginctl', 'show-session', sid, '-p', 'Name', '-p', 'User',
                 '-p', 'Active', '-p', 'Remote', '-p', 'Type', '-p', 'Class',
                 '-p', 'Service'],
                capture_output=True, text=True, timeout=3, check=False,
            )
        except Exception:
            continue
        values = {}
        for row in (getattr(detail, 'stdout', '') or '').splitlines():
            if '=' in row:
                key, value = row.split('=', 1)
                values[key] = value
        if values.get('Active', '').lower() != 'yes':
            continue
        if values.get('Remote', '').lower() == 'yes':
            continue
        session_class = values.get('Class', '').strip().lower()
        name = values.get('Name', '').strip().lower()
        service = values.get('Service', '').strip().lower()
        if session_class == 'greeter':
            return True
        if name in {'lightdm', 'gdm', 'sddm'} and 'greeter' in service:
            return True

    # Mint 22 commonly uses Slick Greeter. It exists at the initial login
    # screen but is not present during an ordinary unlocked user session.
    try:
        result = runner(
            ['pgrep', '-x', 'slick-greeter'],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if getattr(result, 'returncode', 1) == 0:
            return True
    except Exception:
        pass
    return False


def _any_local_graphical_session_locked(runner: Callable = subprocess.run) -> bool:
    """Read LockedHint without requiring the session to remain Active.

    During shutdown, desktops may flip a session away from Active before our
    delay-inhibitor callback runs. Scanning local graphical user sessions keeps
    the pre-shutdown lock state observable during that small teardown window.
    """
    try:
        listing = runner(
            ['loginctl', 'list-sessions', '--no-legend'],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except Exception:
        return False

    for line in (getattr(listing, 'stdout', '') or '').splitlines():
        parts = line.split()
        if not parts:
            continue
        sid = parts[0]
        try:
            detail = runner(
                ['loginctl', 'show-session', sid, '-p', 'User', '-p', 'Remote',
                 '-p', 'Type', '-p', 'Class', '-p', 'LockedHint'],
                capture_output=True, text=True, timeout=3, check=False,
            )
        except Exception:
            continue
        values = {}
        for row in (getattr(detail, 'stdout', '') or '').splitlines():
            if '=' in row:
                key, value = row.split('=', 1)
                values[key] = value
        if values.get('Remote', 'no').lower() == 'yes':
            continue
        if values.get('Class', '') not in {'', 'user', 'user-early'}:
            continue
        if values.get('Type', '') not in {'x11', 'wayland'}:
            continue
        if values.get('LockedHint', '').lower() == 'yes':
            return True
    return False


def session_is_locked(runner: Callable = subprocess.run) -> bool:
    # Check all local graphical sessions first. Unlike active_session(), this
    # does not lose the lock state merely because shutdown has started.
    if _any_local_graphical_session_locked(runner=runner):
        return True

    session = active_session(runner=runner)
    if session is None:
        return False

    # Primary per-session signal: systemd-logind's lock hint.
    try:
        result = runner(
            ['loginctl', 'show-session', session.session_id, '-p', 'LockedHint', '--value'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.stdout.strip().lower() == 'yes':
            return True
    except Exception:
        pass

    # Cinnamon/GNOME fallback for desktops that do not keep LockedHint in sync.
    if shutil.which('gdbus'):
        for destination, object_path in (
            ('org.cinnamon.ScreenSaver', '/org/cinnamon/ScreenSaver'),
            ('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver'),
        ):
            try:
                result = run_as_session(
                    session,
                    ['gdbus', 'call', '--session', '--dest', destination, '--object-path', object_path,
                     '--method', f'{destination}.GetActive'],
                    runner=runner,
                    timeout=3,
                )
                text = (getattr(result, 'stdout', b'') or b'')
                if isinstance(text, bytes):
                    text = text.decode(errors='ignore')
                if 'true' in str(text).lower():
                    return True
            except Exception:
                continue
    return False


def _subscribe_and_wait(on_signal: Callable[[bool, dict], None], tracker: LockStateTracker) -> None:
    # Import lazily so ordinary LaptopGuard commands do not depend on a live
    # GLib main loop or D-Bus connection.
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    loop = GLib.MainLoop()

    def callback(_connection, _sender, _object_path, _interface, _signal, parameters, _user_data):
        start = False
        try:
            start, metadata = parameters.unpack()
            on_signal(bool(start), metadata if isinstance(metadata, dict) else {})
        finally:
            if bool(start) and shutdown_type_from_metadata(metadata if isinstance(metadata, dict) else {}) in {'poweroff', 'reboot'}:
                loop.quit()

    subscription = bus.signal_subscribe(
        'org.freedesktop.login1',
        'org.freedesktop.login1.Manager',
        'PrepareForShutdownWithMetadata',
        '/org/freedesktop/login1',
        None,
        Gio.DBusSignalFlags.NONE,
        callback,
        None,
    )

    def session_callback(_connection, _sender, _object_path, _interface, signal_name, _parameters, _user_data):
        if signal_name in {'Lock', 'Unlock'}:
            tracker.handle_logind_signal(signal_name)
            locked, source = tracker.snapshot()
            print(f'LaptopGuard lock-state cache: locked={locked} source={source}', flush=True)

    session_subscription = bus.signal_subscribe(
        'org.freedesktop.login1',
        'org.freedesktop.login1.Session',
        None,
        None,
        None,
        Gio.DBusSignalFlags.NONE,
        session_callback,
        None,
    )
    try:
        loop.run()
    finally:
        bus.signal_unsubscribe(subscription)
        bus.signal_unsubscribe(session_subscription)


def run(
    settings: Settings,
    lock_checker: Callable[[], bool] = session_is_locked,
    login_screen_checker: Callable[[], bool] = login_screen_active,
) -> int:
    engine = SecurityEngine(settings)
    tracker = LockStateTracker()

    # A positive startup probe is useful; a negative one is deliberately not
    # cached because Mint 22/Cinnamon 6.2 can visibly lock while reporting
    # LockedHint=no and GetActive=false. Lock/unlock transitions observed before
    # shutdown are authoritative for this guard.
    try:
        if bool(lock_checker()):
            tracker.update(True, 'startup-probe')
    except Exception:
        pass

    stop_event = threading.Event()
    _start_user_lock_state_watcher(tracker, stop_event)

    def on_signal(start: bool, metadata: dict) -> None:
        shutdown_type = shutdown_type_from_metadata(metadata)
        # Restart/reboot is explicitly out of scope. Return before touching the
        # security engine so it cannot capture evidence or send notifications.
        if not start or shutdown_type != 'poweroff':
            return
        try:
            locked = cached_or_probe_lock_state(tracker, lock_checker)
        except Exception as exc:
            print(f'LaptopGuard shutdown guard lock check failed: {exc}', flush=True)
            locked = False
        _cached, source = tracker.snapshot()
        source = source if _cached is not None else 'shutdown-probe'
        login_screen = False
        if not locked:
            try:
                login_screen = bool(login_screen_checker())
            except Exception as exc:
                print(f'LaptopGuard login-screen check failed: {exc}', flush=True)
        event = shutdown_event_for_signal(
            True,
            metadata,
            locked=locked,
            login_screen=login_screen,
            push_enabled=False,
        )
        print(
            f'LaptopGuard shutdown guard: type={shutdown_type} locked={locked} '
            f'login_screen={login_screen} source={source}',
            flush=True,
        )
        if event is None:
            return
        try:
            try:
                push_enabled = bool(engine.push_enabled())
            except Exception:
                push_enabled = False
            if push_enabled:
                completed, result = run_with_deadline(
                    lambda: engine.handle_event(event),
                    timeout=SHUTDOWN_PUSH_DEADLINE_SECONDS,
                )
                if not completed:
                    print('LaptopGuard shutdown push window expired; shutdown will continue.', flush=True)
                    return
            else:
                result = engine.handle_event(event)
            print(
                f'LaptopGuard shutdown alert: delivery={result.delivery} '
                f'photo={result.photo_captured} location={result.location_captured}',
                flush=True,
            )
        except Exception as exc:
            # The shutdown must never be permanently blocked by LaptopGuard.
            print(f'LaptopGuard shutdown alert failed: {exc}', flush=True)

    try:
        _subscribe_and_wait(on_signal, tracker)
    finally:
        stop_event.set()
    return 0
