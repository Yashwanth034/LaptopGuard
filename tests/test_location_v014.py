import json
from pathlib import Path
from types import SimpleNamespace

from laptopguard.location import (
    LocationSample,
    choose_location_consensus,
    parse_gpspipe_output,
    parse_google_response,
    parse_mylnikov_response,
    wifi_access_points,
)


class R:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.stderr = ''
        self.returncode = returncode


def test_mylnikov_response_accepts_lat_and_legacy_lan_field():
    a = parse_mylnikov_response({'result': 200, 'data': {'lat': '17.385', 'lon': '78.486', 'range': '80'}})
    b = parse_mylnikov_response({'result': 200, 'data': {'lan': '17.385', 'lon': '78.486', 'range': '80'}})
    assert a is not None and b is not None
    assert a.source == 'wifi-mylnikov'
    assert a.accuracy_m == 80
    assert round(b.latitude, 3) == 17.385


def test_google_response_never_accepts_ip_fallback_marker():
    assert parse_google_response({'location': {'lat': 1, 'lng': 2}, 'accuracy': 20}, consider_ip=False).source == 'wifi-google'
    assert parse_google_response({'location': {'lat': 1, 'lng': 2}, 'accuracy': 25000}, consider_ip=True) is None


def test_gpspipe_parser_prefers_3d_tpv_fix_and_accuracy():
    text = '\n'.join([
        json.dumps({'class': 'TPV', 'mode': 1}),
        json.dumps({'class': 'TPV', 'mode': 3, 'lat': 17.385044, 'lon': 78.486671, 'epx': 4.0, 'epy': 6.5}),
    ])
    sample = parse_gpspipe_output(text)
    assert sample is not None
    assert sample.source == 'gpsd'
    assert sample.accuracy_m == 6.5


def test_wifi_scan_includes_signal_strength_for_geolocation(monkeypatch):
    monkeypatch.setattr('laptopguard.location.shutil.which', lambda name: '/usr/bin/nmcli' if name == 'nmcli' else None)

    def runner(args, **kwargs):
        return R('08:bb:cc:dd:ee:00:80:6\n10:20:30:40:50:60:60:11\n')

    points = wifi_access_points(runner=runner)
    assert len(points) == 2
    assert points[0]['signalStrength'] == -60
    assert points[0]['channel'] == 6


def test_consensus_combines_nearby_wifi_results_and_rejects_large_conflict():
    close = choose_location_consensus([
        LocationSample(17.38500, 78.48660, 'wifi-beacondb', 80),
        LocationSample(17.38510, 78.48670, 'wifi-mylnikov', 120),
    ])
    assert close is not None
    assert close.source == 'wifi-consensus'
    assert close.accuracy_m is not None and close.accuracy_m <= 120

    conflict = choose_location_consensus([
        LocationSample(17.385, 78.486, 'wifi-beacondb', 500),
        LocationSample(28.6139, 77.2090, 'wifi-mylnikov', 500),
    ])
    assert conflict is None


def test_wifi_location_falls_back_to_mylnikov_when_beacondb_has_no_coverage(monkeypatch):
    import laptopguard.location as loc
    points = [
        {'macAddress': '08:11:22:33:44:55', 'signalStrength': -50},
        {'macAddress': '10:22:33:44:55:66', 'signalStrength': -60},
    ]
    monkeypatch.setattr(loc, 'beacondb_wifi_location', lambda points, timeout: None)
    monkeypatch.setattr(loc, 'mylnikov_wifi_location', lambda points, timeout: LocationSample(17.385, 78.486, 'wifi-mylnikov', 90).normalized())
    monkeypatch.setattr(loc, '_read_google_key', lambda path: '')
    sample = loc.wifi_location(points=points, timeout=0.1)
    assert sample is not None
    assert sample.source == 'wifi-mylnikov'


