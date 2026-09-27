from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from typing import Callable

from .network import VpnState, detect_vpn, internet_available
from .platform_support import IS_LINUX, default_google_key_path


USER_AGENT = 'LaptopGuard/0.1.25'
DEFAULT_GOOGLE_KEY_FILE = default_google_key_path()


@dataclass(frozen=True)
class LocationSample:
    latitude: float
    longitude: float
    source: str
    accuracy_m: float | None = None
    timestamp: str = ''
    confidence: str = ''
    vpn_detected: bool = False

    def normalized(self) -> 'LocationSample':
        confidence = self.confidence or confidence_for(self.accuracy_m, self.source)
        return LocationSample(
            self.latitude,
            self.longitude,
            self.source,
            self.accuracy_m,
            self.timestamp or datetime.now(timezone.utc).isoformat(),
            confidence,
            self.vpn_detected,
        )


def confidence_for(accuracy: float | None, source: str) -> str:
    if source in {'modem-gps', 'gpsd'}:
        return 'high'
    if accuracy is not None and accuracy <= 100:
        return 'high'
    if accuracy is not None and accuracy <= 1500:
        return 'medium'
    return 'low'


def _valid_coordinates(latitude: float, longitude: float) -> bool:
    return -90 <= latitude <= 90 and -180 <= longitude <= 180 and not (latitude == 0 and longitude == 0)


def parse_mmcli_location(text: str) -> LocationSample | None:
    lat = re.search(r'latitude\s*:\s*(-?\d+(?:\.\d+)?)', text, re.I)
    lon = re.search(r'longitude\s*:\s*(-?\d+(?:\.\d+)?)', text, re.I)
    if not lat or not lon:
        return None
    latitude = float(lat.group(1))
    longitude = float(lon.group(1))
    if not _valid_coordinates(latitude, longitude):
        return None
    return LocationSample(latitude, longitude, 'modem-gps').normalized()


