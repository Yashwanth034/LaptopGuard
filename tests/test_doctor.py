from laptopguard.config import Settings
from laptopguard.doctor import run


def test_doctor_reports_face_detector_data():
    checks = run(Settings())
    assert any(check.name == 'Face detector data' for check in checks)


def test_doctor_location_capability_reports_wifi_without_active_resolution():
    from laptopguard.doctor import _location_capability_check

    check = _location_capability_check(
        [{'macAddress': '08:11:22:33:44:55'}, {'macAddress': '10:22:33:44:55:66'}],
        vpn_active=False,
        browser_configured=False,
        browser_session_ready=False,
    )
    assert check.ok is True
    assert check.name == 'Physical location capability'
    assert '2 Wi-Fi APs' in check.detail
    assert 'passive check' in check.detail.lower()


def test_doctor_location_check_is_passive_and_never_calls_browser_resolver():
    from laptopguard.doctor import _location_capability_check

    def forbidden(*args, **kwargs):
        raise AssertionError('doctor must never launch browser geolocation')

    check = _location_capability_check(
        [{'macAddress': '08:11:22:33:44:55'}, {'macAddress': '10:22:33:44:55:66'}],
        vpn_active=True,
        browser_configured=True,
        browser_session_ready=True,
        browser_resolver=forbidden,
    )
    assert check.ok is True
    assert check.name == 'Physical location capability'
    assert 'passive check' in check.detail.lower()


def test_doctor_is_passive_for_camera_and_screenshot(monkeypatch, tmp_path):
    import laptopguard.doctor as doctor
    from laptopguard.config import Settings
    from laptopguard.session import ActiveSession

    # Force doctor to see a video device and an active desktop. If doctor tries
    # to open the camera or take a screenshot, this test must fail.
    original_glob = doctor.Path.glob

    def fake_glob(self, pattern):
        if str(self) == '/dev' and pattern == 'video*':
            return [doctor.Path('/dev/video0')]
        return original_glob(self, pattern)

    monkeypatch.setattr(doctor.Path, 'glob', fake_glob)
    import laptopguard.camera as camera
    import laptopguard.evidence as evidence
    monkeypatch.setattr(camera, 'choose_camera', lambda *a, **k: (_ for _ in ()).throw(AssertionError('doctor opened camera')))
    monkeypatch.setattr(evidence, 'capture_screenshot', lambda *a, **k: (_ for _ in ()).throw(AssertionError('doctor captured screenshot')))
    monkeypatch.setattr(doctor, '_find_face_cascade', lambda: doctor.Path('/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml'))
    monkeypatch.setattr(doctor, 'active_session', lambda: ActiveSession('1', 'user', 1000, 'x11', ':0', '/run/user/1000'))
    monkeypatch.setattr(doctor, 'wifi_access_points', lambda: [])
    monkeypatch.setattr(doctor, 'hardware_gps', lambda: None)
    monkeypatch.setattr(doctor, 'detect_vpn', lambda: type('Vpn', (), {'active': False, 'interfaces': (), 'types': ()})())
    monkeypatch.setattr(doctor, 'load_browser_settings', lambda: None)
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr(doctor, '_service_check', lambda name: doctor.DoctorCheck(f'systemd {name}', True, 'active=True, enabled=True'))

    class FakeBrightness:
        device = 'intel_backlight'
        def get_percent(self):
            return 40

    monkeypatch.setattr(doctor, 'BrightnessController', FakeBrightness)

    settings = Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
    )
    (tmp_path / 'state').mkdir()

    checks = doctor.run(settings)

    camera = next(check for check in checks if check.name == 'Webcam device presence')
    screenshot = next(check for check in checks if check.name == 'Screenshot capability')
    assert camera.ok is True
    assert 'passive' in camera.detail.lower()
    assert screenshot.ok is True
    assert 'passive' in screenshot.detail.lower()
