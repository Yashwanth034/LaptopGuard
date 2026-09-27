from pathlib import Path

from laptopguard.location import LocationSample, collect_location
from laptopguard.network import VpnState


def _vpn_on() -> VpnState:
    return VpnState(True, ('vpn0',), ('vpn',))


def test_offline_vpn_never_launches_browser_or_network_wifi_provider(tmp_path: Path):
    calls = {'browser': 0, 'wifi': 0}

    def browser_provider():
        calls['browser'] += 1
        raise AssertionError('browser geolocation must not launch while offline')

    def wifi_provider(*, points):
        calls['wifi'] += 1
        raise AssertionError('network Wi-Fi geolocation must not run while offline')

    sample = collect_location(
        vpn_state=_vpn_on(),
        gps_provider=lambda: None,
        wifi_provider=wifi_provider,
        geoclue_provider=lambda: None,
        ip_provider=lambda: None,
        cache_path=tmp_path / 'wifi-location-cache.json',
        wifi_points_provider=lambda: [],
        browser_provider=browser_provider,
        internet_provider=lambda: False,
    )

    assert sample is None
    assert calls == {'browser': 0, 'wifi': 0}


def test_online_vpn_still_uses_browser_geolocation(tmp_path: Path):
    browser_fix = LocationSample(17.4, 78.4, 'browser-geolocation', 12).normalized()

    sample = collect_location(
        vpn_state=_vpn_on(),
        gps_provider=lambda: None,
        wifi_provider=lambda *, points: None,
        geoclue_provider=lambda: None,
        ip_provider=lambda: None,
        cache_path=tmp_path / 'wifi-location-cache.json',
        wifi_points_provider=lambda: [],
        browser_provider=lambda: browser_fix,
        internet_provider=lambda: True,
    )

    assert sample is not None
    assert sample.source == 'browser-geolocation'
    assert sample.accuracy_m == 12


def test_networkmanager_connectivity_gate_accepts_only_full(monkeypatch):
    import laptopguard.network as net

    class Result:
        def __init__(self, state: str, returncode: int = 0):
            self.stdout = state + '\n'
            self.stderr = ''
            self.returncode = returncode

    monkeypatch.setattr(net.shutil, 'which', lambda name: '/usr/bin/nmcli' if name == 'nmcli' else None)

    def full_runner(args, **kwargs):
        if args == ['nmcli', '-t', '-f', 'CONNECTIVITY', 'general']:
            return Result('full')
        if args == ['nmcli', '-t', '--escape', 'no', '-f', 'TYPE,DEVICE', 'connection', 'show', '--active']:
            return Result('802-11-wireless:wlp0s20f3')
        raise AssertionError(args)

    assert net.internet_available(runner=full_runner) is True
    assert net.internet_available(runner=lambda *a, **k: Result('none')) is False
    assert net.internet_available(runner=lambda *a, **k: Result('limited')) is False


def test_connectivity_gate_rejects_full_status_without_physical_uplink(monkeypatch):
    import laptopguard.network as net

    class Result:
        def __init__(self, stdout: str, returncode: int = 0):
            self.stdout = stdout
            self.stderr = ''
            self.returncode = returncode

    monkeypatch.setattr(net.shutil, 'which', lambda name: '/usr/bin/nmcli' if name == 'nmcli' else None)

    def runner(args, **kwargs):
        if args == ['nmcli', '-t', '-f', 'CONNECTIVITY', 'general']:
            return Result('full\n')
        if args == ['nmcli', '-t', '--escape', 'no', '-f', 'TYPE,DEVICE', 'connection', 'show', '--active']:
            return Result('wireguard:rt-direct\nloopback:lo\n')
        raise AssertionError(args)

    assert net.internet_available(runner=runner) is False