def modem_gps(runner: Callable = subprocess.run) -> LocationSample | None:
    if not shutil.which('mmcli'):
        return None
    try:
        listed = runner(['mmcli', '-L'], capture_output=True, text=True, timeout=4, check=False)
        match = re.search(r'/Modem/(\d+)', listed.stdout)
        if not match:
            return None
        modem = match.group(1)
        runner(['mmcli', '-m', modem, '--location-enable-gps-nmea'], capture_output=True, text=True, timeout=6, check=False)
        result = runner(['mmcli', '-m', modem, '--location-get'], capture_output=True, text=True, timeout=6, check=False)
        return parse_mmcli_location(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def parse_gpspipe_output(text: str) -> LocationSample | None:
    best: LocationSample | None = None
    best_mode = 0
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get('class') != 'TPV':
            continue
        try:
            mode = int(data.get('mode') or 0)
            latitude = float(data['lat'])
            longitude = float(data['lon'])
        except (KeyError, TypeError, ValueError):
            continue
        if mode < 2 or not _valid_coordinates(latitude, longitude):
            continue
        errors = []
        for key in ('epx', 'epy'):
            try:
                errors.append(abs(float(data[key])))
            except (KeyError, TypeError, ValueError):
                pass
        accuracy = max(errors) if errors else (10.0 if mode >= 3 else 50.0)
        sample = LocationSample(latitude, longitude, 'gpsd', accuracy).normalized()
        if mode > best_mode or (mode == best_mode and (best is None or (sample.accuracy_m or 1e9) < (best.accuracy_m or 1e9))):
            best = sample
            best_mode = mode
    return best


def gpsd_location(runner: Callable = subprocess.run) -> LocationSample | None:
    if not shutil.which('gpspipe'):
        return None
    try:
        result = runner(['gpspipe', '-w', '-n', '12'], capture_output=True, text=True, timeout=8, check=False)
        return parse_gpspipe_output(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def hardware_gps() -> LocationSample | None:
    return modem_gps() or gpsd_location()


def browser_geolocation(max_vpn_accuracy_m: float = 250.0, vpn_active: bool | None = None) -> LocationSample | None:
    from .browser_location import accept_browser_fix, browser_location_raw
    raw = browser_location_raw()
    if not raw or raw.get('error'):
        return None
    try:
        latitude = float(raw['latitude'])
        longitude = float(raw['longitude'])
        accuracy = float(raw['accuracy']) if raw.get('accuracy') is not None else None
    except (KeyError, TypeError, ValueError):
        return None
    if not _valid_coordinates(latitude, longitude):
        return None
    sample = LocationSample(latitude, longitude, 'browser-geolocation', accuracy).normalized()
    active = detect_vpn().active if vpn_active is None else bool(vpn_active)
    return accept_browser_fix(sample, active, max_vpn_accuracy_m)


def _valid_bssid(value: str) -> bool:
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        return False
    if value.lower() in {'ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00'}:
        return False
    first = int(value.split(':', 1)[0], 16)
    return not bool(first & 0x02)


def _signal_percent_to_dbm(percent: int) -> int:
    return max(-100, min(-10, int(round(percent / 2 - 100))))


def _iw_wifi_access_points(runner: Callable = subprocess.run, limit: int = 30) -> list[dict]:
    if not shutil.which('iw'):
        return []
    try:
        devices = runner(['iw', 'dev'], capture_output=True, text=True, timeout=4, check=False)
        interfaces = re.findall(r'^\s*Interface\s+(\S+)', devices.stdout, re.M)
        for interface in interfaces:
            scan = runner(['iw', 'dev', interface, 'scan'], capture_output=True, text=True, timeout=10, check=False)
            if scan.returncode != 0:
                continue
            points: list[dict] = []
            current: dict | None = None
            for line in scan.stdout.splitlines():
                match = re.match(r'^BSS\s+([0-9a-fA-F:]{17})\b', line.strip())
                if match:
                    if current and _valid_bssid(str(current.get('macAddress', ''))):
                        points.append(current)
                    current = {'macAddress': match.group(1).lower()}
                    continue
                if current is None:
                    continue
                signal = re.search(r'signal:\s*(-?\d+(?:\.\d+)?)\s*dBm', line)
                if signal:
                    current['signalStrength'] = int(round(float(signal.group(1))))
            if current and _valid_bssid(str(current.get('macAddress', ''))):
                points.append(current)
            unique: dict[str, dict] = {}
            for point in points:
                mac = str(point['macAddress'])
                existing = unique.get(mac)
                if existing is None or point.get('signalStrength', -200) > existing.get('signalStrength', -200):
                    unique[mac] = point
            if len(unique) >= 2:
                return sorted(unique.values(), key=lambda p: p.get('signalStrength', -200), reverse=True)[:limit]
    except Exception:
        pass
    return []


def wifi_access_points(runner: Callable = subprocess.run, limit: int = 30) -> list[dict]:
    iw_points = _iw_wifi_access_points(runner, limit)
    if len(iw_points) >= 2:
        return iw_points
    if not shutil.which('nmcli'):
        return []
    try:
        result = runner(
            ['nmcli', '-t', '--escape', 'no', '-f', 'BSSID,SIGNAL,CHAN', 'dev', 'wifi', 'list', '--rescan', 'auto'],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        seen: set[str] = set()
        out: list[dict] = []
        for line in result.stdout.splitlines():
            match = re.match(r'^((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}):(\d+):(\d+)$', line)
            if not match:
                continue
            bssid = match.group(1).lower()
            if not _valid_bssid(bssid) or bssid in seen:
                continue
            seen.add(bssid)
            percent = int(match.group(2))
            channel = int(match.group(3))
            out.append({'macAddress': bssid, 'signalStrength': _signal_percent_to_dbm(percent), 'channel': channel})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def store_wifi_location(cache_path: Path, points: list[dict], sample: LocationSample) -> None:
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.is_file() else []
    except Exception:
        data = []
    bssids = sorted({str(p.get('macAddress', '')).lower() for p in points if p.get('macAddress')})
    if len(bssids) < 2:
        return
    entry = {'bssids': bssids, 'sample': asdict(sample.normalized())}
    data = [row for row in data if set(row.get('bssids', [])) != set(bssids)]
    data.append(entry)
    data = data[-100:]
    temp = cache_path.with_name(f'.{cache_path.name}.tmp')
    temp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(cache_path)


def cached_wifi_location(cache_path: Path, points: list[dict]) -> LocationSample | None:
    cache_path = Path(cache_path)
    if not cache_path.is_file():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding='utf-8'))
    except Exception:
        return None
    observed = {str(p.get('macAddress', '')).lower() for p in points if p.get('macAddress')}
    best = None
    best_score = 0.0
    for row in data:
        known = set(row.get('bssids', []))
        overlap = len(observed & known)
        if overlap < 2:
            continue
        score = overlap / max(1, len(known | observed))
        if score > best_score:
            best_score = score
            best = row
    if best is None or best_score < 0.34:
        return None
    raw = best.get('sample') or {}
    try:
        return LocationSample(
            float(raw['latitude']),
            float(raw['longitude']),
            'wifi-cache',
            float(raw['accuracy_m']) if raw.get('accuracy_m') is not None else None,
        ).normalized()
    except Exception:
        return None


def parse_beacondb_response(data: dict) -> LocationSample | None:
    fallback = str(data.get('fallback', '')).lower()
    if fallback.startswith('ip'):
        return None
    location = data.get('location') or {}
    lat = location.get('lat')
    lon = location.get('lng')
    if lat is None or lon is None:
        return None
    try:
        latitude = float(lat)
        longitude = float(lon)
        accuracy = float(data['accuracy']) if data.get('accuracy') is not None else None
    except (TypeError, ValueError):
        return None
    if not _valid_coordinates(latitude, longitude):
        return None
    return LocationSample(latitude, longitude, 'wifi-beacondb', accuracy).normalized()


def beacondb_wifi_location(points: list[dict], timeout: float = 5.0) -> LocationSample | None:
    if len(points) < 2:
        return None
    body = json.dumps({'considerIp': False, 'wifiAccessPoints': points}).encode('utf-8')
    request = urllib.request.Request(
        'https://api.beacondb.net/v1/geolocate',
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_beacondb_response(json.load(response))
    except Exception:
        return None


def parse_mylnikov_response(data: dict) -> LocationSample | None:
    if int(data.get('result') or 0) != 200:
        return None
    payload = data.get('data') or {}
    lat = payload.get('lat', payload.get('lan'))
    lon = payload.get('lon')
    if lat is None or lon is None:
        return None
    try:
        latitude = float(lat)
        longitude = float(lon)
        accuracy = float(payload['range']) if payload.get('range') is not None else None
    except (TypeError, ValueError):
        return None
    if not _valid_coordinates(latitude, longitude):
        return None
    return LocationSample(latitude, longitude, 'wifi-mylnikov', accuracy).normalized()


def _mylnikov_batch_wifi_location(points: list[dict], timeout: float = 5.0) -> LocationSample | None:
    if len(points) < 2:
        return None
    rows = []
    for point in points[:20]:
        mac = str(point.get('macAddress', '')).lower()
        if not _valid_bssid(mac):
            continue
        signal = int(point.get('signalStrength', -70))
        rows.append(f'{mac},{signal}')
    if len(rows) < 2:
        return None
    encoded = base64.b64encode(';'.join(rows).encode('ascii')).decode('ascii')
    query = urllib.parse.urlencode({'v': '1.1', 'data': 'open', 'search': encoded})
    request = urllib.request.Request(f'https://api.mylnikov.org/geolocation/wifi?{query}', headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_mylnikov_response(json.load(response))
    except Exception:
        return None


def mylnikov_single_bssid_location(point: dict, timeout: float = 5.0) -> LocationSample | None:
    mac = str(point.get('macAddress', '')).lower()
    if not _valid_bssid(mac):
        return None
    query = urllib.parse.urlencode({'v': '1.1', 'data': 'open', 'bssid': mac})
    request = urllib.request.Request(f'https://api.mylnikov.org/geolocation/wifi?{query}', headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            sample = parse_mylnikov_response(json.load(response))
    except Exception:
        return None
    if sample is None:
        return None
    return LocationSample(sample.latitude, sample.longitude, 'wifi-mylnikov-ap', sample.accuracy_m).normalized()


def mylnikov_individual_wifi_location(points: list[dict], timeout: float = 5.0) -> tuple[LocationSample | None, int]:
    usable = [p for p in points if _valid_bssid(str(p.get('macAddress', '')).lower())][:20]
    if not usable:
        return None, 0
    samples: list[LocationSample] = []
    with ThreadPoolExecutor(max_workers=min(8, len(usable))) as pool:
        futures = [pool.submit(mylnikov_single_bssid_location, point, timeout) for point in usable]
        for future in futures:
            try:
                sample = future.result(timeout=timeout + 1)
            except Exception:
                sample = None
            if sample is not None:
                samples.append(sample)
    if not samples:
        return None, 0
    return choose_location_consensus(samples), len(samples)


def mylnikov_wifi_location(points: list[dict], timeout: float = 5.0) -> LocationSample | None:
    batch = _mylnikov_batch_wifi_location(points, timeout)
    if batch is not None:
        return batch
    sample, _matches = mylnikov_individual_wifi_location(points, timeout)
    return sample


def parse_google_response(data: dict, consider_ip: bool = False) -> LocationSample | None:
    if consider_ip:
        return None
    location = data.get('location') or {}
    if location.get('lat') is None or location.get('lng') is None:
        return None
    try:
        latitude = float(location['lat'])
        longitude = float(location['lng'])
        accuracy = float(data['accuracy']) if data.get('accuracy') is not None else None
    except (TypeError, ValueError):
        return None
    if not _valid_coordinates(latitude, longitude):
        return None
    return LocationSample(latitude, longitude, 'wifi-google', accuracy).normalized()


def _read_google_key(path: Path = DEFAULT_GOOGLE_KEY_FILE) -> str:
    try:
        return path.read_text(encoding='utf-8').strip() if path.is_file() else ''
    except OSError:
        return ''


def google_wifi_location(points: list[dict], api_key: str, timeout: float = 5.0) -> LocationSample | None:
    if len(points) < 2 or not api_key:
        return None
    body = json.dumps({'considerIp': False, 'wifiAccessPoints': points}).encode('utf-8')
    url = 'https://www.googleapis.com/geolocation/v1/geolocate?' + urllib.parse.urlencode({'key': api_key})
    request = urllib.request.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_google_response(json.load(response), consider_ip=False)
    except Exception:
        return None


def _distance_m(a: LocationSample, b: LocationSample) -> float:
    radius = 6371000.0
    lat1 = math.radians(a.latitude)
    lat2 = math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.asin(min(1.0, math.sqrt(h)))


def choose_location_consensus(samples: list[LocationSample]) -> LocationSample | None:
    valid = [s.normalized() for s in samples if _valid_coordinates(s.latitude, s.longitude)]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    groups: list[list[LocationSample]] = []
    for base in valid:
        group = [base]
        for other in valid:
            if other is base:
                continue
            threshold = max(1000.0, float(base.accuracy_m or 500) + float(other.accuracy_m or 500) + 250.0)
            if _distance_m(base, other) <= threshold:
                group.append(other)
        groups.append(group)
    groups.sort(key=lambda g: (-len(g), sum(float(x.accuracy_m or 5000) for x in g)))
    best_group = groups[0]
    if len(best_group) >= 2:
        weights = [1.0 / max(20.0, float(x.accuracy_m or 500.0)) ** 2 for x in best_group]
        total = sum(weights)
        latitude = sum(x.latitude * w for x, w in zip(best_group, weights)) / total
        longitude = sum(x.longitude * w for x, w in zip(best_group, weights)) / total
        spread = max(_distance_m(best_group[0], x) for x in best_group[1:]) if len(best_group) > 1 else 0.0
        accuracy = max(20.0, min(float(x.accuracy_m or 500.0) for x in best_group) + spread)
        return LocationSample(latitude, longitude, 'wifi-consensus', accuracy).normalized()
    ranked = sorted(valid, key=lambda s: float(s.accuracy_m or 1e9))
    if len(ranked) == 1:
        return ranked[0]
    best_accuracy = float(ranked[0].accuracy_m or 1e9)
    second_accuracy = float(ranked[1].accuracy_m or 1e9)
    if best_accuracy <= 100 and second_accuracy >= best_accuracy * 4:
        return ranked[0]
    return None


def wifi_location(
    timeout: float = 5.0,
    runner: Callable = subprocess.run,
    points: list[dict] | None = None,
    google_key_file: Path = DEFAULT_GOOGLE_KEY_FILE,
) -> LocationSample | None:
    points = points if points is not None else wifi_access_points(runner)
    if len(points) < 2:
        return None
    api_key = _read_google_key(Path(google_key_file))
    tasks: list[Callable[[], LocationSample | None]] = [
        lambda: beacondb_wifi_location(points, timeout),
        lambda: mylnikov_wifi_location(points, timeout),
    ]
    if api_key:
        tasks.append(lambda: google_wifi_location(points, api_key, timeout))
    results: list[LocationSample] = []
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [pool.submit(task) for task in tasks]
        for future in futures:
            try:
                sample = future.result(timeout=timeout + 1)
            except Exception:
                sample = None
            if sample is not None:
                results.append(sample)
    return choose_location_consensus(results)


def ip_location(timeout: float = 5.0) -> LocationSample | None:
    try:
        request = urllib.request.Request('https://ipapi.co/json/', headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        lat = data.get('latitude')
        lon = data.get('longitude')
        if lat is None or lon is None:
            return None
        latitude = float(lat)
        longitude = float(lon)
        if not _valid_coordinates(latitude, longitude):
            return None
        return LocationSample(latitude, longitude, 'ip', 25000.0).normalized()
    except Exception:
        return None


def parse_geoclue_output(text: str) -> LocationSample | None:
    lat = re.search(r'latitude\s*[:=]\s*(-?\d+(?:\.\d+)?)', text, re.I)
    lon = re.search(r'longitude\s*[:=]\s*(-?\d+(?:\.\d+)?)', text, re.I)
    acc = re.search(r'accuracy\s*[:=]\s*(\d+(?:\.\d+)?)', text, re.I)
    if not lat or not lon:
        return None
    latitude = float(lat.group(1))
    longitude = float(lon.group(1))
    if not _valid_coordinates(latitude, longitude):
        return None
    return LocationSample(latitude, longitude, 'geoclue', float(acc.group(1)) if acc else None).normalized()


def geoclue_location(runner: Callable = subprocess.run) -> LocationSample | None:
    candidates = [Path('/usr/libexec/geoclue-2.0/demos/where-am-i'), Path('/usr/lib/geoclue-2.0/demos/where-am-i')]
    executable = next((str(p) for p in candidates if p.is_file()), shutil.which('where-am-i'))
    if not executable:
        return None
    try:
        runner(['systemctl', 'start', 'geoclue.service'], capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        pass
    try:
        result = runner([executable], capture_output=True, text=True, timeout=8, check=False)
        return parse_geoclue_output(result.stdout + '\n' + result.stderr)
    except Exception:
        return None


def diagnose_location_sources(timeout: float = 5.0) -> dict:
    report: dict[str, object] = {}
    try:
        gps = hardware_gps()
    except Exception:
        gps = None
    report['gps'] = gps.source if gps is not None else 'unavailable'

    points = wifi_access_points()
    report['wifi_access_points'] = len(points)

    try:
        beacon = beacondb_wifi_location(points, timeout) if len(points) >= 2 else None
    except Exception:
        beacon = None
    report['beacondb'] = beacon.source if beacon is not None else 'no-fix'

    try:
        myl_batch = _mylnikov_batch_wifi_location(points, timeout) if len(points) >= 2 else None
    except Exception:
        myl_batch = None
    report['mylnikov_batch'] = myl_batch.source if myl_batch is not None else 'no-fix'

    try:
        myl_individual, matches = mylnikov_individual_wifi_location(points, timeout) if points else (None, 0)
    except Exception:
        myl_individual, matches = None, 0
    report['mylnikov_individual_matches'] = matches
    report['mylnikov_individual'] = myl_individual.source if myl_individual is not None else 'no-fix'

    key = _read_google_key()
    report['google'] = 'configured' if key else 'not-configured'
    if key and len(points) >= 2:
        try:
            google = google_wifi_location(points, key, timeout)
        except Exception:
            google = None
        report['google'] = google.source if google is not None else 'configured-no-fix'

    try:
        geoclue = geoclue_location()
    except Exception:
        geoclue = None
    report['geoclue'] = geoclue.source if geoclue is not None else 'no-fix'
    try:
        from .browser_location import load_browser_settings
        configured = load_browser_settings() is not None
    except Exception:
        configured = False
    if configured:
        try:
            browser = browser_geolocation(250.0, vpn_active=detect_vpn().active)
        except Exception:
            browser = None
        if browser is not None:
            accuracy = f'±{browser.accuracy_m:.0f}m' if browser.accuracy_m is not None else 'accuracy-unknown'
            report['browser_geolocation'] = f'fix {accuracy}'
        else:
            report['browser_geolocation'] = 'configured-no-fix'
    else:
        report['browser_geolocation'] = 'not-configured'
    return report


def collect_location(
    allow_ip: bool = True,
    vpn_state: VpnState | None = None,
    gps_provider: Callable[[], LocationSample | None] = hardware_gps,
    wifi_provider: Callable[..., LocationSample | None] = wifi_location,
    geoclue_provider: Callable[[], LocationSample | None] = geoclue_location,
    ip_provider: Callable[[], LocationSample | None] = ip_location,
    cache_path: Path | None = None,
    wifi_points_provider: Callable[[], list[dict]] = wifi_access_points,
    browser_provider: Callable[[], LocationSample | None] | None = None,
    browser_max_vpn_accuracy_m: float = 250.0,
    browser_enabled: bool = True,
    internet_provider: Callable[[], bool] = internet_available,
) -> LocationSample | None:
    vpn = vpn_state or detect_vpn()
    sample = gps_provider()
    if sample:
        return LocationSample(**{**asdict(sample.normalized()), 'vpn_detected': vpn.active})
    points = wifi_points_provider() if cache_path is not None else []
    try:
        online = bool(internet_provider())
    except Exception:
        online = False
    sample = None
    if online:
        try:
            sample = wifi_provider(points=points) if cache_path is not None else wifi_provider()
        except TypeError:
            sample = wifi_provider()
    if sample:
        normalized = LocationSample(**{**asdict(sample.normalized()), 'vpn_detected': vpn.active})
        if cache_path is not None and points:
            store_wifi_location(cache_path, points, normalized)
        return normalized
    if cache_path is not None and points:
        sample = cached_wifi_location(cache_path, points)
        if sample:
            return LocationSample(**{**asdict(sample.normalized()), 'vpn_detected': vpn.active})
    sample = geoclue_provider()
    if sample and (not vpn.active or (sample.accuracy_m is not None and sample.accuracy_m <= 500)):
        return LocationSample(**{**asdict(sample.normalized()), 'vpn_detected': vpn.active})
    if browser_enabled and online and (vpn.active or not IS_LINUX):
        provider = browser_provider or (lambda: browser_geolocation(browser_max_vpn_accuracy_m, vpn_active=vpn.active))
        try:
            sample = provider()
        except Exception:
            sample = None
        if sample and (not vpn.active or (sample.accuracy_m is not None and sample.accuracy_m <= browser_max_vpn_accuracy_m)):
            normalized = LocationSample(**{**asdict(sample.normalized()), 'vpn_detected': vpn.active})
            if cache_path is not None:
                if not points:
                    points = wifi_points_provider()
                if points:
                    store_wifi_location(cache_path, points, normalized)
            return normalized
    if allow_ip and not vpn.active and online:
        sample = ip_provider()
        if sample:
            return LocationSample(**{**asdict(sample.normalized()), 'vpn_detected': False})
    return None


def append_history(path: Path, sample: LocationSample) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(asdict(sample.normalized()), separators=(',', ':')) + '\n')
