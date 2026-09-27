from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import pwd
import secrets
import signal
import shutil
import subprocess
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .session import ActiveSession, active_session

DEFAULT_SETTINGS_FILE = Path('/etc/laptopguard/browser-location.json')
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class BrowserLocationSettings:
    user: str
    browser: str
    profile_dir: str
    port: int = DEFAULT_PORT


def save_browser_settings(path: Path, settings: BrowserLocationSettings) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.tmp')
    temp.write_text(json.dumps(settings.__dict__, separators=(',', ':')), encoding='utf-8')
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def load_browser_settings(path: Path = DEFAULT_SETTINGS_FILE) -> BrowserLocationSettings | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        return BrowserLocationSettings(
            user=str(raw['user']),
            browser=str(raw['browser']),
            profile_dir=str(raw['profile_dir']),
            port=int(raw.get('port', DEFAULT_PORT)),
        )
    except Exception:
        return None


def find_browser() -> str | None:
    for name in ('google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser', 'brave-browser', 'brave'):
        path = shutil.which(name)
        if path:
            return path
    return None


def accept_browser_fix(sample, vpn_active: bool, max_vpn_accuracy_m: float = 250.0):
    if sample is None:
        return None
    if not vpn_active:
        return sample
    accuracy = getattr(sample, 'accuracy_m', None)
    if accuracy is None or float(accuracy) > float(max_vpn_accuracy_m):
        return None
    return sample


def _location_page(setup: bool, token: str) -> str:
    button = '<button id="go">Allow location</button>' if setup else ''
    if setup:
        start_script = 'document.getElementById("go").onclick=locate;'
        status = 'Click Allow location and approve the browser prompt once.'
    else:
        # Querying permission state does not trigger a permission prompt. Only an
        # already-granted profile is allowed to call getCurrentPosition here.
        start_script = 'backgroundLocate();'
        status = 'Checking location…'
    return f'''<!doctype html><meta charset="utf-8"><title>LaptopGuard Location</title>
<style>body{{font-family:sans-serif;max-width:560px;margin:60px auto;padding:20px}}button{{font-size:18px;padding:10px 16px}}</style>
<h2>LaptopGuard location</h2><p id="status">{status}</p>{button}
<script>
async function send(data){{try{{await fetch('/result?token={token}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});}}catch(e){{}}}}
function locate(){{document.getElementById('status').textContent='Checking location…';navigator.geolocation.getCurrentPosition(
 p=>{{send({{latitude:p.coords.latitude,longitude:p.coords.longitude,accuracy:p.coords.accuracy,timestamp:p.timestamp}});document.getElementById('status').textContent='Location access is ready.';}},
 e=>{{send({{error:String(e.code)+': '+e.message}});document.getElementById('status').textContent='Location unavailable.';}},
 {{enableHighAccuracy:true,timeout:12000,maximumAge:0}});}}
async function backgroundLocate(){{
 try{{
  if(!navigator.permissions || !navigator.permissions.query){{await send({{error:'geolocation permission status unavailable'}});return;}}
  const permission=await navigator.permissions.query({{name:'geolocation'}});
  if(permission.state !== 'granted'){{await send({{error:'geolocation permission not granted'}});return;}}
  locate();
 }}catch(e){{await send({{error:'geolocation permission check failed'}});}}
}}
{start_script}
</script>'''


class _Handler(BaseHTTPRequestHandler):
    server_version = 'LaptopGuardLocation/1.0'

    def _send(self, code: int, body: str, content_type: str = 'text/html; charset=utf-8') -> None:
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        token = parse_qs(parsed.query).get('token', [''])[0]
        if token != self.server.token:
            self._send(403, 'forbidden', 'text/plain; charset=utf-8')
            return
        setup = parsed.path == '/setup'
        self._send(200, _location_page(setup, self.server.token))

    def do_POST(self):
        parsed = urlparse(self.path)
        token = parse_qs(parsed.query).get('token', [''])[0]
        if token != self.server.token:
            self._send(403, 'forbidden', 'text/plain; charset=utf-8')
            return
        try:
            length = min(4096, int(self.headers.get('Content-Length', '0')))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            self.server.result = payload
            self.server.done.set()
            self._send(204, '', 'text/plain; charset=utf-8')
        except Exception:
            self._send(400, 'bad request', 'text/plain; charset=utf-8')

    def log_message(self, *_args):
        return


