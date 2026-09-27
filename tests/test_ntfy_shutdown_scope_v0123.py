from __future__ import annotations

from pathlib import Path
import time

from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, PushSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample


def _settings(tmp_path: Path) -> Settings:
    secret = tmp_path / 'smtp-password'
    secret.write_text('pw', encoding='utf-8')
    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
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
        push=PushSettings(topic_file=str(topic_file)),
    )


class CaptureResult:
    frames_seen = 1

    class metrics:
        brightness = 80
        sharpness = 120
        faces = 1


def _capture(path, **kwargs):
    Path(path).write_bytes(b'jpeg-evidence')
    return CaptureResult()


def test_ntfy_photo_publish_sends_jpeg_bytes_and_location_in_message(tmp_path: Path):
    from laptopguard.push import send_notification

    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'jpeg-evidence')
    seen = {}

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        seen['body'] = request.data
        seen['message'] = request.get_header('Message')
        seen['filename'] = request.get_header('Filename')
        seen['content_type'] = request.get_header('Content-type')
        return Response()

    send_notification(
        'laptopguard-0123456789abcdef',
        event='lockscreen_shutdown',
        timestamp='2026-09-15T17:00:00+00:00',
        hostname='mint-laptop',
        photo_captured=True,
        location_captured=True,
        photo_path=photo,
        location={
            'latitude': 17.3,
            'longitude': 78.4,
            'accuracy_m': 12.0,
            'source': 'browser-geolocation',
        },
        opener=opener,
    )

    assert seen['body'] == b'jpeg-evidence'
    assert seen['filename'] == 'photo.jpg'
    assert seen['content_type'] == 'image/jpeg'
    assert 'Event: lockscreen_shutdown' in seen['message']
    assert 'Location: https://maps.google.com/?q=17.3,78.4' in seen['message']
    assert 'Accuracy: ±12 m' in seen['message']


def test_protected_shutdown_push_receives_photo_and_location_before_gmail_queue_flush(tmp_path: Path):
    from laptopguard.push import mark_enabled

    settings = _settings(tmp_path)
    mark_enabled(Path(settings.state_dir), 'laptopguard-0123456789abcdef')
    pushes = []
    immediate_mail = []

    def screenshot(path):
        Path(path).write_bytes(b'screen')
        return Path(path)

    engine = SecurityEngine(
        settings,
        camera_capture=_capture,
        screenshot_capture=screenshot,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'mint-laptop'},
        location_collect=lambda **kwargs: LocationSample(17.3, 78.4, 'browser-geolocation', 12).normalized(),
        mail_send=lambda *args, **kwargs: immediate_mail.append('mail'),
        shutdown_mail_send=lambda *args, **kwargs: immediate_mail.append('shutdown-mail'),
        push_send=lambda topic, **kwargs: pushes.append(kwargs),
    )

    result = engine.handle_event('login_screen_shutdown')

    assert result.delivery == 'pushed'
    assert len(pushes) == 1
    assert Path(pushes[0]['photo_path']).name == 'photo.jpg'
    assert pushes[0]['location']['latitude'] == 17.3
    assert pushes[0]['location']['longitude'] == 78.4
    assert immediate_mail == []
    assert len(engine.queue.items()) == 1
    payload, files = engine.queue.read(engine.queue.items()[0])
    assert payload['metadata']['location']['latitude'] == 17.3
    assert set(files) == {'photo.jpg', 'screenshot.png'}


def test_legacy_normal_shutdown_and_reboot_event_names_are_ignored(tmp_path: Path):
    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('camera must not run')),
        screenshot_capture=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('screenshot must not run')),
        location_collect=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('location must not run')),
        mail_send=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('mail must not run')),
        push_send=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('push must not run')),
    )

    for event in ('shutdown', 'reboot_shutdown'):
        result = engine.handle_event(event)
        assert result.delivery == 'ignored-lifecycle'
        assert result.photo_captured is False
        assert result.location_captured is False


