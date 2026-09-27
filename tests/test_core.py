from laptopguard.events import classify_auth_event
from laptopguard.quality import FrameMetrics, acceptable


def test_failed_auth_is_suspicious():
    event = classify_auth_event('pam_unix(cinnamon-screensaver:auth): authentication failure')
    assert event.kind == 'failed_auth'
    assert event.suspicious is True


def test_good_frame_is_accepted():
    metrics = FrameMetrics(brightness=95.0, sharpness=180.0, face_count=1)
    assert acceptable(metrics) is True


def test_dark_frame_is_rejected():
    metrics = FrameMetrics(brightness=12.0, sharpness=180.0, face_count=1)
    assert acceptable(metrics) is False
