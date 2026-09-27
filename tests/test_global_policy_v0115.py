from pathlib import Path

from laptopguard.config import CaptureSettings, LocationSettings, MailSettings, Settings, load_config
from laptopguard.engine import SecurityEngine


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
        capture=CaptureSettings(require_face=False),
        location=LocationSettings(enabled=True, allow_ip_fallback=False),
    )


def test_normal_boot_and_resume_capture_defaults_are_disabled():
    capture = CaptureSettings()
    assert capture.capture_on_boot is False
    assert capture.capture_on_resume is False


def test_migrate_normal_lifecycle_policy_disables_old_boot_and_resume_capture(tmp_path: Path):
    from laptopguard.config import migrate_normal_lifecycle_policy

    cfg = tmp_path / 'config.toml'
    cfg.write_text(
        '[capture]\n'
        'camera_index = -1\n'
        'capture_on_resume = true\n'
        'capture_on_boot = true\n\n'
        '[location]\n'
        'enabled = true\n',
        encoding='utf-8',
    )

    assert migrate_normal_lifecycle_policy(cfg) is True
    text = cfg.read_text(encoding='utf-8')
    assert 'capture_on_resume = false' in text
    assert 'capture_on_boot = false' in text
    settings = load_config(cfg)
    assert settings.capture.capture_on_resume is False
    assert settings.capture.capture_on_boot is False
    assert migrate_normal_lifecycle_policy(cfg) is False


def test_resume_is_readiness_only_and_never_captures_or_sends(tmp_path: Path):
    calls = {'camera': 0, 'screenshot': 0, 'location': 0, 'mail': 0, 'ready': 0, 'flush': 0}

    def forbidden(name):
        def inner(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f'{name} must not run for normal resume')
        return inner

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=forbidden('camera'),
        screenshot_capture=forbidden('screenshot'),
        location_collect=forbidden('location'),
        mail_send=forbidden('mail'),
        readiness_waiter=lambda: calls.__setitem__('ready', calls['ready'] + 1),
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
    )
    engine.flush_queue = lambda: calls.__setitem__('flush', calls['flush'] + 1) or 0

    result = engine.handle_event('resume')

    assert result.delivery == 'readiness-only'
    assert result.photo_captured is False
    assert result.location_captured is False
    assert calls == {'camera': 0, 'screenshot': 0, 'location': 0, 'mail': 0, 'ready': 1, 'flush': 1}


def test_boot_is_readiness_only_and_never_captures_or_sends(tmp_path: Path):
    calls = {'camera': 0, 'screenshot': 0, 'location': 0, 'mail': 0, 'flush': 0}

    def forbidden(name):
        def inner(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f'{name} must not run for normal boot')
        return inner

    engine = SecurityEngine(
        _settings(tmp_path),
        camera_capture=forbidden('camera'),
        screenshot_capture=forbidden('screenshot'),
        location_collect=forbidden('location'),
        mail_send=forbidden('mail'),
        readiness_waiter=lambda: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
    )
    engine.flush_queue = lambda: calls.__setitem__('flush', calls['flush'] + 1) or 0

    result = engine.handle_event('boot')

    assert result.delivery == 'readiness-only'
    assert result.photo_captured is False
    assert result.location_captured is False
    assert calls == {'camera': 0, 'screenshot': 0, 'location': 0, 'mail': 0, 'flush': 1}


def test_background_location_page_requires_pregranted_permission():
    from laptopguard.browser_location import _location_page

    html = _location_page(setup=False, token='token')
    assert "navigator.permissions.query({name:'geolocation'})" in html
    assert "permission.state !== 'granted'" in html
    assert 'backgroundLocate();' in html
    assert "getCurrentPosition" in html


def test_setup_location_page_is_the_only_path_allowed_to_request_permission():
    from laptopguard.browser_location import _location_page

    setup_html = _location_page(setup=True, token='token')
    background_html = _location_page(setup=False, token='token')
    assert 'Click Allow location and approve the browser prompt once.' in setup_html
    assert 'document.getElementById("go").onclick=locate;' in setup_html
    assert 'Click Allow location and approve the browser prompt once.' not in background_html
    assert "permission.state !== 'granted'" in background_html


def test_upgrade_cleanup_removes_only_legacy_boot_resume_queue_items(tmp_path: Path):
    from laptopguard.queue_store import EncryptedQueue

    queue = EncryptedQueue(tmp_path / 'queue', tmp_path / 'queue.key')
    boot = queue.enqueue({'metadata': {'event': 'boot'}, 'subject': 'boot', 'body': 'boot'}, [])
    resume = queue.enqueue({'metadata': {'event': 'resume'}, 'subject': 'resume', 'body': 'resume'}, [])
    failed = queue.enqueue({'metadata': {'event': 'failed_auth'}, 'subject': 'failed', 'body': 'failed'}, [])

    removed = queue.remove_events({'boot', 'resume'})

    assert removed == 2
    assert not boot.exists()
    assert not resume.exists()
    assert failed.exists()
    payload, _ = queue.read(failed)
    assert payload['metadata']['event'] == 'failed_auth'
