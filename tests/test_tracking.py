from pathlib import Path
from laptopguard.config import LocationSettings
from test_engine import FakeBrightness, make_settings
from laptopguard.engine import SecurityEngine
from laptopguard.location import LocationSample


def test_failed_auth_does_not_activate_tracking_automatically(tmp_path: Path):
    settings = make_settings(tmp_path, mail_enabled=False)
    engine = SecurityEngine(
        settings,
        camera_capture=lambda *a, **k: None,
        screenshot_capture=lambda p: None,
        location_collect=lambda **k: None,
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
        brightness_factory=FakeBrightness,
    )
    first = engine.handle_event('failed_auth')
    assert first.delivery == 'ignored-first-attempt'
    assert engine.tracking_active() is False
    second = engine.handle_event('failed_auth')
    assert second.delivery == 'ignored-second-attempt'
    assert engine.tracking_active() is False
    engine.handle_event('failed_auth')
    assert engine.tracking_active() is False


def test_offline_gps_update_is_encrypted_in_queue(tmp_path: Path):
    settings = make_settings(tmp_path, mail_enabled=False)
    engine = SecurityEngine(
        settings,
        location_collect=lambda **k: LocationSample(17.3, 78.4, 'modem-gps').normalized(),
        metadata_factory=lambda event: {'event': event, 'timestamp': 'now', 'hostname': 'test'},
    )
    engine.activate_tracking(10)
    assert engine.send_location_update() is True
    assert len(engine.queue.items()) == 1