def test_vpn_detection_catches_unmanaged_tun_interface(monkeypatch):
    import laptopguard.network as net

    class Result:
        def __init__(self, stdout=''):
            self.stdout = stdout
            self.stderr = ''
            self.returncode = 0

    monkeypatch.setattr(net.shutil, 'which', lambda name: f'/usr/bin/{name}' if name == 'ip' else None)

    def runner(args, **kwargs):
        if args[:4] == ['ip', '-j', 'link', 'show']:
            return Result('[{"ifname":"lo","operstate":"UNKNOWN"},{"ifname":"tun0","operstate":"UP"}]')
        raise AssertionError(args)

    state = net.detect_vpn(runner=runner)
    assert state.active is True
    assert 'tun0' in state.interfaces


def test_mylnikov_single_bssid_fallback_parses_individual_hit(monkeypatch):
    import io
    import laptopguard.location as loc

    class Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    payload = b'{"result":200,"data":{"lat":"17.385","lon":"78.486","range":"140"}}'
    monkeypatch.setattr(loc.urllib.request, 'urlopen', lambda request, timeout=0: Response(payload))
    sample = loc.mylnikov_single_bssid_location({'macAddress': '08:11:22:33:44:55', 'signalStrength': -45}, timeout=0.1)
    assert sample is not None
    assert sample.source == 'wifi-mylnikov-ap'
    assert sample.accuracy_m == 140


def test_mylnikov_provider_falls_back_to_individual_bssid_hits(monkeypatch):
    import laptopguard.location as loc

    points = [
        {'macAddress': '08:11:22:33:44:55', 'signalStrength': -45},
        {'macAddress': '10:22:33:44:55:66', 'signalStrength': -55},
        {'macAddress': '18:33:44:55:66:77', 'signalStrength': -70},
    ]
    monkeypatch.setattr(loc, '_mylnikov_batch_wifi_location', lambda points, timeout=5.0: None)

    samples = {
        '08:11:22:33:44:55': loc.LocationSample(17.38500, 78.48660, 'wifi-mylnikov-ap', 120).normalized(),
        '10:22:33:44:55:66': loc.LocationSample(17.38510, 78.48670, 'wifi-mylnikov-ap', 160).normalized(),
        '18:33:44:55:66:77': None,
    }
    monkeypatch.setattr(loc, 'mylnikov_single_bssid_location', lambda point, timeout=5.0: samples[point['macAddress']])
    sample = loc.mylnikov_wifi_location(points, timeout=0.1)
    assert sample is not None
    assert sample.source in {'wifi-mylnikov-ap', 'wifi-consensus'}
    assert abs(sample.latitude - 17.38505) < 0.001


def test_location_diagnostics_reports_provider_failures_without_bssids(monkeypatch):
    import laptopguard.location as loc

    points = [
        {'macAddress': '08:11:22:33:44:55', 'signalStrength': -45},
        {'macAddress': '10:22:33:44:55:66', 'signalStrength': -55},
    ]
    monkeypatch.setattr(loc, 'hardware_gps', lambda: None)
    monkeypatch.setattr(loc, 'wifi_access_points', lambda: points)
    monkeypatch.setattr(loc, 'beacondb_wifi_location', lambda points, timeout=5.0: None)
    monkeypatch.setattr(loc, '_mylnikov_batch_wifi_location', lambda points, timeout=5.0: None)
    monkeypatch.setattr(loc, 'mylnikov_individual_wifi_location', lambda points, timeout=5.0: (None, 0))
    monkeypatch.setattr(loc, '_read_google_key', lambda path=loc.DEFAULT_GOOGLE_KEY_FILE: '')
    monkeypatch.setattr(loc, 'geoclue_location', lambda: None)
    report = loc.diagnose_location_sources()
    assert report['gps'] == 'unavailable'
    assert report['wifi_access_points'] == 2
    assert report['beacondb'] == 'no-fix'
    assert report['mylnikov_batch'] == 'no-fix'
    assert report['mylnikov_individual_matches'] == 0
    assert report['google'] == 'not-configured'
    assert report['geoclue'] == 'no-fix'
    assert '08:11:22:33:44:55' not in str(report)
