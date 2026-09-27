from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable

from .network import snapshot as network_snapshot
from .session import active_session, run_as_session


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def active_ssid(runner: Callable = subprocess.run, timeout: float = 5.0) -> str | None:
    if not shutil.which('nmcli'):
        return None
    try:
        result = runner(['nmcli', '-t', '--escape', 'no', '-f', 'ACTIVE,SSID', 'dev', 'wifi'], capture_output=True, text=True, timeout=timeout, check=False)
        for line in result.stdout.splitlines():
            if line.startswith('yes:'):
                return line.split(':', 1)[1] or None
    except Exception:
        pass
    return None


def nearby_wifi(runner: Callable = subprocess.run, limit: int = 12) -> list[dict]:
    if not shutil.which('nmcli'):
        return []
    try:
        result = runner(['nmcli', '-t', '--escape', 'no', '-f', 'BSSID,SSID,SIGNAL', 'dev', 'wifi', 'list'], capture_output=True, text=True, timeout=8, check=False)
        out = []
        for line in result.stdout.splitlines():
            match = re.match(r'^((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}):(.*):(\d+)$', line)
            if not match:
                continue
            bssid, ssid, signal = match.groups()
            out.append({'ssid': ssid, 'bssid': bssid.lower(), 'signal_percent': int(signal)})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def capture_screenshot(output: Path, session_provider: Callable = active_session, runner: Callable = subprocess.run) -> Path | None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    session = session_provider()
    if session is None:
        return None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix='laptopguard-screenshot-'))
        os.chown(temp_dir, session.uid, session.uid)
        temp_dir.chmod(0o700)
    except OSError:
        return None
    source = temp_dir / 'screenshot.png'
    candidates = []
    # On X11, scrot captures the root window without the visible flash that
    # gnome-screenshot can produce. Keep gnome-screenshot as a fallback and as
    # the primary option on Wayland, where scrot generally cannot capture.
    if session.session_type == 'x11' and shutil.which('scrot'):
        candidates.append(['scrot', str(source)])
    if shutil.which('gnome-screenshot'):
        candidates.append(['gnome-screenshot', '-f', str(source)])
    if shutil.which('scrot') and session.session_type != 'x11':
        candidates.append(['scrot', str(source)])
    if shutil.which('import') and session.session_type == 'x11':
        candidates.append(['import', '-window', 'root', str(source)])
    try:
        for cmd in candidates:
            try:
                env_args = [f'{k}={v}' for k, v in session.environment().items()]
                result = runner(['runuser', '-u', session.user, '--', 'env', *env_args, *cmd], capture_output=True, timeout=10, check=False)
                if output.is_file() and output.stat().st_size > 0:
                    return output
                if result.returncode == 0 and source.is_file() and source.stat().st_size > 0:
                    output.write_bytes(source.read_bytes())
                    os.chmod(output, 0o600)
                    return output
            except Exception:
                continue
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return None


def base_metadata(event: str) -> dict:
    session = active_session()
    net = network_snapshot()
    return {
        'event': event,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'hostname': os.uname().nodename,
        'username': session.user if session else 'login-screen',
        'session': asdict(session) if session else None,
        'wifi_ssid': active_ssid(),
        'nearby_wifi': nearby_wifi(),
        'network': {
            'vpn': {
                'active': net.vpn.active,
                'interfaces': list(net.vpn.interfaces),
                'types': list(net.vpn.types),
            },
            'interfaces': list(net.interfaces),
        },
    }


def write_metadata(target: Path, metadata: dict, attachments: list[Path]) -> dict:
    data = dict(metadata)
    data['sha256'] = {Path(path).name: sha256_file(Path(path)) for path in attachments if Path(path).is_file()}
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f'.{target.name}.tmp')
    temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    return data
