from pathlib import Path

from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample


def _settings(tmp_path: Path) -> Settings:
    secret = tmp_path / 'smtp-password'
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
        capture=CaptureSettings(max_seconds=0.1, require_face=False),
        location=LocationSettings(enabled=True, allow_ip_fallback=False),
    )


class CaptureResult:
    frames_seen = 1

    class metrics:
        brightness = 80
        sharpness = 120
        faces = 1


def _capture(path, **kwargs):
    Path(path).write_bytes(b'photo')
    return CaptureResult()


def test_shutdown_sends_fast_mail_before_slow_location(tmp_path: Path, monkeypatch):
    calls = []
    import laptopguard.engine as engine_module
    monkeypatch.setattr(engine_module, 'active_ssid', lambda timeout=5.0: 'fast-wifi')

    def location(**kwargs):
        calls.append('location')
        return LocationSample(17.3, 78.4, 'test').normalized()

    def mail(settings, subject, body, attachments):
        calls.append('mail')
        assert 'Wi-Fi: fast-wifi' in body

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=_capture,
        screenshot_capture=lambda path: None,
        metadata_factory=lambda event: {
            'event': event,
            'timestamp': 'now',
            'hostname': 'test',
            'wifi_ssid': 'wifi',
        },
        location_collect=location,
        mail_send=mail,
    )

    result = engine.handle_event('login_screen_shutdown')

    assert result.delivery == 'sent'
    assert calls[0] == 'mail'
    assert 'location' not in calls
    assert result.location_captured is False
    assert engine.queue.items() == []


def test_shutdown_mail_failure_keeps_queue_and_then_enriches_location(tmp_path: Path, monkeypatch):
    calls = []
    import laptopguard.engine as engine_module
    monkeypatch.setattr(engine_module, 'active_ssid', lambda timeout=5.0: 'fast-wifi')

    def location(**kwargs):
        calls.append('location')
        return LocationSample(17.3, 78.4, 'test').normalized()

    def mail(settings, subject, body, attachments):
        calls.append('mail')
        raise OSError('network disappeared during shutdown')

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=_capture,
        screenshot_capture=lambda path: None,
        metadata_factory=lambda event: {
            'event': event,
            'timestamp': 'now',
            'hostname': 'test',
            'wifi_ssid': 'wifi',
        },
        location_collect=location,
        mail_send=mail,
    )

    result = engine.handle_event('login_screen_shutdown')

    assert result.delivery == 'queued'
    assert calls == ['mail', 'location']
    assert result.location_captured is True
    assert len(engine.queue.items()) == 1
    payload, _files = engine.queue.read(engine.queue.items()[0])
    assert payload['metadata']['location']['latitude'] == 17.3
    assert payload['metadata']['location']['longitude'] == 78.4
