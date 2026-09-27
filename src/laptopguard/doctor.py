from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from .brightness import BrightnessController
from .browser_location import load_browser_settings
from .camera import _find_face_cascade
from .config import Settings
from .location import hardware_gps, wifi_access_points
from .mailer import probe as probe_mail
from .network import detect_vpn
from .platform_support import IS_LINUX, IS_MACOS, IS_WINDOWS, platform_name
from .queue_store import EncryptedQueue
from .session import active_session


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def _service_check(name: str) -> DoctorCheck:
    try:
        active = subprocess.run(['systemctl', 'is-active', '--quiet', name], check=False).returncode == 0
        enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet', name], check=False).returncode == 0
        return DoctorCheck(f'systemd {name}', active and enabled, f'active={active}, enabled={enabled}')
    except Exception as exc:
        return DoctorCheck(f'systemd {name}', False, str(exc))




def _location_capability_check(
    points,
    vpn_active: bool = False,
    browser_configured: bool = False,
    browser_session_ready: bool = False,
    browser_resolver=None,
) -> DoctorCheck:
    # Deliberately passive: doctor must never launch browser geolocation or call
    # an external positioning provider. Active resolution belongs to
    # `laptopguard location-test`; permission prompts belong only to setup.
    sources = []
    if len(points) >= 2:
        sources.append(f'{len(points)} Wi-Fi APs')
    if browser_configured:
        sources.append('browser profile configured' + ('/session ready' if browser_session_ready else '/session unavailable'))
    if vpn_active:
        sources.append('VPN-aware')
    ok = len(points) >= 2 or (browser_configured and browser_session_ready)
    detail = 'Passive check: ' + (', '.join(sources) if sources else 'no ready Wi-Fi/browser location source')
    return DoctorCheck('Physical location capability', ok, detail)

def _shutdown_guard_capability_check() -> DoctorCheck:
    inhibit = shutil.which('systemd-inhibit')
    if not inhibit:
        return DoctorCheck('Lock-screen shutdown guard', False, 'systemd-inhibit not found')
    try:
        result = subprocess.run(['systemd', '--version'], capture_output=True, text=True, timeout=3, check=False)
        first = (result.stdout.splitlines() or [''])[0]
        parts = first.split()
        version = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    except Exception:
        version = 0
    if version and version < 255:
        return DoctorCheck('Lock-screen shutdown guard', False, f'systemd {version} lacks shutdown-type metadata; 255+ required')
    detail = f'passive check: {inhibit}, systemd {version or "unknown"}, power-off/reboot metadata listener ready'
    return DoctorCheck('Lock-screen shutdown guard', True, detail)


def _portable_run(settings: Settings) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = [
        DoctorCheck(
            'Platform mode',
            True,
            f'{platform_name()} portable mode; Linux-only failed-login, systemd shutdown, and tamper hooks are disabled',
        )
    ]

    cascade = _find_face_cascade()
    checks.append(DoctorCheck('Face detector data', cascade is not None, str(cascade) if cascade else 'OpenCV Haar cascade data not found'))

    session = active_session()
    checks.append(DoctorCheck('Desktop session', session is not None, session.user if session else 'No current desktop session'))

    if IS_WINDOWS:
        helper = shutil.which('powershell') or shutil.which('pwsh')
        detail = helper or 'PowerShell screenshot helper not found'
    elif IS_MACOS:
        helper = shutil.which('screencapture') or ('/usr/sbin/screencapture' if Path('/usr/sbin/screencapture').is_file() else None)
        detail = helper or 'screencapture helper not found'
    else:
        helper = None
        detail = 'Unsupported desktop platform'
    checks.append(DoctorCheck('Screenshot capability', helper is not None, detail))

    vpn = detect_vpn()
    checks.append(DoctorCheck('VPN awareness', True, f'active={vpn.active}, interfaces={",".join(vpn.interfaces) or "none"}'))

    browser_settings = load_browser_settings()
    checks.append(DoctorCheck(
        'Browser geolocation',
        True,
        f'configured for {browser_settings.user}' if browser_settings is not None else 'optional; run laptopguard browser-location-setup to enable',
    ))

    mail_ok = settings.mail.enabled and bool(settings.mail.to_address and settings.mail.username and settings.mail.password())
    if mail_ok:
        try:
            probe_mail(settings.mail)
            checks.append(DoctorCheck('SMTP authentication', True, settings.mail.to_address))
        except Exception as exc:
            checks.append(DoctorCheck('SMTP authentication', False, f'{type(exc).__name__}: {exc}'))
    else:
        checks.append(DoctorCheck('SMTP authentication', False, 'Run: laptopguard configure'))

    state = Path(settings.state_dir)
    try:
        state.mkdir(parents=True, exist_ok=True)
        writable = state.is_dir() and os.access(state, os.W_OK)
    except OSError:
        writable = False
    checks.append(DoctorCheck('State directory', writable, str(state)))

    if writable:
        try:
            queue = EncryptedQueue(Path(settings.queue_dir), state / 'queue.key')
            corrupt = 0
            for item in queue.items():
                try:
                    queue.read(item)
                except Exception:
                    corrupt += 1
            checks.append(DoctorCheck('Encrypted queue health', corrupt == 0, f'{len(queue.items())} queued, {corrupt} corrupt'))
        except Exception as exc:
            checks.append(DoctorCheck('Encrypted queue health', False, str(exc)))
    return checks


