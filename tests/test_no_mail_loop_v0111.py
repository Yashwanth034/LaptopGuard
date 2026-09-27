from pathlib import Path

from laptopguard.config import LocationSettings
from laptopguard.engine import SecurityEngine
from test_failed_auth_threshold_v0110 import make_engine, settings


def test_full_failed_auth_alert_does_not_enable_periodic_tracking_by_default(tmp_path: Path):
    sent = []
    engine = make_engine(tmp_path, sent=sent)

    engine.handle_event('failed_auth')
    engine.handle_event('failed_auth')
    third = engine.handle_event('failed_auth')

    assert third.delivery == 'sent'
    assert len(sent) == 1
    assert engine.tracking_active() is False


def test_manual_tracking_still_works(tmp_path: Path):
    engine = SecurityEngine(settings(tmp_path))

    engine.activate_tracking(10)

    assert engine.tracking_active() is True


def test_location_settings_disable_automatic_tracking_by_default():
    assert LocationSettings().auto_tracking_after_alert is False
