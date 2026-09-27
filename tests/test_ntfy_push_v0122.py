from __future__ import annotations

import os
from pathlib import Path
import time

import pytest

from laptopguard.cli import build_parser
from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample


def _settings(tmp_path: Path, push_topic_file: Path | None = None) -> Settings:
    from laptopguard.config import PushSettings

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
        push=PushSettings(topic_file=str(push_topic_file or (tmp_path / 'ntfy-topic'))),
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


def test_cli_parses_configure_push_topic_and_test_push():
    configured = build_parser().parse_args(['configure-push', 'laptopguard-0123456789abcdef'])
    tested = build_parser().parse_args(['test-push'])
    assert configured.command == 'configure-push'
    assert configured.topic == 'laptopguard-0123456789abcdef'
    assert tested.command == 'test-push'


def test_validate_topic_accepts_private_name_and_rejects_urls_or_unsafe_values():
    from laptopguard.push import validate_topic

    assert validate_topic('laptopguard-0123456789abcdef') == 'laptopguard-0123456789abcdef'
    for bad in ('', '   ', 'https://ntfy.sh/secret', 'http://ntfy.sh/secret', 'short', 'bad/topic', 'bad topic'):
        with pytest.raises(ValueError):
            validate_topic(bad)


def test_configure_push_stores_root_only_topic_preserves_email_config_and_disables_until_retested(tmp_path: Path):
    from laptopguard.push import configure_topic, mark_enabled, is_enabled

    config = tmp_path / 'config.toml'
    original = '[mail]\nenabled = true\nhost = "smtp.example.com"\nusername = "owner@example.com"\n'
    config.write_text(original, encoding='utf-8')
    topic_file = tmp_path / 'ntfy-topic'
    state_dir = tmp_path / 'state'
    mark_enabled(state_dir, 'laptopguard-0123456789abcdef')
    assert is_enabled(state_dir, topic_file) is False

    configure_topic(topic_file, state_dir, 'laptopguard-0123456789abcdef')

    assert config.read_text(encoding='utf-8') == original
    assert topic_file.read_text(encoding='utf-8').strip() == 'laptopguard-0123456789abcdef'
    assert oct(topic_file.stat().st_mode & 0o777) == '0o600'
    assert is_enabled(state_dir, topic_file) is False


def test_ntfy_http_post_is_small_and_contains_required_shutdown_fields():
    from laptopguard.push import send_notification

    seen = {}

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        seen['url'] = request.full_url
        seen['body'] = request.data.decode('utf-8')
        seen['title'] = request.get_header('Title')
        seen['timeout'] = timeout
        return Response()

    send_notification(
        'laptopguard-0123456789abcdef',
        event='reboot_shutdown',
        timestamp='2026-09-15T22:30:00+05:30',
        hostname='mint-laptop',
        photo_captured=True,
        location_captured=False,
        opener=opener,
        timeout=2.0,
    )

    assert seen['url'] == 'https://ntfy.sh/laptopguard-0123456789abcdef'
    assert seen['title'] == 'LaptopGuard Security Alert'
    assert 'Event: reboot_shutdown' in seen['body']
    assert 'Timestamp: 2026-09-15T22:30:00+05:30' in seen['body']
    assert 'Hostname: mint-laptop' in seen['body']
    assert 'Photo evidence: yes' in seen['body']
    assert 'Location evidence: no' in seen['body']
    assert len(seen['body'].encode('utf-8')) < 1024


def test_test_push_activates_only_after_success_and_does_not_use_security_engine(tmp_path: Path):
    from laptopguard.push import run_test, is_enabled

    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    settings = _settings(tmp_path, topic_file)
    calls = []

    def sender(topic, **kwargs):
        calls.append((topic, kwargs))

    assert run_test(settings, sender=sender) is True
    assert len(calls) == 1
    assert calls[0][1]['event'] == 'push_test'
    assert calls[0][1]['photo_captured'] is False
    assert calls[0][1]['location_captured'] is False
    assert is_enabled(Path(settings.state_dir), topic_file) is True


def test_test_push_failure_does_not_activate(tmp_path: Path):
    from laptopguard.push import run_test, is_enabled

    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    settings = _settings(tmp_path, topic_file)

    def fail(*args, **kwargs):
        raise OSError('ntfy unavailable')

    assert run_test(settings, sender=fail) is False
    assert is_enabled(Path(settings.state_dir), topic_file) is False