def run(settings: Settings) -> list[DoctorCheck]:
    if not IS_LINUX:
        return _portable_run(settings)
    checks: list[DoctorCheck] = []
    cameras = sorted(Path('/dev').glob('video*'))
    camera_detail = (
        f'Passive check: {len(cameras)} video device(s) present; use laptopguard test for a real capture'
        if cameras else
        'Passive check: no /dev/video* device found'
    )
    checks.append(DoctorCheck('Webcam device presence', bool(cameras), camera_detail))
    cascade = _find_face_cascade()
    checks.append(DoctorCheck('Face detector data', cascade is not None, str(cascade) if cascade else 'OpenCV Haar cascade data not found; install opencv-data'))

    try:
        ctl = BrightnessController()
        value = ctl.get_percent()
        checks.append(DoctorCheck('Brightness control', True, f'{value}% via {ctl.device or "backlight class"}'))
    except Exception as exc:
        checks.append(DoctorCheck('Brightness control', False, str(exc)))

    session = active_session()
    checks.append(DoctorCheck('Active graphical session', session is not None, f'{session.user} ({session.session_type})' if session else 'No active local X11/Wayland session; login-screen captures will omit screenshots'))

    screenshot_helper = shutil.which('gnome-screenshot')
    screenshot_ok = session is not None and screenshot_helper is not None
    if session is None:
        screenshot_detail = 'Passive check: no active graphical session; security alerts will omit screenshots until a session exists'
    elif screenshot_helper is None:
        screenshot_detail = 'Passive check: gnome-screenshot helper not found'
    else:
        screenshot_detail = f'Passive check: active {session.session_type} session and {screenshot_helper} available; no screenshot was taken'
    checks.append(DoctorCheck('Screenshot capability', screenshot_ok if session is not None else True, screenshot_detail))

    for command, label in [('nmcli', 'NetworkManager'), ('journalctl', 'Journal monitor')]:
        path = shutil.which(command)
        checks.append(DoctorCheck(label, path is not None, path or f'{command} not found'))

    vpn = detect_vpn()
    checks.append(DoctorCheck('VPN awareness', True, f'active={vpn.active}, interfaces={",".join(vpn.interfaces) or "none"}, types={",".join(vpn.types) or "none"}'))
    browser_settings = load_browser_settings()
    if browser_settings is not None:
        browser_session_ok = session is not None and session.user == browser_settings.user
        detail = (
            f'using active {session.session_type} session for {session.user}'
            if browser_session_ok and session is not None
            else 'No matching active graphical session; browser location is unavailable until that user is logged in'
        )
        checks.append(DoctorCheck('Browser location background runtime', browser_session_ok, detail))
    aps = wifi_access_points()
    checks.append(DoctorCheck('Wi-Fi positioning input', len(aps) >= 2, f'{len(aps)} usable globally-administered access point(s) visible'))
    try:
        gps = hardware_gps()
    except Exception:
        gps = None
    if gps is not None:
        accuracy = f'±{gps.accuracy_m:.0f} m' if gps.accuracy_m is not None else 'accuracy unknown'
        checks.append(DoctorCheck('GPS/GNSS fix', True, f'{gps.source}, {accuracy}'))
    else:
        checks.append(DoctorCheck('GPS/GNSS fix', True, 'No active hardware fix; Wi-Fi positioning will be used'))
    checks.append(_location_capability_check(aps, vpn_active=vpn.active, browser_configured=browser_settings is not None and settings.location.browser_geolocation_enabled, browser_session_ready=(browser_settings is not None and session is not None and session.user == browser_settings.user)))

    mail_ok = settings.mail.enabled and bool(settings.mail.to_address and settings.mail.username and settings.mail.password())
    if mail_ok:
        try:
            probe_mail(settings.mail)
            checks.append(DoctorCheck('SMTP authentication', True, settings.mail.to_address))
        except Exception as exc:
            checks.append(DoctorCheck('SMTP authentication', False, f'{type(exc).__name__}: {exc}'))
    else:
        checks.append(DoctorCheck('SMTP authentication', False, 'Run: sudo laptopguard configure'))

    state = Path(settings.state_dir)
    writable = state.exists() and state.is_dir() and os.access(state, os.W_OK)
    checks.append(DoctorCheck('State directory', writable, str(state)))
    try:
        usage = shutil.disk_usage(state)
        free_mb = usage.free // (1024 * 1024)
        checks.append(DoctorCheck('Evidence disk space', free_mb >= 50, f'{free_mb} MiB free'))
    except Exception as exc:
        checks.append(DoctorCheck('Evidence disk space', False, str(exc)))

    try:
        queue = EncryptedQueue(Path(settings.queue_dir), state / 'queue.key')
        corrupt = 0
        for item in queue.items():
            try:
                queue.read(item)
            except Exception:
                corrupt += 1
        checks.append(DoctorCheck('Encrypted queue health', corrupt == 0, f'{len(queue.items())} queued, {corrupt} corrupt'))
    except Exception as exc:
        checks.append(DoctorCheck('Encrypted queue health', False, str(exc)))

    checks.append(_shutdown_guard_capability_check())
    if shutil.which('systemctl'):
        checks.append(_service_check('laptopguard.service'))
        checks.append(_service_check('laptopguard-watchdog.timer'))
    return checks
