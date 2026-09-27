from pathlib import Path

import pytest

from laptopguard import cli
from laptopguard.camera import camera_indices
from laptopguard.config import Settings
from laptopguard.platform_support import (
    IS_LINUX,
    IS_MACOS,
    IS_WINDOWS,
    default_config_path,
    default_state_dir,
    hostname,
)
from laptopguard.session import active_session
from laptopguard.timeline import EventTimeline


def test_cli_and_platform_helpers_load():
    parser = cli.build_parser()
    assert parser.prog == "laptopguard"
    assert hostname()
    assert default_config_path().name == "config.toml"


def test_settings_use_platform_state_defaults():
    settings = Settings()
    assert Path(settings.state_dir) == default_state_dir()
    if IS_WINDOWS:
        assert "LaptopGuard" in str(default_state_dir())
        assert "/etc/" not in str(default_config_path()).replace("\\", "/")
    elif IS_MACOS:
        assert "Library/Application Support/LaptopGuard" in str(default_state_dir()).replace("\\", "/")
    elif IS_LINUX:
        assert default_config_path() == Path("/etc/laptopguard/config.toml")


def test_event_timeline_sequence_is_portable(tmp_path: Path):
    timeline = EventTimeline(
        tmp_path,
        boot_id_provider=lambda: "boot-test",
        monotonic_ns=lambda: 123,
    )
    first = timeline.next()
    second = timeline.next()
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["boot_id"] == "boot-test"


def test_non_linux_current_session_is_available():
    if IS_LINUX:
        pytest.skip("portable desktop-session fallback is non-Linux only")
    session = active_session()
    assert session is not None
    assert session.user
    assert session.session_type in {"windows", "aqua", "desktop"}


def test_non_linux_camera_probe_range_is_available():
    if IS_LINUX:
        pytest.skip("portable camera index probing is non-Linux only")
    assert camera_indices() == [0, 1, 2, 3, 4]
