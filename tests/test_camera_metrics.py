import numpy as np
from laptopguard.camera import measure_frame


def test_measure_frame_reports_brightness_and_sharpness():
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    frame[:, 40:] = 255
    metrics = measure_frame(frame, detect_faces=False)
    assert 120 <= metrics.brightness <= 135
    assert metrics.sharpness > 100
    assert metrics.face_count == 0


def test_face_cascade_falls_back_to_system_opencv_data(monkeypatch, tmp_path):
    from laptopguard import camera

    cascade = tmp_path / "haarcascade_frontalface_default.xml"
    cascade.write_text("cascade", encoding="utf-8")
    monkeypatch.delattr(camera.cv2, "data", raising=False)
    monkeypatch.setattr(camera, "SYSTEM_CASCADE_PATHS", (cascade,))

    assert camera._find_face_cascade() == cascade
