from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import socket
import subprocess
from typing import Callable

from .platform_support import IS_LINUX


@dataclass(frozen=True)
class VpnState:
    active: bool
    interfaces: tuple[str, ...]
    types: tuple[str, ...]


@dataclass(frozen=True)
class NetworkSnapshot:
    vpn: VpnState
    interfaces: tuple[dict, ...] = ()


def classify_interface(name: str) -> str:
    value = name.lower()
    if value.startswith(('wg', 'tun', 'tap', 'utun', 'ppp', 'ipsec', 'tailscale', 'zt')):
        return 'vpn'
    if value.startswith(('docker', 'br-', 'veth', 'virbr', 'lxc', 'podman')):
        return 'virtual'
    if value == 'lo':
        return 'loopback'
    return 'physical'


def detect_vpn(runner: Callable = subprocess.run) -> VpnState:
    interfaces: set[str] = set()
    types: set[str] = set()
    if shutil.which('wg'):
        try:
            result = runner(['wg', 'show', 'interfaces'], capture_output=True, text=True, timeout=3, check=False)
            for item in result.stdout.split():
                if item:
                    interfaces.add(item)
                    types.add('wireguard')
        except Exception:
            pass
    if shutil.which('nmcli'):
        try:
            result = runner(['nmcli', '-t', '--escape', 'no', '-f', 'TYPE,DEVICE', 'connection', 'show', '--active'], capture_output=True, text=True, timeout=4, check=False)
            for line in result.stdout.splitlines():
                if ':' not in line:
                    continue
                kind, device = line.split(':', 1)
                k = kind.lower()
                d = device.strip()
                if k in {'vpn', 'wireguard'} or classify_interface(d) == 'vpn':
                    if d:
                        interfaces.add(d)
                    types.add(k or 'vpn')
        except Exception:
            pass
    if shutil.which('ip'):
        try:
            result = runner(['ip', '-j', 'link', 'show'], capture_output=True, text=True, timeout=3, check=False)
            for item in json.loads(result.stdout or '[]'):
                name = str(item.get('ifname', ''))
                state = str(item.get('operstate', '')).upper()
                if classify_interface(name) == 'vpn' and state not in {'DOWN', 'NOTPRESENT', 'LOWERLAYERDOWN'}:
                    interfaces.add(name)
                    types.add('tunnel')
        except Exception:
            pass
    if not IS_LINUX:
        try:
            for _index, name in socket.if_nameindex():
                if classify_interface(name) == 'vpn':
                    interfaces.add(name)
                    types.add('tunnel')
        except Exception:
            pass
    return VpnState(bool(interfaces or types), tuple(sorted(interfaces)), tuple(sorted(types)))


def internet_available(runner: Callable = subprocess.run) -> bool:
    """Return True only for full connectivity backed by a physical uplink.

    Background browser geolocation is privacy-sensitive because launching a browser
    can surface a permission UI. Be fail-closed: when connectivity is unavailable,
    stale, VPN-only, or cannot be determined, callers skip browser/network-only
    providers.
    """
    if not shutil.which('nmcli'):
        if IS_LINUX:
            return False
        try:
            with socket.create_connection(('1.1.1.1', 443), timeout=2):
                return True
        except OSError:
            return False
    try:
        connectivity = runner(
            ['nmcli', '-t', '-f', 'CONNECTIVITY', 'general'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if connectivity.returncode != 0 or connectivity.stdout.strip().lower() != 'full':
            return False
        active = runner(
            ['nmcli', '-t', '--escape', 'no', '-f', 'TYPE,DEVICE', 'connection', 'show', '--active'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if active.returncode != 0:
            return False
        for line in active.stdout.splitlines():
            if ':' not in line:
                continue
            kind, device = line.split(':', 1)
            kind = kind.strip().lower()
            device = device.strip()
            if not device or kind in {'vpn', 'wireguard', 'loopback'}:
                continue
            if classify_interface(device) == 'physical':
                return True
        return False
    except Exception:
        return False


def snapshot(runner: Callable = subprocess.run) -> NetworkSnapshot:
    entries: list[dict] = []
    if shutil.which('ip'):
        try:
            result = runner(['ip', '-j', 'addr', 'show'], capture_output=True, text=True, timeout=4, check=False)
            for item in json.loads(result.stdout or '[]'):
                name = str(item.get('ifname', ''))
                addresses = []
                for addr in item.get('addr_info', []):
                    if addr.get('family') in {'inet', 'inet6'}:
                        addresses.append(addr.get('local'))
                entries.append({'name': name, 'class': classify_interface(name), 'addresses': [a for a in addresses if a]})
        except Exception:
            pass
    return NetworkSnapshot(detect_vpn(runner), tuple(entries))