def test_push_activation_does_not_expand_shutdown_or_reboot_scope():
    from laptopguard.shutdown_guard import shutdown_event_for_signal

    for push_enabled in (False, True):
        assert shutdown_event_for_signal(
            True, {'type': 'poweroff'}, locked=True, login_screen=False, push_enabled=push_enabled
        ) == 'lockscreen_shutdown'
        assert shutdown_event_for_signal(
            True, {'type': 'poweroff'}, locked=False, login_screen=True, push_enabled=push_enabled
        ) == 'login_screen_shutdown'
        assert shutdown_event_for_signal(
            True, {'type': 'poweroff'}, locked=False, login_screen=False, push_enabled=push_enabled
        ) is None
        assert shutdown_event_for_signal(
            True, {'type': 'reboot'}, locked=True, login_screen=False, push_enabled=push_enabled
        ) is None
        assert shutdown_event_for_signal(
            True, {'type': 'reboot'}, locked=False, login_screen=True, push_enabled=push_enabled
        ) is None

def test_push_mode_success_sends_ntfy_with_photo_and_location_and_keeps_gmail_queue(tmp_path: Path, monkeypatch):
    import laptopguard.engine as engine_module
    from laptopguard.push import mark_enabled

    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    settings = _settings(tmp_path, topic_file)
    mark_enabled(Path(settings.state_dir), 'laptopguard-0123456789abcdef')
    monkeypatch.setattr(engine_module, 'active_ssid', lambda timeout=5.0: 'fast-wifi')
    calls = []

    def push(topic, **kwargs):
        if kwargs.get('photo_path') is not None:
            kwargs = dict(kwargs)
            kwargs['photo_bytes'] = Path(kwargs['photo_path']).read_bytes()
        calls.append(('push', topic, kwargs))

    def mail(*args, **kwargs):
        calls.append(('mail',))

    def screenshot(path):
        Path(path).write_bytes(b'screen')
        return Path(path)

    engine = SecurityEngine(
        settings,
        camera_capture=_capture,
        screenshot_capture=screenshot,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        location_collect=lambda **kwargs: LocationSample(17.3, 78.4, 'test', 12).normalized(),
        mail_send=mail,
        push_send=push,
    )

    result = engine.handle_event('lockscreen_shutdown')

    assert result.delivery == 'pushed'
    assert [call[0] for call in calls] == ['push']
    kwargs = calls[0][2]
    assert kwargs['photo_bytes'] == b'photo'
    assert kwargs['location']['latitude'] == 17.3
    assert kwargs['location']['longitude'] == 78.4
    assert len(engine.queue.items()) == 1
    payload, files = engine.queue.read(engine.queue.items()[0])
    assert payload['metadata']['event'] == 'lockscreen_shutdown'
    assert payload['metadata']['location']['latitude'] == 17.3
    assert files['photo.jpg'] == b'photo'
    assert files['screenshot.png'] == b'screen'

def test_push_failure_never_attempts_shutdown_gmail_and_keeps_enriched_queue_for_boot(tmp_path: Path, monkeypatch):
    import laptopguard.engine as engine_module
    from laptopguard.push import mark_enabled

    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    settings = _settings(tmp_path, topic_file)
    mark_enabled(Path(settings.state_dir), 'laptopguard-0123456789abcdef')
    monkeypatch.setattr(engine_module, 'active_ssid', lambda timeout=5.0: 'fast-wifi')
    calls = []

    def fail_push(*args, **kwargs):
        calls.append('push')
        raise OSError('ntfy unavailable')

    def shutdown_mail(*args, **kwargs):
        calls.append('shutdown-mail')
        raise AssertionError('Gmail must not be attempted during push-mode shutdown')

    def location(**kwargs):
        calls.append('location')
        return LocationSample(17.3, 78.4, 'test').normalized()

    def screenshot(path):
        Path(path).write_bytes(b'screen')
        return Path(path)

    engine = SecurityEngine(
        settings,
        camera_capture=_capture,
        screenshot_capture=screenshot,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        location_collect=location,
        mail_send=lambda *args, **kwargs: None,
        shutdown_mail_send=shutdown_mail,
        push_send=fail_push,
    )

    result = engine.handle_event('lockscreen_shutdown')

    assert result.delivery == 'queued'
    assert 'shutdown-mail' not in calls
    assert calls.count('push') == 1
    assert calls.count('location') == 1
    assert len(engine.queue.items()) == 1
    payload, files = engine.queue.read(engine.queue.items()[0])
    assert payload['metadata']['event'] == 'lockscreen_shutdown'
    assert payload['metadata']['location']['latitude'] == 17.3
    assert files['photo.jpg'] == b'photo'
    assert files['screenshot.png'] == b'screen'
    assert payload['metadata']['evidence']['screenshot'] is True

