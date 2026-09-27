from pathlib import Path

from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings
from laptopguard.engine import SecurityEngine
from laptopguard.queue_store import EncryptedQueue
from laptopguard.shutdown_guard import shutdown_type_from_metadata, should_alert_for_shutdown


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


def test_shutdown_metadata_distinguishes_poweroff_from_reboot():
    assert shutdown_type_from_metadata({'type': 'power-off'}) == 'poweroff'
    assert shutdown_type_from_metadata({'type': 'poweroff'}) == 'poweroff'
    assert shutdown_type_from_metadata({'type': 'reboot'}) == 'reboot'
    assert should_alert_for_shutdown(True, {'type': 'power-off'}, locked=True) is True
    assert should_alert_for_shutdown(True, {'type': 'poweroff'}, locked=True) is True
    assert should_alert_for_shutdown(True, {'type': 'reboot'}, locked=True) is False
    assert should_alert_for_shutdown(True, {'type': 'power-off'}, locked=False) is False
    assert should_alert_for_shutdown(False, {'type': 'power-off'}, locked=True) is False


def test_queue_update_atomically_replaces_payload_and_attachments(tmp_path: Path):
    queue = EncryptedQueue(tmp_path / 'queue', tmp_path / 'queue.key')
    first = tmp_path / 'photo.jpg'
    first.write_bytes(b'photo')
    item = queue.enqueue({'subject': 'initial', 'body': 'initial'}, [first])

    screenshot = tmp_path / 'screenshot.png'
    screenshot.write_bytes(b'screen')
    queue.update(item, {'subject': 'updated', 'body': 'updated'}, [first, screenshot])

    assert queue.items() == [item]
    payload, files = queue.read(item)
    assert payload['subject'] == 'updated'
    assert files == {'photo.jpg': b'photo', 'screenshot.png': b'screen'}


def test_locked_shutdown_queues_before_slow_location_and_sends_once(tmp_path: Path):
    calls = []

    class CaptureResult:
        frames_seen = 3
        class metrics:
            brightness = 80
            sharpness = 120
            faces = 1

    def capture(path, **kwargs):
        Path(path).write_bytes(b'photo')
        return CaptureResult()

    def screenshot(path):
        Path(path).write_bytes(b'screen')
        return Path(path)

    def metadata(event):
        calls.append('metadata')
        return {'event': event, 'timestamp': 'now', 'hostname': 'test', 'wifi_ssid': 'wifi'}

    def location(**kwargs):
        calls.append('location')
        return None

    sent = []
    def mail(settings, subject, body, attachments):
        sent.append((subject, body, [Path(p).name for p in attachments]))

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=capture,
        screenshot_capture=screenshot,
        metadata_factory=metadata,
        location_collect=location,
        mail_send=mail,
    )

    result = engine.handle_event('lockscreen_shutdown')

    assert result.event == 'lockscreen_shutdown'
    assert result.delivery == 'sent'
    assert result.photo_captured is True
    assert len(sent) == 1
    assert set(sent[0][2]) == {'photo.jpg'}
    assert engine.queue.items() == []


def test_locked_shutdown_keeps_encrypted_queue_if_mail_fails(tmp_path: Path):
    class CaptureResult:
        frames_seen = 1
        class metrics:
            brightness = 80
            sharpness = 120
            faces = 1

    def capture(path, **kwargs):
        Path(path).write_bytes(b'photo')
        return CaptureResult()

    def fail_mail(*args, **kwargs):
        raise OSError('powering off')

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=capture,
        screenshot_capture=lambda p: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        location_collect=lambda **kwargs: None,
        mail_send=fail_mail,
    )

    result = engine.handle_event('lockscreen_shutdown')
    assert result.delivery == 'queued'
    assert len(engine.queue.items()) == 1
    payload, files = engine.queue.read(engine.queue.items()[0])
    assert payload['metadata']['event'] == 'lockscreen_shutdown'
    assert files['photo.jpg'] == b'photo'


def test_shutdown_guard_command_uses_delay_inhibitor(monkeypatch):
    from laptopguard import daemon

    monkeypatch.setattr(daemon.shutil, 'which', lambda name: '/usr/bin/systemd-inhibit' if name == 'systemd-inhibit' else '/usr/local/bin/laptopguard')
    command = daemon.shutdown_guard_command()
    assert command is not None
    assert '--what=shutdown' in command
    assert '--mode=delay' in command
    assert command[-2:] == ['/usr/local/bin/laptopguard', 'shutdown-watch']


def test_session_lock_uses_logind_locked_hint(monkeypatch):
    from laptopguard.shutdown_guard import session_is_locked
    from laptopguard.session import ActiveSession
    import laptopguard.shutdown_guard as guard

    session = ActiveSession('2', 'alice', 1000, 'x11', ':0', '/run/user/1000')
    monkeypatch.setattr(guard, 'active_session', lambda runner=None: session)

    class Result:
        def __init__(self, stdout=''):
            self.stdout = stdout
            self.returncode = 0

    def runner(command, **kwargs):
        if command[:3] == ['loginctl', 'show-session', '2']:
            return Result('yes\n')
        return Result('')

    assert session_is_locked(runner=runner) is True


def test_doctor_shutdown_guard_check_is_passive_and_accepts_systemd_255(monkeypatch):
    import laptopguard.doctor as doctor

    monkeypatch.setattr(doctor.shutil, 'which', lambda name: '/usr/bin/systemd-inhibit' if name == 'systemd-inhibit' else f'/usr/bin/{name}')

    class Result:
        stdout = 'systemd 255 (255.4-1ubuntu8)\n'
        returncode = 0

    monkeypatch.setattr(doctor.subprocess, 'run', lambda *a, **k: Result())
    check = doctor._shutdown_guard_capability_check()
    assert check.ok is True
    assert check.name == 'Lock-screen shutdown guard'
    assert 'systemd 255' in check.detail


def test_session_lock_falls_back_to_logind_sessions_when_active_session_is_unavailable(monkeypatch):
    from laptopguard.shutdown_guard import session_is_locked
    import laptopguard.shutdown_guard as guard

    monkeypatch.setattr(guard, 'active_session', lambda runner=None: None)

    class Result:
        def __init__(self, stdout=''):
            self.stdout = stdout
            self.returncode = 0

    def runner(command, **kwargs):
        if command[:3] == ['loginctl', 'list-sessions', '--no-legend']:
            return Result('2 1000 alice seat0 2222 user tty2 no\n')
        if command[:3] == ['loginctl', 'show-session', '2']:
            return Result('User=1000\nRemote=no\nType=x11\nClass=user\nLockedHint=yes\n')
        return Result('')

    assert session_is_locked(runner=runner) is True
