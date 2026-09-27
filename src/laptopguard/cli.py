from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .camera import capture_best
from .config import load_config
from .daemon import run as run_daemon
from .doctor import run as run_doctor
from .engine import SecurityEngine
from .hardening import audit as hardening_audit
from .shutdown_guard import run as run_shutdown_guard, run_user_lock_watch
from .mailer import probe as probe_mail
from .location import collect_location, diagnose_location_sources
from .browser_location import load_browser_settings, setup_browser_location
from .network import detect_vpn
from .config import MailSettings
from .validation import valid_email
from .push import configure_topic, run_test as run_push_test
from .platform_support import (
    IS_LINUX,
    current_user,
    default_config_path,
    default_evidence_dir,
    default_queue_dir,
    default_secret_path,
    default_state_dir,
    is_admin,
    platform_name,
)
import tempfile

DEFAULT_CONFIG = default_config_path()
DEFAULT_SECRET = default_secret_path()


def _ask(prompt: str, default: str = '') -> str:
    suffix = f' [{default}]' if default else ''
    value = input(f'{prompt}{suffix}: ').strip()
    return value or default


def _running_as_admin() -> bool:
    geteuid = getattr(os, 'geteuid', None)
    return bool(geteuid() == 0) if callable(geteuid) else is_admin()


def _portable_path(path: Path) -> str:
    return str(path).replace('\\', '/')


def configure(path: Path) -> int:
    if IS_LINUX and not _running_as_admin() and str(path).startswith('/etc/'):
        print('Configuration under /etc requires root. Run: sudo laptopguard configure', file=sys.stderr)
        return 2
    host = _ask('SMTP host', 'smtp.gmail.com')
    port = int(_ask('SMTP SSL port', '465'))
    username = _ask('SMTP username/email')
    from_address = _ask('From address', username)
    to_address = _ask('Send security alerts to', username)
    password = getpass.getpass('SMTP app password/token: ').strip()
    if not username or not to_address or not password:
        print('Username, destination address, and app password/token are required.', file=sys.stderr)
        return 2
    if not valid_email(username) or not valid_email(from_address) or not valid_email(to_address):
        print('Invalid email address. Do not enter the app password in an email-address field.', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='laptopguard-config-') as temp_dir:
        probe_secret = Path(temp_dir) / 'smtp-password'
        probe_secret.write_text(password + '\n', encoding='utf-8')
        os.chmod(probe_secret, 0o600)
        test_settings = MailSettings(True, host, port, username, from_address, to_address, str(probe_secret), True)
        try:
            print('Testing SMTP authentication...')
            probe_mail(test_settings)
        except Exception as exc:
            print(f'SMTP authentication failed: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 2
    system_config = path == DEFAULT_CONFIG
    secret_path = DEFAULT_SECRET if system_config else path.with_name('smtp-password')
    state_dir = default_state_dir() if system_config else path.parent / 'state'
    evidence_dir = default_evidence_dir() if system_config else path.parent / 'evidence'
    queue_dir = default_queue_dir() if system_config else path.parent / 'queue'
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(password + '\n', encoding='utf-8')
    os.chmod(secret_path, 0o600)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'''state_dir = "{_portable_path(state_dir)}"
evidence_dir = "{_portable_path(evidence_dir)}"
queue_dir = "{_portable_path(queue_dir)}"
rate_limit_seconds = 180
failed_auth_threshold = 3
failed_auth_window_seconds = 120

[mail]
enabled = true
host = "{host}"
port = {port}
username = "{username}"
from_address = "{from_address}"
to_address = "{to_address}"
password_file = "{_portable_path(secret_path)}"
use_ssl = true

[capture]
camera_index = -1
auto_camera = true
max_seconds = 5.0
min_brightness = 45.0
min_sharpness = 90.0
require_face = true
boost_brightness = 100
capture_on_resume = false
capture_on_boot = false

[location]
enabled = true
allow_ip_fallback = true
tracking_minutes = 360
tracking_interval_seconds = 300
auto_tracking_after_alert = false
browser_geolocation_enabled = true
browser_max_vpn_accuracy_m = 250.0
''', encoding='utf-8')
    os.chmod(path, 0o600)
    print(f'Wrote {path}')
    if IS_LINUX and shutil_which('systemctl') and path == DEFAULT_CONFIG:
        result = subprocess.run(['systemctl', 'enable', '--now', 'laptopguard.service', 'laptopguard-watchdog.timer'], check=False)
        if result.returncode == 0:
            print('LaptopGuard service and watchdog enabled and started.')
        else:
            print('Configuration saved, but systemd enable/start failed. Run: sudo laptopguard status', file=sys.stderr)
    print('Run: sudo laptopguard test' if IS_LINUX else 'Run: laptopguard test')
    return 0


