from pathlib import Path
import os
import pwd

from laptopguard.browser_location import BrowserLocationSettings, _browser_command
from laptopguard.session import ActiveSession


def test_background_browser_stays_headed_not_chrome_headless():
    user = pwd.getpwuid(os.getuid()).pw_name
    home = pwd.getpwuid(os.getuid()).pw_dir
    settings = BrowserLocationSettings(
        user,
        '/usr/bin/google-chrome',
        home + '/.local/share/laptopguard-location-browser',
    )
    session = ActiveSession('2', user, os.getuid(), 'x11', ':0', f'/run/user/{os.getuid()}')
    cmd = _browser_command(settings, 'http://127.0.0.1:8765/locate?token=x', background=True, session=session)
    joined = ' '.join(cmd)
    assert 'xvfb-run' not in joined
    assert '--headless' not in joined
    assert '--app=http://127.0.0.1:8765/locate?token=x' in joined


def test_setup_browser_remains_visible_without_xvfb():
    user = pwd.getpwuid(os.getuid()).pw_name
    home = pwd.getpwuid(os.getuid()).pw_dir
    settings = BrowserLocationSettings(
        user,
        '/usr/bin/google-chrome',
        home + '/.local/share/laptopguard-location-browser',
    )
    cmd = _browser_command(settings, 'http://127.0.0.1:8765/setup?token=x', background=False)
    joined = ' '.join(cmd)
    assert 'xvfb-run' not in joined
    assert '--headless' not in joined
    assert '--app=http://127.0.0.1:8765/setup?token=x' in joined
