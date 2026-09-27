from pathlib import Path

from laptopguard.config import Settings
from laptopguard.shutdown_guard import login_screen_active, should_alert_for_shutdown


def test_shutdown_policy_alerts_for_login_screen_poweroff_but_not_reboot():
    assert should_alert_for_shutdown(True, {'type': 'poweroff'}, locked=False, login_screen=True) is True
    assert should_alert_for_shutdown(True, {'type': 'reboot'}, locked=False, login_screen=True) is False
    assert should_alert_for_shutdown(True, {'type': 'poweroff'}, locked=False, login_screen=False) is False


def test_login_screen_active_detects_active_lightdm_greeter_session():
    class Result:
        def __init__(self, stdout='', returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def runner(command, **kwargs):
        if command[:3] == ['loginctl', 'list-sessions', '--no-legend']:
            return Result('c1 112 lightdm seat0 1200 greeter x11 no\n')
        if command[:3] == ['loginctl', 'show-session', 'c1']:
            return Result('Name=lightdm\nUser=112\nActive=yes\nRemote=no\nType=x11\nClass=greeter\nService=lightdm-greeter\n')
        return Result('', 1)

    assert login_screen_active(runner=runner) is True


def test_login_screen_active_uses_slick_greeter_fallback():
    class Result:
        def __init__(self, stdout='', returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def runner(command, **kwargs):
        if command[:3] == ['loginctl', 'list-sessions', '--no-legend']:
            return Result('')
        if command[:2] == ['pgrep', '-x'] and command[-1] == 'slick-greeter':
            return Result('4321\n', 0)
        return Result('', 1)

    assert login_screen_active(runner=runner) is True


def test_shutdown_guard_run_alerts_for_initial_login_screen(monkeypatch, tmp_path: Path):
    import laptopguard.shutdown_guard as guard

    handled = []

    class FakeEngine:
        def __init__(self, settings):
            pass

        def handle_event(self, name):
            handled.append(name)
            class Result:
                delivery = 'queued'
                photo_captured = True
                location_captured = False
            return Result()

    def fake_start(tracker, stop_event):
        return None

    def fake_subscribe(on_signal, tracker):
        on_signal(True, {'type': 'poweroff'})

    monkeypatch.setattr(guard, 'SecurityEngine', FakeEngine)
    monkeypatch.setattr(guard, '_start_user_lock_state_watcher', fake_start)
    monkeypatch.setattr(guard, '_subscribe_and_wait', fake_subscribe)

    settings = Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
    )
    guard.run(settings, lock_checker=lambda: False, login_screen_checker=lambda: True)

    assert handled == ['login_screen_shutdown']


def test_login_screen_active_does_not_mistake_normal_lightdm_user_session_for_greeter():
    class Result:
        def __init__(self, stdout='', returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def runner(command, **kwargs):
        if command[:3] == ['loginctl', 'list-sessions', '--no-legend']:
            return Result('c2 1000 alice seat0 1275 user x11 no\n')
        if command[:3] == ['loginctl', 'show-session', 'c2']:
            return Result('Name=alice\nUser=1000\nActive=yes\nRemote=no\nType=x11\nClass=user\nService=lightdm\n')
        if command[:2] == ['pgrep', '-x'] and command[-1] == 'slick-greeter':
            return Result('', 1)
        return Result('', 1)

    assert login_screen_active(runner=runner) is False


def test_engine_login_screen_shutdown_uses_same_crash_safe_full_alert_path(tmp_path: Path):
    from laptopguard.config import CaptureSettings, LocationSettings, MailSettings
    from laptopguard.engine import SecurityEngine
    from laptopguard.location import LocationSample

    secret = tmp_path / 'smtp-password'
    secret.write_text('pw', encoding='utf-8')
    settings = Settings(
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

    def capture(path, **kwargs):
        Path(path).write_bytes(b'photo')
        return CaptureResult()

    sent = []
    engine = SecurityEngine(
        settings,
        camera_capture=capture,
        screenshot_capture=lambda path: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test', 'wifi_ssid': 'wifi'},
        location_collect=lambda **kwargs: LocationSample(17.3, 78.4, 'test').normalized(),
        mail_send=lambda settings, subject, body, attachments: sent.append((subject, list(attachments))),
    )

    result = engine.handle_event('login_screen_shutdown')

    assert result.event == 'login_screen_shutdown'
    assert result.delivery == 'sent'
    assert result.photo_captured is True
    assert result.location_captured is False
    assert len(sent) == 1
    assert engine.queue.items() == []
