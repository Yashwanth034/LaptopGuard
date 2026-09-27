from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import pwd
import shutil
import subprocess
from typing import Callable


@dataclass(frozen=True)
class ActiveSession:
    session_id: str
    user: str
    uid: int
    session_type: str
    display: str
    runtime_dir: str
    xauthority: str = ''
    wayland_display: str = ''

    def environment(self) -> dict[str, str]:
        env = {
            'XDG_RUNTIME_DIR': self.runtime_dir,
            'DBUS_SESSION_BUS_ADDRESS': f'unix:path={self.runtime_dir}/bus',
        }
        if self.display:
            env['DISPLAY'] = self.display
        if self.xauthority:
            env['XAUTHORITY'] = self.xauthority
        if self.wayland_display:
            env['WAYLAND_DISPLAY'] = self.wayland_display
        return env


def parse_loginctl_sessions(rows: list[dict]) -> ActiveSession | None:
    candidates = []
    for row in rows:
        if not row.get('active') or row.get('remote'):
            continue
        session_type = str(row.get('type') or '')
        display = str(row.get('display') or '')
        wayland_display = str(row.get('wayland_display') or '')
        if session_type not in {'x11', 'wayland'}:
            if wayland_display:
                session_type = 'wayland'
            elif display:
                session_type = 'x11'
            else:
                continue
        candidate = dict(row)
        candidate['type'] = session_type
        candidates.append(candidate)
    if not candidates:
        return None
    r = candidates[0]
    uid = int(r['uid'])
    return ActiveSession(str(r['id']), str(r['user']), uid, str(r.get('type') or ''), str(r.get('display') or ''), f'/run/user/{uid}', str(r.get('xauthority') or ''), str(r.get('wayland_display') or ''))


def active_session(runner: Callable = subprocess.run) -> ActiveSession | None:
    if not shutil.which('loginctl'):
        return None
    try:
        listing = runner(['loginctl', 'list-sessions', '--no-legend'], capture_output=True, text=True, timeout=4, check=False)
        rows = []
        for line in listing.stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            sid = parts[0]
            detail = runner(['loginctl', 'show-session', sid, '-p', 'Name', '-p', 'User', '-p', 'Active', '-p', 'Remote', '-p', 'Type', '-p', 'Display', '-p', 'Leader'], capture_output=True, text=True, timeout=4, check=False)
            values = {}
            for row in detail.stdout.splitlines():
                if '=' in row:
                    k, v = row.split('=', 1)
                    values[k] = v
            if not values.get('User'):
                continue
            uid = int(values['User'])
            user = values.get('Name') or pwd.getpwuid(uid).pw_name
            proc_env = {}
            leader = values.get('Leader', '')
            if leader.isdigit():
                try:
                    raw = Path(f'/proc/{leader}/environ').read_bytes().split(b'\0')
                    for item in raw:
                        if b'=' in item:
                            k, v = item.split(b'=', 1)
                            proc_env[k.decode(errors='ignore')] = v.decode(errors='ignore')
                except OSError:
                    pass
            rows.append({
                'id': sid,
                'user': user,
                'uid': uid,
                'active': values.get('Active') == 'yes',
                'remote': values.get('Remote') == 'yes',
                'type': values.get('Type', ''),
                'display': values.get('Display') or proc_env.get('DISPLAY', ''),
                'xauthority': proc_env.get('XAUTHORITY', ''),
                'wayland_display': proc_env.get('WAYLAND_DISPLAY', ''),
            })
        return parse_loginctl_sessions(rows)
    except Exception:
        return None


def run_as_session(session: ActiveSession, command: list[str], runner: Callable = subprocess.run, timeout: int = 10):
    env_args = [f'{k}={v}' for k, v in session.environment().items()]
    return runner(['runuser', '-u', session.user, '--', 'env', *env_args, *command], capture_output=True, timeout=timeout, check=False)
