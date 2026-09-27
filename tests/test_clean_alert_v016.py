from pathlib import Path

from laptopguard.alerts import format_alert
from laptopguard.camera import CaptureResult
from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample
from laptopguard.quality import FrameMetrics


def test_alert_is_compact_and_contains_only_useful_summary():
    metadata = {
        'event': 'failed_auth',
        'timestamp': '2026-09-15T04:00:00+00:00',
        'hostname': 'laptop',
        'wifi_ssid': 'HomeWiFi',
        'location': {'latitude': 17.3, 'longitude': 78.4, 'accuracy_m': 35, 'source': 'browser-geolocation'},
        'network': {'vpn': {'active': True, 'interfaces': ['tun0'], 'types': ['vpn']}},
        'sequence': 99,
        'evidence': {'photo': True, 'screenshot': True},
    }
    _, body = format_alert(metadata)
    assert 'Wi-Fi: HomeWiFi' in body
    assert 'https://maps.google.com/?q=17.3,78.4' in body
    assert 'Accuracy: ±35 m' in body
    assert 'Photo: attached' in body
    assert 'Screenshot: attached' in body
    assert 'VPN:' not in body
    assert 'Event sequence:' not in body
    assert 'integrity hashes' not in body


def test_engine_emails_only_photo_and_screenshot_not_metadata_file(tmp_path: Path):
    secret = tmp_path / 'secret'
    secret.write_text('pw')
    settings = Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
        rate_limit_seconds=0,
        mail=MailSettings(True, 'smtp.example.com', 465, 'u@example.com', 'u@example.com', 'u@example.com', str(secret), True),
        capture=CaptureSettings(max_seconds=0.1, require_face=False),
        location=LocationSettings(enabled=True, allow_ip_fallback=False),
    )
    sent = []

    def capture(path, **kwargs):
        path.write_bytes(b'photo')
        return CaptureResult(path, FrameMetrics(80, 100, 1), 1)

    def screenshot(path):
        path.write_bytes(b'screen')
        return path

    def mail_send(_settings, _subject, _body, attachments):
        sent.extend(Path(p).name for p in attachments)

    engine = SecurityEngine(
        settings,
        camera_capture=capture,
        screenshot_capture=screenshot,
        mail_send=mail_send,
        location_collect=lambda **kwargs: LocationSample(17.3, 78.4, 'test', 25).normalized(),
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test', 'wifi_ssid': 'HomeWiFi'},
    )
    result = engine.handle_event('manual_test')
    assert result.delivery == 'sent'
    assert sorted(sent) == ['photo.jpg', 'screenshot.png']