def test_boot_flush_sends_successful_push_evidence_by_existing_gmail_path(tmp_path: Path):
    from laptopguard.push import mark_enabled

    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    settings = _settings(tmp_path, topic_file)
    mark_enabled(Path(settings.state_dir), 'laptopguard-0123456789abcdef')
    sent = []

    def screenshot(path):
        Path(path).write_bytes(b'screen')
        return Path(path)

    engine = SecurityEngine(
        settings,
        camera_capture=_capture,
        screenshot_capture=screenshot,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        location_collect=lambda **kwargs: LocationSample(17.3, 78.4, 'test').normalized(),
        mail_send=lambda settings, subject, body, attachments: sent.append((subject, body, [Path(p).name for p in attachments])),
        push_send=lambda *args, **kwargs: None,
    )
    first = engine.handle_event('lockscreen_shutdown')
    assert first.delivery == 'pushed'
    assert len(engine.queue.items()) == 1

    boot = engine.handle_event('boot')

    assert boot.delivery == 'readiness-only'
    assert len(sent) == 1
    assert set(sent[0][2]) == {'photo.jpg', 'screenshot.png'}
    assert 'Location: https://maps.google.com/?q=17.3,78.4' in sent[0][1]
    assert engine.queue.items() == []

def test_shutdown_deadline_returns_without_waiting_for_slow_push_work():
    from laptopguard.shutdown_guard import run_with_deadline
    def slow_action():
        time.sleep(0.25)
        return 'too-late'

    started = time.monotonic()
    completed, value = run_with_deadline(slow_action, timeout=0.03)
    elapsed = time.monotonic() - started

    assert completed is False
    assert value is None
    assert elapsed < 0.15


def test_shutdown_guard_does_nothing_for_unlocked_poweroff_or_reboot_even_with_push_enabled(monkeypatch, tmp_path: Path):
    import laptopguard.shutdown_guard as guard

    handled = []
    signals = [{'type': 'poweroff'}, {'type': 'reboot'}]

    class FakeEngine:
        def __init__(self, settings):
            pass

        def push_enabled(self):
            return True

        def handle_event(self, name):
            handled.append(name)
            raise AssertionError('normal shutdown/reboot must not trigger a security event')

    monkeypatch.setattr(guard, 'SecurityEngine', FakeEngine)
    monkeypatch.setattr(guard, '_start_user_lock_state_watcher', lambda tracker, stop_event: None)

    def fake_subscribe(on_signal, tracker):
        for metadata in signals:
            on_signal(True, metadata)

    monkeypatch.setattr(guard, '_subscribe_and_wait', fake_subscribe)
    settings = _settings(tmp_path)

    guard.run(settings, lock_checker=lambda: False, login_screen_checker=lambda: False)

    assert handled == []

def test_cli_configure_push_preserves_config_and_does_not_print_topic(monkeypatch, tmp_path: Path, capsys):
    import laptopguard.cli as cli

    monkeypatch.setattr(cli.os, 'geteuid', lambda: 0)
    topic_file = tmp_path / 'ntfy-topic'
    config = tmp_path / 'config.toml'
    config.write_text(
        f'state_dir = "{tmp_path / "state"}"\n'
        f'evidence_dir = "{tmp_path / "evidence"}"\n'
        f'queue_dir = "{tmp_path / "queue"}"\n\n'
        '[mail]\nenabled = true\nhost = "smtp.example.com"\nusername = "owner@example.com"\n\n'
        f'[push]\ntopic_file = "{topic_file}"\n',
        encoding='utf-8',
    )
    original = config.read_bytes()
    topic = 'laptopguard-0123456789abcdef'

    rc = cli.main(['--config', str(config), 'configure-push', topic])

    captured = capsys.readouterr()
    assert rc == 0
    assert config.read_bytes() == original
    assert topic_file.read_text(encoding='utf-8').strip() == topic
    assert oct(topic_file.stat().st_mode & 0o777) == '0o600'
    assert topic not in captured.out
    assert topic not in captured.err


