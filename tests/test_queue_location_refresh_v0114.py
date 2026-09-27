from pathlib import Path

from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample


def make_settings(tmp_path: Path) -> Settings:
    secret = tmp_path / 'secret'
    secret.write_text('pw', encoding='utf-8')
    return Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
        rate_limit_seconds=0,
        mail=MailSettings(
            enabled=True,
            host='smtp.example.com',
            username='u',
            from_address='from@example.com',
            to_address='to@example.com',
            password_file=str(secret),
        ),
        capture=CaptureSettings(require_face=False),
        location=LocationSettings(enabled=True, allow_ip_fallback=False),
    )


def test_flush_refreshes_missing_location_before_sending_queued_alert(tmp_path: Path):
    sent = []
    location_calls = []

    def mail_send(settings, subject, body, attachments):
        sent.append((subject, body, list(attachments)))

    def location_collect(**kwargs):
        location_calls.append(kwargs)
        return LocationSample(10.1234, 20.5678, 'browser-geolocation', 12).normalized()

    engine = SecurityEngine(
        make_settings(tmp_path),
        camera_capture=lambda *a, **k: None,
        mail_send=mail_send,
        screenshot_capture=lambda p: None,
        location_collect=location_collect,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'event-time', 'hostname': 'test-host'},
    )
    engine.queue.enqueue(
        {
            'subject': '[LaptopGuard] manual_test on test-host',
            'body': 'LaptopGuard security alert\nLocation: unavailable',
            'metadata': {
                'event': 'manual_test',
                'timestamp': 'event-time',
                'hostname': 'test-host',
                'evidence': {'photo': True, 'screenshot': True},
            },
        },
        [],
    )

    assert engine.flush_queue() == 1
    assert len(location_calls) == 1
    assert len(sent) == 1
    subject, body, _ = sent[0]
    assert subject == '[LaptopGuard] manual_test on test-host'
    assert 'Time: event-time' in body
    assert 'Location: https://maps.google.com/?q=10.1234,20.5678' in body
    assert 'Accuracy: ±12 m' in body
    assert 'Location: unavailable' not in body
    assert engine.queue.items() == []