def configure_push(path: Path, topic: str) -> int:
    if IS_LINUX and not _running_as_admin():
        print('Push configuration requires root. Run with sudo.', file=sys.stderr)
        return 2
    settings = load_config(path)
    topic_file = Path(settings.push.topic_file)
    try:
        configure_topic(topic_file, Path(settings.state_dir), topic)
    except ValueError:
        print('Invalid ntfy topic. Enter only a private random topic name, not a URL.', file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'Could not save ntfy push configuration: {type(exc).__name__}', file=sys.stderr)
        return 2
    print('ntfy topic saved securely. Run: sudo laptopguard test-push' if IS_LINUX else 'ntfy topic saved securely. Run: laptopguard test-push')
    return 0


def test_push(settings) -> int:
    if IS_LINUX and not _running_as_admin():
        print('Push test requires root. Run with sudo.', file=sys.stderr)
        return 2
    if run_push_test(settings):
        if IS_LINUX:
            print('ntfy test notification sent. Protected power-off push is now enabled.')
        else:
            print('ntfy test notification sent. Portable evidence alerts continue to use SMTP/queue delivery.')
        return 0
    print('ntfy test notification failed. Push remains disabled.', file=sys.stderr)
    return 1


def shutil_which(command: str) -> str | None:
    import shutil
    return shutil.which(command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='laptopguard', description='Laptop anti-theft evidence and recovery agent')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG), help='configuration TOML path')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('configure', help='configure SMTP delivery and enable the service')
    configure_push = sub.add_parser('configure-push', help='configure ntfy topic for shutdown/reboot alerts')
    configure_push.add_argument('topic')
    sub.add_parser('test-push', help='send an isolated ntfy test notification')
    sub.add_parser('daemon', help='internal background-service command')
    sub.add_parser('shutdown-watch', help=argparse.SUPPRESS)
    sub.add_parser('lock-watch-user', help=argparse.SUPPRESS)
    event = sub.add_parser('event', help='internal event-injection command')
    event.add_argument('name')
    sub.add_parser('flush', help='retry queued encrypted alerts')
    sub.add_parser('doctor', help='check camera, network, brightness, location and email setup')
    sub.add_parser('hardening-audit', help='check disk/boot protections without changing them')
    sub.add_parser('test', help='capture and send a manual security test')
    sub.add_parser('location-test', help='resolve physical location without capturing a photo or sending email')
    sub.add_parser('browser-location-setup', help='one-time browser geolocation permission setup')
    tracking = sub.add_parser('tracking', help='control temporary location tracking')
    tracking.add_argument('action', choices=['on', 'off', 'status'])
    sub.add_parser('status', help='show background-service status')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    if args.command == 'configure':
        return configure(config_path)
    if args.command == 'configure-push':
        return configure_push(config_path, args.topic)
    if args.command == 'lock-watch-user':
        return run_user_lock_watch()
    if args.command == 'test-push' and IS_LINUX and not _running_as_admin():
        print('Push test requires root. Run with sudo.', file=sys.stderr)
        return 2
    if args.command == 'browser-location-setup':
        if IS_LINUX:
            user = os.environ.get('SUDO_USER', '').strip()
            if not user or user == 'root':
                print('Run this from your logged-in desktop account with: sudo laptopguard browser-location-setup', file=sys.stderr)
                return 2
        else:
            user = current_user()
        print('A dedicated browser window will open once. Click Allow location and approve the browser permission prompt.')
        configured, result = setup_browser_location(user)
        if configured is None:
            print(f"Browser location setup failed: {(result or {}).get('error', 'no location result')}", file=sys.stderr)
            return 1
        accuracy = float((result or {}).get('accuracy', 0) or 0)
        print(f'Browser location setup complete for {configured.user}. Accuracy in this test: ±{accuracy:.0f} m')
        print("This permission is stored in LaptopGuard's dedicated browser profile; normal browser data is not used.")
        return 0
    settings = load_config(config_path)
    if args.command == 'test-push':
        return test_push(settings)
    if args.command == 'daemon':
        run_daemon(settings)
        return 0
    if args.command == 'shutdown-watch':
        return run_shutdown_guard(settings)
    if args.command == 'doctor':
        bad = 0
        for check in run_doctor(settings):
            tag = 'OK' if check.ok else 'WARN'
            bad += not check.ok
            print(f'[{tag}] {check.name}: {check.detail}')
        return 0 if bad == 0 else 1
    if args.command == 'hardening-audit':
        if not IS_LINUX:
            print(f'Hardening audit is currently Linux-specific; {platform_name()} portable mode does not modify OS security settings.')
            return 0
        for check in hardening_audit():
            tag = 'OK' if check.ok is True else ('WARN' if check.ok is False else 'UNKNOWN')
            print(f'[{tag}] {check.name}: {check.detail}')
        return 0
    if args.command == 'status':
        if IS_LINUX and shutil_which('systemctl'):
            return subprocess.run(['systemctl', '--no-pager', '--full', 'status', 'laptopguard.service'], check=False).returncode
        print(f'LaptopGuard portable mode on {platform_name()}: run `laptopguard daemon` in the user session for queue/tracking support.')
        return 0
    if args.command == 'location-test':
        vpn = detect_vpn()
        sample = collect_location(allow_ip=settings.location.allow_ip_fallback, cache_path=Path(settings.state_dir) / 'wifi-location-cache.json', browser_max_vpn_accuracy_m=settings.location.browser_max_vpn_accuracy_m, browser_enabled=settings.location.browser_geolocation_enabled)
        print(f'VPN detected: {vpn.active} ({", ".join(vpn.types) or "none"})')
        if sample is None:
            print('Physical location: unavailable')
            if vpn.active:
                print('VPN/IP location was not used as a physical-location substitute.')
            else:
                print('No trustworthy location source returned a fix.')
            report = diagnose_location_sources(timeout=3.0)
            print(f"GPS/GNSS: {report.get('gps', 'unavailable')}")
            print(f"Usable Wi-Fi APs: {report.get('wifi_access_points', 0)}")
            print(f"BeaconDB: {report.get('beacondb', 'no-fix')}")
            print(f"Mylnikov batch: {report.get('mylnikov_batch', 'no-fix')}")
            print(f"Mylnikov individual AP matches: {report.get('mylnikov_individual_matches', 0)}")
            print(f"Google Wi-Fi: {report.get('google', 'not-configured')}")
            print(f"GeoClue: {report.get('geoclue', 'no-fix')}")
            print(f"Browser geolocation: {report.get('browser_geolocation', 'not-configured')}")
            return 1
        sample = sample.normalized()
        accuracy = f'±{sample.accuracy_m:.0f} m' if sample.accuracy_m is not None else 'unknown'
        print(f'Physical location source: {sample.source}')
        print(f'Accuracy: {accuracy}')
        print(f'Confidence: {sample.confidence.upper()}')
        print(f'Coordinates: {sample.latitude:.6f}, {sample.longitude:.6f}')
        print(f'Map: https://maps.google.com/?q={sample.latitude},{sample.longitude}')
        return 0

    engine = SecurityEngine(settings)
    if args.command == 'event':
        result = engine.handle_event(args.name)
        print(result)
        return 0
    if args.command == 'flush':
        print(f'Sent {engine.flush_queue()} queued alert(s).')
        return 0
    if args.command == 'test':
        result = engine.handle_event('manual_test')
        print(result)
        return 0 if result.delivery in {'sent', 'queued'} else 1
    if args.command == 'tracking':
        if args.action == 'on':
            engine.activate_tracking()
            print('Location tracking enabled temporarily; periodic location emails will be sent until tracking expires or is turned off.')
        elif args.action == 'off':
            engine.deactivate_tracking()
            print('Location tracking disabled.')
        else:
            print('active' if engine.tracking_active() else 'inactive')
        return 0
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