def test_cli_test_push_path_does_not_construct_security_engine(monkeypatch, tmp_path: Path):
    import laptopguard.cli as cli

    monkeypatch.setattr(cli.os, 'geteuid', lambda: 0)
    topic_file = tmp_path / 'ntfy-topic'
    topic_file.write_text('laptopguard-0123456789abcdef\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    config = tmp_path / 'config.toml'
    config.write_text(
        f'state_dir = "{tmp_path / "state"}"\n'
        f'evidence_dir = "{tmp_path / "evidence"}"\n'
        f'queue_dir = "{tmp_path / "queue"}"\n\n'
        f'[push]\ntopic_file = "{topic_file}"\n',
        encoding='utf-8',
    )
    calls = []

    monkeypatch.setattr(cli, 'run_push_test', lambda settings: calls.append(settings) or True, raising=False)
    monkeypatch.setattr(cli, 'SecurityEngine', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('engine must not be created')))

    rc = cli.main(['--config', str(config), 'test-push'])

    assert rc == 0
    assert len(calls) == 1


def test_cli_rejects_full_url_without_echoing_secret(monkeypatch, tmp_path: Path, capsys):
    import laptopguard.cli as cli

    config = tmp_path / 'config.toml'
    config.write_text(f'state_dir = "{tmp_path / "state"}"\n', encoding='utf-8')
    bad = 'https://ntfy.sh/laptopguard-secret-0123456789'

    rc = cli.main(['--config', str(config), 'configure-push', bad])

    captured = capsys.readouterr()
    assert rc == 2
    assert bad not in captured.out
    assert bad not in captured.err


def test_shutdown_guard_uses_five_seconds_as_a_maximum_only_for_protected_poweroff(monkeypatch, tmp_path: Path):
    import laptopguard.shutdown_guard as guard

    seen = []

    class FakeEngine:
        def __init__(self, settings):
            pass

        def push_enabled(self):
            return True

        def handle_event(self, name):
            assert name == 'lockscreen_shutdown'
            class Result:
                delivery = 'pushed'
                photo_captured = True
                location_captured = True
            return Result()

    def fake_deadline(action, timeout):
        seen.append(timeout)
        return True, action()

    monkeypatch.setattr(guard, 'SecurityEngine', FakeEngine)
    monkeypatch.setattr(guard, 'run_with_deadline', fake_deadline)
    monkeypatch.setattr(guard, '_start_user_lock_state_watcher', lambda tracker, stop_event: None)
    monkeypatch.setattr(guard, '_subscribe_and_wait', lambda on_signal, tracker: on_signal(True, {'type': 'poweroff'}))

    guard.run(_settings(tmp_path), lock_checker=lambda: True, login_screen_checker=lambda: False)

    assert seen == [5.0]

def test_push_activation_is_bound_to_the_exact_tested_topic(tmp_path: Path):
    from laptopguard.push import is_enabled, run_test

    topic_file = tmp_path / 'ntfy-topic'
    first = 'laptopguard-0123456789abcdef'
    second = 'laptopguard-fedcba9876543210'
    topic_file.write_text(first + '\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)
    settings = _settings(tmp_path, topic_file)

    assert run_test(settings, sender=lambda *args, **kwargs: None) is True
    assert is_enabled(Path(settings.state_dir), topic_file) is True

    topic_file.write_text(second + '\n', encoding='utf-8')
    os.chmod(topic_file, 0o600)

    assert is_enabled(Path(settings.state_dir), topic_file) is False


def test_settings_keeps_v0121_positional_constructor_order():
    from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings

    mail = MailSettings(enabled=True)
    capture = CaptureSettings(max_seconds=1.5)
    location = LocationSettings(enabled=False)
    settings = Settings(mail, capture, location, '/state', '/evidence', '/queue', 7, 4, 90)

    assert settings.mail is mail
    assert settings.capture is capture
    assert settings.location is location
    assert settings.state_dir == '/state'
    assert settings.evidence_dir == '/evidence'
    assert settings.queue_dir == '/queue'
    assert settings.rate_limit_seconds == 7
    assert settings.failed_auth_threshold == 4
    assert settings.failed_auth_window_seconds == 90


def test_configure_push_requires_root_even_with_custom_config(monkeypatch, tmp_path: Path):
    import laptopguard.cli as cli

    topic_file = tmp_path / 'ntfy-topic'
    config = tmp_path / 'config.toml'
    config.write_text(
        f'state_dir = "{tmp_path / "state"}"\n\n'
        f'[push]\ntopic_file = "{topic_file}"\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 1000)

    rc = cli.main(['--config', str(config), 'configure-push', 'laptopguard-0123456789abcdef'])

    assert rc == 2
    assert not topic_file.exists()
