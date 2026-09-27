from contextlib import contextmanager
from pathlib import Path

from laptopguard.camera import CaptureResult
from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.quality import FrameMetrics
from laptopguard.location import LocationSample


class FakeBrightness:
    @contextmanager
    def boosted(self, percent=100):
        yield 35


def make_settings(tmp_path: Path, mail_enabled=True):
    secret = tmp_path / 'secret'
    secret.write_text('pw')
    return Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
        rate_limit_seconds=0,
        mail=MailSettings(
            enabled=mail_enabled,
            host='smtp.example.com',
            username='u',
            from_address='from@example.com',
            to_address='to@example.com',
            password_file=str(secret),
        ),
        capture=CaptureSettings(max_seconds=0.1, require_face=False),
        location=LocationSettings(enabled=True, allow_ip_fallback=False),
    )


def test_engine_sends_good_capture(tmp_path: Path):
    sent = []

    def fake_capture(path, **kwargs):
        path.write_bytes(b'photo')
        return CaptureResult(path, FrameMetrics(90, 150, 0), 3)

    def fake_mail(settings, subject, body, attachments):
        sent.append((subject, list(attachments)))

    engine = SecurityEngine(
        make_settings(tmp_path),
        camera_capture=fake_capture,
        mail_send=fake_mail,
        screenshot_capture=lambda p: None,
        location_collect=lambda **kwargs: LocationSample(17.3, 78.4, 'test').normalized(),
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        brightness_factory=FakeBrightness,
    )
    first = engine.handle_event('failed_auth')
    second = engine.handle_event('failed_auth')
    result = engine.handle_event('failed_auth')
    assert first.delivery == 'ignored-first-attempt'
    assert second.delivery == 'ignored-second-attempt'
    assert result.delivery == 'sent'
    assert len(sent) == 1
    assert engine.queue.items() == []


def test_engine_queues_when_mail_fails(tmp_path: Path):
    def fake_capture(path, **kwargs):
        path.write_bytes(b'photo')
        return CaptureResult(path, FrameMetrics(90, 150, 0), 3)

    def failing_mail(*args, **kwargs):
        raise OSError('offline')

    engine = SecurityEngine(
        make_settings(tmp_path),
        camera_capture=fake_capture,
        mail_send=failing_mail,
        screenshot_capture=lambda p: None,
        location_collect=lambda **kwargs: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        brightness_factory=FakeBrightness,
    )
    first = engine.handle_event('failed_auth')
    second = engine.handle_event('failed_auth')
    result = engine.handle_event('failed_auth')
    assert first.delivery == 'ignored-first-attempt'
    assert second.delivery == 'ignored-second-attempt'
    assert result.delivery == 'queued'
    assert len(engine.queue.items()) == 1


def test_rate_limited_event_is_still_recorded_locally(tmp_path: Path):
    settings = make_settings(tmp_path, mail_enabled=False)
    settings = Settings(
        state_dir=settings.state_dir,
        evidence_dir=settings.evidence_dir,
        queue_dir=settings.queue_dir,
        rate_limit_seconds=999,
        mail=settings.mail,
        capture=settings.capture,
        location=settings.location,
    )
    engine = SecurityEngine(
        settings,
        camera_capture=lambda *a, **k: None,
        screenshot_capture=lambda p: None,
        location_collect=lambda **k: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        brightness_factory=FakeBrightness,
    )
    first = engine.handle_event('failed_auth')
    second = engine.handle_event('failed_auth')
    third = engine.handle_event('failed_auth')
    fourth = engine.handle_event('failed_auth')
    fifth = engine.handle_event('failed_auth')
    result = engine.handle_event('failed_auth')
    assert first.delivery == 'ignored-first-attempt'
    assert second.delivery == 'ignored-second-attempt'
    assert third.delivery == 'queued'
    assert fourth.delivery == 'ignored-first-attempt'
    assert fifth.delivery == 'ignored-second-attempt'
    assert result.delivery == 'rate-limited'
    lines = (Path(settings.state_dir) / 'event-history.jsonl').read_text().splitlines()
    assert len(lines) == 6