class _LocationServer(HTTPServer):
    allow_reuse_address = True

    def __init__(self, port: int):
        super().__init__(('127.0.0.1', port), _Handler)
        self.token = secrets.token_urlsafe(24)
        self.done = threading.Event()
        self.result: dict | None = None

    def url(self, setup: bool = False) -> str:
        route = 'setup' if setup else 'locate'
        return f'http://127.0.0.1:{self.server_port}/{route}?token={self.token}'


def _browser_command(
    settings: BrowserLocationSettings,
    url: str,
    background: bool,
    session: ActiveSession | None = None,
) -> list[str]:
    info = pwd.getpwnam(settings.user)
    browser_args = [
        settings.browser,
        '--app=' + url,
        '--user-data-dir=' + settings.profile_dir,
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-sync',
    ]
    env = {
        'HOME': info.pw_dir,
        'USER': settings.user,
        'LOGNAME': settings.user,
    }
    if background:
        if session is None or session.user != settings.user:
            raise RuntimeError('No matching active graphical session for browser location')
        env.update(session.environment())
        browser_args += [
            '--start-minimized',
            '--window-size=320,240',
            '--window-position=-32000,-32000',
            '--disable-notifications',
        ]
    else:
        runtime = Path(f'/run/user/{info.pw_uid}')
        if runtime.is_dir():
            env['XDG_RUNTIME_DIR'] = str(runtime)

    env_args = [f'{key}={value}' for key, value in env.items() if value]
    return ['runuser', '-u', settings.user, '--', 'env', *env_args, *browser_args]


def _prepare_profile(settings: BrowserLocationSettings) -> None:
    info = pwd.getpwnam(settings.user)
    profile = Path(settings.profile_dir)
    for directory in (profile.parent.parent, profile.parent, profile):
        if not directory.exists():
            directory.mkdir(exist_ok=True)
            os.chown(directory, info.pw_uid, info.pw_gid)
    os.chown(profile, info.pw_uid, info.pw_gid)
    os.chmod(profile, 0o700)


def _run_browser_probe(settings: BrowserLocationSettings, setup: bool, timeout: float, popen: Callable = subprocess.Popen) -> dict | None:
    _prepare_profile(settings)
    server = _LocationServer(settings.port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proc = None
    try:
        session = None
        if not setup:
            session = active_session()
            if session is None or session.user != settings.user:
                return {'error': 'No matching active graphical session for browser location'}
        command = _browser_command(settings, server.url(setup), background=not setup, session=session)
        proc = popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        server.done.wait(timeout)
        return server.result
    finally:
        server.shutdown()
        server.server_close()
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    pass


def setup_browser_location(user: str, settings_path: Path = DEFAULT_SETTINGS_FILE, timeout: float = 45.0) -> tuple[BrowserLocationSettings | None, dict | None]:
    browser = find_browser()
    if not browser:
        return None, {'error': 'No supported Chrome/Chromium/Brave browser found'}
    info = pwd.getpwnam(user)
    profile = Path(info.pw_dir) / '.local' / 'share' / 'laptopguard-location-browser'
    settings = BrowserLocationSettings(user, browser, str(profile), DEFAULT_PORT)
    try:
        result = _run_browser_probe(settings, setup=True, timeout=timeout)
    except Exception as exc:
        return None, {'error': f'{type(exc).__name__}: {exc}'}
    if not result or result.get('error'):
        return None, result or {'error': 'No browser location result received'}
    save_browser_settings(Path(settings_path), settings)
    return settings, result


def browser_location_raw(settings_path: Path = DEFAULT_SETTINGS_FILE, timeout: float = 18.0) -> dict | None:
    settings = load_browser_settings(Path(settings_path))
    if settings is None or not Path(settings.browser).is_file():
        return None
    try:
        return _run_browser_probe(settings, setup=False, timeout=timeout)
    except Exception:
        return None
