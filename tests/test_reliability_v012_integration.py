from pathlib import Path
from types import SimpleNamespace

from laptopguard.brightness import BrightnessController
from laptopguard.camera import choose_camera
from laptopguard.evidence import capture_screenshot, base_metadata
from laptopguard.network import VpnState
from laptopguard.session import ActiveSession


class R:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ''


def test_camera_selection_prefers_non_ir_working_rgb_device():
    names = {0: 'Integrated Camera: IR', 1: 'Integrated Camera'}
    chosen = choose_camera([0, 1], name_provider=lambda i: names[i], probe=lambda i: i in {0, 1})
    assert chosen == 1


def test_camera_selection_skips_busy_device():
    names = {0: 'Integrated Camera', 1: 'USB Camera'}
    chosen = choose_camera([0, 1], name_provider=lambda i: names[i], probe=lambda i: i == 1)
    assert chosen == 1


def test_brightness_boost_restores_exact_raw_value():
    calls = []
    values = {'current': 413, 'max': 1000}

    def runner(args, **kwargs):
        calls.append(args)
        if args[-1] == 'g':
            return R(str(values['current']))
        if args[-1] == 'm':
            return R(str(values['max']))
        if 'set' in args:
            values['current'] = int(args[-1])
            return R()
        return R()

    ctl = BrightnessController(runner=runner, device='intel_backlight')
    with ctl.boosted(100):
        assert values['current'] == 1000
    assert values['current'] == 413


def test_screenshot_runs_inside_active_desktop_session(tmp_path: Path, monkeypatch):
    target = tmp_path / 'shot.png'
    session = ActiveSession('2', 'alice', 1000, 'x11', ':0', '/run/user/1000')
    seen = []

    def fake_which(name):
        return '/usr/bin/gnome-screenshot' if name == 'gnome-screenshot' else None

    def runner(args, **kwargs):
        seen.append(args)
        target.write_bytes(b'png')
        return R(returncode=0)

    monkeypatch.setattr('laptopguard.evidence.shutil.which', fake_which)
    result = capture_screenshot(target, session_provider=lambda: session, runner=runner)
    assert result == target
    flat = ' '.join(seen[0])
    assert 'runuser -u alice' in flat
    assert 'DISPLAY=:0' in flat
    assert 'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus' in flat


def test_metadata_uses_active_desktop_user_and_labels_vpn(monkeypatch):
    session = ActiveSession('2', 'alice', 1000, 'x11', ':0', '/run/user/1000')
    fake_snapshot = SimpleNamespace(vpn=VpnState(True, ('wg0',), ('wireguard',)), interfaces=({'name':'wlp2s0','class':'physical','addresses':['192.168.1.2']},{'name':'wg0','class':'vpn','addresses':['10.0.0.2']},))
    monkeypatch.setattr('laptopguard.evidence.active_session', lambda: session)
    monkeypatch.setattr('laptopguard.evidence.network_snapshot', lambda: fake_snapshot)
    monkeypatch.setattr('laptopguard.evidence.active_ssid', lambda: 'Home')
    monkeypatch.setattr('laptopguard.evidence.nearby_wifi', lambda: [])
    data = base_metadata('manual_test')
    assert data['username'] == 'alice'
    assert data['network']['vpn']['active'] is True
    assert data['network']['vpn']['interfaces'] == ['wg0']


def test_active_session_reads_leader_environment_without_silently_failing(monkeypatch, tmp_path):
    from laptopguard import session as session_mod

    class Result:
        def __init__(self, stdout=''):
            self.stdout = stdout
            self.returncode = 0

    calls = []
    def runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ['loginctl', 'list-sessions']:
            return Result('2 1000 alice seat0 tty2\n')
        if cmd[:2] == ['loginctl', 'show-session']:
            return Result('Name=alice\nUser=1000\nActive=yes\nRemote=no\nType=x11\nDisplay=:0\nLeader=4242\n')
        raise AssertionError(cmd)

    monkeypatch.setattr(session_mod.shutil, 'which', lambda name: '/usr/bin/loginctl')
    monkeypatch.setattr(session_mod.pwd, 'getpwuid', lambda uid: type('P', (), {'pw_name':'alice'})())

    real_path = session_mod.Path if hasattr(session_mod, 'Path') else None
    assert real_path is not None, 'session module must import pathlib.Path for /proc/<leader>/environ access'
    result = session_mod.active_session(runner=runner)
    assert result is not None
    assert result.user == 'alice'
    assert result.session_type == 'x11'
