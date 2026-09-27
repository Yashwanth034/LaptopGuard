import os
import pwd

from laptopguard.browser_location import BrowserLocationSettings, _browser_command
from laptopguard.session import ActiveSession


def _settings():
    info = pwd.getpwuid(os.getuid())
    return BrowserLocationSettings(
        info.pw_name,
        '/usr/bin/google-chrome',
        info.pw_dir + '/.local/share/laptopguard-location-browser',
    )


def test_background_browser_reuses_real_graphical_session_not_xvfb():
    settings = _settings()
    session = ActiveSession(
        session_id='2',
        user=settings.user,
        uid=os.getuid(),
        session_type='x11',
        display=':0',
        runtime_dir=f'/run/user/{os.getuid()}',
        xauthority='/home/test/.Xauthority',
    )
    cmd = _browser_command(
        settings,
        'http://127.0.0.1:8765/locate?token=x',
        background=True,
        session=session,
    )
    joined = ' '.join(cmd)
    assert 'xvfb-run' not in joined
    assert 'DISPLAY=:0' in joined
    assert f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus' in joined
    assert '--start-minimized' in joined
    assert '--app=http://127.0.0.1:8765/locate?token=x' in joined


def test_background_browser_rejects_wrong_or_missing_active_user_session():
    settings = _settings()
    try:
        _browser_command(settings, 'http://127.0.0.1:8765/locate?token=x', background=True, session=None)
    except RuntimeError as exc:
        assert 'active graphical session' in str(exc).lower()
    else:
        raise AssertionError('expected missing graphical session to fail')
