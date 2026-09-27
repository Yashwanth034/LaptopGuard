from contextlib import contextmanager
from pathlib import Path

from laptopguard.auth_attempts import FailedAuthTracker
from laptopguard.camera import CaptureResult
from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample
from laptopguard.quality import FrameMetrics


class FakeBrightness:
    @contextmanager
    def boosted(self, percent=100):
        yield 35


def settings(tmp_path: Path) -> Settings:
    secret = tmp_path / 'secret'
    secret.write_text('pw')
    return Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
        rate_limit_seconds=180,
        failed_auth_threshold=3,
        failed_auth_window_seconds=120,
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


def fake_capture(path: Path, **kwargs):
    path.write_bytes(b'photo')
    return CaptureResult(path, FrameMetrics(90, 150, 0), 3)


def make_engine(tmp_path: Path, *, sent=None, captures=None, screenshots=None, locations=None):
    sent = sent if sent is not None else []
    captures = captures if captures is not None else []
    screenshots = screenshots if screenshots is not None else []
    locations = locations if locations is not None else []

    def capture(path: Path, **kwargs):
        captures.append(Path(path).name)
        return fake_capture(path, **kwargs)

    def mail(settings, subject, body, attachments):
        sent.append([Path(p).name for p in attachments])

    def screenshot(path: Path):
        screenshots.append(path)
        path.write_bytes(b'screen')
        return path

    def location(**kwargs):
        locations.append(kwargs)
        return LocationSample(17.3, 78.4, 'test').normalized()

    return SecurityEngine(
        settings(tmp_path),
        camera_capture=capture,
        mail_send=mail,
        screenshot_capture=screenshot,
        location_collect=location,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        brightness_factory=FakeBrightness,
    )


def test_first_local_failure_does_absolutely_nothing(tmp_path: Path):
    sent, captures, screenshots, locations = [], [], [], []
    engine = make_engine(
        tmp_path,
        sent=sent,
        captures=captures,
        screenshots=screenshots,
        locations=locations,
    )

    result = engine.handle_event('failed_auth')

    assert result.delivery == 'ignored-first-attempt'
    assert result.photo_captured is False
    assert result.location_captured is False
    assert sent == []
    assert captures == []
    assert screenshots == []
    assert locations == []
    assert engine.tracking_active() is False


def test_second_local_failure_does_absolutely_nothing(tmp_path: Path):
    sent, captures, screenshots, locations = [], [], [], []
    engine = make_engine(
        tmp_path,
        sent=sent,
        captures=captures,
        screenshots=screenshots,
        locations=locations,
    )

    first = engine.handle_event('failed_auth')
    second = engine.handle_event('failed_auth')

    assert first.delivery == 'ignored-first-attempt'
    assert second.delivery == 'ignored-second-attempt'
    assert second.photo_captured is False
    assert second.location_captured is False
    assert captures == []
    assert sent == []
    assert screenshots == []
    assert locations == []
    assert engine.tracking_active() is False


def test_third_local_failure_sends_full_alert_only_on_third_attempt(tmp_path: Path):
    sent, captures, screenshots, locations = [], [], [], []
    engine = make_engine(
        tmp_path,
        sent=sent,
        captures=captures,
        screenshots=screenshots,
        locations=locations,
    )

    first = engine.handle_event('failed_auth')
    second = engine.handle_event('failed_auth')
    third = engine.handle_event('failed_auth')

    assert first.delivery == 'ignored-first-attempt'
    assert second.delivery == 'ignored-second-attempt'
    assert third.delivery == 'sent'
    assert third.photo_captured is True
    assert third.location_captured is True
    assert captures == ['photo.jpg']
    assert len(sent) == 1
    assert set(sent[0]) == {'photo.jpg', 'screenshot.png'}
    assert len(screenshots) == 1
    assert len(locations) == 1
    assert engine.tracking_active() is False


def test_failed_auth_counter_expires_after_window_before_third_attempt(tmp_path: Path):
    now = [100.0]
    tracker = FailedAuthTracker(tmp_path / 'failed-auth.json', threshold=3, window_seconds=120, clock=lambda: now[0])

    first = tracker.register()
    second = tracker.register()
    now[0] += 121
    third = tracker.register()

    assert first.count == 1 and first.trigger is False
    assert second.count == 2 and second.trigger is False
    assert third.count == 1 and third.trigger is False


def test_legacy_second_attempt_photo_is_removed_without_new_capture(tmp_path: Path):
    sent, captures, screenshots, locations = [], [], [], []
    engine = make_engine(
        tmp_path, sent=sent, captures=captures, screenshots=screenshots, locations=locations
    )
    engine.pending_auth_photo.write_bytes(b'legacy-photo')

    first = engine.handle_event('failed_auth')
    second = engine.handle_event('failed_auth')

    assert first.delivery == 'ignored-first-attempt'
    assert second.delivery == 'ignored-second-attempt'
    assert not engine.pending_auth_photo.exists()
    assert captures == []
    assert sent == []
    assert screenshots == []
    assert locations == []

def test_third_attempt_alert_mentions_one_photo():
    from laptopguard.alerts import format_alert

    _, body = format_alert({
        'event': 'failed_auth',
        'timestamp': 'now',
        'hostname': 'test',
        'evidence': {'prior_attempt_photo': False, 'photo': True, 'screenshot': True},
    })

    assert 'Photo: attached' in body
    assert 'Photos: 2 attached' not in body
