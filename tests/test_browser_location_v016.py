from pathlib import Path

from laptopguard.browser_location import BrowserLocationSettings, accept_browser_fix, load_browser_settings, save_browser_settings
from laptopguard.location import LocationSample, collect_location
from laptopguard.network import VpnState


def test_browser_fix_under_vpn_requires_good_accuracy():
    good = LocationSample(17.3, 78.4, 'browser-geolocation', 42).normalized()
    broad = LocationSample(17.3, 78.4, 'browser-geolocation', 5000).normalized()
    assert accept_browser_fix(good, vpn_active=True, max_vpn_accuracy_m=250) is good
    assert accept_browser_fix(broad, vpn_active=True, max_vpn_accuracy_m=250) is None


def test_browser_settings_round_trip(tmp_path: Path):
    path = tmp_path / 'browser-location.json'
    settings = BrowserLocationSettings('alice', '/usr/bin/google-chrome', '/home/alice/.local/share/laptopguard-location-browser')
    save_browser_settings(path, settings)
    assert load_browser_settings(path) == settings
    assert oct(path.stat().st_mode & 0o777) == '0o600'


def test_collect_location_uses_browser_fallback_with_vpn():
    vpn = VpnState(True, ('tun0',), ('vpn',))
    browser = LocationSample(17.3, 78.4, 'browser-geolocation', 55).normalized()
    result = collect_location(
        allow_ip=True,
        vpn_state=vpn,
        gps_provider=lambda: None,
        wifi_provider=lambda **kwargs: None,
        geoclue_provider=lambda: None,
        ip_provider=lambda: LocationSample(1, 2, 'ip', 25000).normalized(),
        wifi_points_provider=lambda: [],
        browser_provider=lambda: browser,
        browser_max_vpn_accuracy_m=250,
        internet_provider=lambda: True,
    )
    assert result is not None
    assert result.source == 'browser-geolocation'
    assert result.vpn_detected is True