def test_x11_screenshot_prefers_scrot_and_never_invokes_gnome_screenshot(tmp_path: Path, monkeypatch):
    from laptopguard.evidence import capture_screenshot
    from laptopguard.session import ActiveSession
    import laptopguard.evidence as evidence

    target = tmp_path / 'screenshot.png'
    session = ActiveSession('2', 'alice', 1000, 'x11', ':0', '/run/user/1000')
    commands = []

    def which(name):
        if name in {'scrot', 'gnome-screenshot'}:
            return f'/usr/bin/{name}'
        return None

    class Result:
        returncode = 0

    def runner(args, **kwargs):
        commands.append(args)
        source = Path(args[-1])
        source.write_bytes(b'png')
        return Result()

    monkeypatch.setattr(evidence.shutil, 'which', which)
    result = capture_screenshot(target, session_provider=lambda: session, runner=runner)

    assert result == target
    assert len(commands) == 1
    assert 'scrot' in commands[0]
    assert 'gnome-screenshot' not in commands[0]


def test_five_second_deadline_does_not_force_five_second_wait():
    from laptopguard.shutdown_guard import run_with_deadline

    started = time.monotonic()
    completed, value = run_with_deadline(lambda: 'done', timeout=5.0)
    elapsed = time.monotonic() - started

    assert completed is True
    assert value == 'done'
    assert elapsed < 0.25


def test_shutdown_photo_retry_stays_silent_without_brightness_or_white_screen(tmp_path: Path):
    calls = []

    def capture(path, **kwargs):
        calls.append(kwargs['max_seconds'])
        if len(calls) == 1:
            return None
        Path(path).write_bytes(b'jpeg-evidence')
        return CaptureResult()

    def visible_effect(*args, **kwargs):
        raise AssertionError('shutdown capture must not flash/brighten the display')

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=capture,
        brightness_factory=visible_effect,
        illuminator_factory=visible_effect,
        screenshot_capture=lambda path: None,
        location_collect=lambda **kwargs: None,
        mail_send=lambda *args, **kwargs: None,
        shutdown_mail_send=lambda *args, **kwargs: (_ for _ in ()).throw(OSError('offline')),
    )

    result = engine.handle_event('lockscreen_shutdown')

    assert result.photo_captured is True
    assert len(calls) == 2


def test_shutdown_push_uses_recent_last_known_location_if_live_probe_is_too_slow(tmp_path: Path):
    from dataclasses import asdict
    from datetime import datetime, timezone
    import json
    import threading
    from laptopguard.push import mark_enabled

    settings = _settings(tmp_path)
    mark_enabled(Path(settings.state_dir), 'laptopguard-0123456789abcdef')
    state = Path(settings.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    recent = LocationSample(
        17.31,
        78.41,
        'browser-geolocation',
        15,
        datetime.now(timezone.utc).isoformat(),
        'high',
        True,
    )
    (state / 'location-history.jsonl').write_text(json.dumps(asdict(recent)) + '\n', encoding='utf-8')

    blocker = threading.Event()
    pushes = []

    def slow_location(**kwargs):
        blocker.wait(5)
        return None

    engine = SecurityEngine(
        settings,
        camera_capture=_capture,
        screenshot_capture=lambda path: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'mint-laptop'},
        location_collect=slow_location,
        mail_send=lambda *args, **kwargs: None,
        push_send=lambda topic, **kwargs: pushes.append(kwargs),
    )

    started = time.monotonic()
    result = engine.handle_event('lockscreen_shutdown')
    elapsed = time.monotonic() - started
    blocker.set()

    assert result.delivery == 'pushed'
    assert elapsed < 2.0
    assert pushes[0]['location']['latitude'] == 17.31
    assert pushes[0]['location']['longitude'] == 78.41
    assert pushes[0]['location']['source'].startswith('last-known:')
