from __future__ import annotations

import ctypes
import getpass
import os
from pathlib import Path
import socket
import sys
import time


IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"


def platform_name() -> str:
    if IS_WINDOWS:
        return "Windows"
    if IS_MACOS:
        return "macOS"
    if IS_LINUX:
        return "Linux"
    return sys.platform


def hostname() -> str:
    return socket.gethostname() or "unknown"


def boot_identifier() -> str:
    if IS_LINUX:
        path = Path('/proc/sys/kernel/random/boot_id')
        try:
            return path.read_text(encoding='utf-8').strip()
        except OSError:
            pass
    boot_minute = int((time.time() - time.monotonic()) // 60)
    return f'{hostname()}-{boot_minute}'


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def app_data_dir() -> Path:
    home = Path.home()
    if IS_WINDOWS:
        root = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        return root / "LaptopGuard"
    if IS_MACOS:
        return home / "Library" / "Application Support" / "LaptopGuard"
    return Path("/var/lib/laptopguard")


def default_config_path() -> Path:
    if IS_LINUX:
        return Path("/etc/laptopguard/config.toml")
    return app_data_dir() / "config.toml"


def default_secret_path() -> Path:
    if IS_LINUX:
        return Path("/etc/laptopguard/smtp-password")
    return app_data_dir() / "smtp-password"


def default_push_topic_path() -> Path:
    if IS_LINUX:
        return Path("/etc/laptopguard/ntfy-topic")
    return app_data_dir() / "ntfy-topic"


def default_browser_settings_path() -> Path:
    if IS_LINUX:
        return Path("/etc/laptopguard/browser-location.json")
    return app_data_dir() / "browser-location.json"


def default_google_key_path() -> Path:
    if IS_LINUX:
        return Path("/etc/laptopguard/google-geolocation-key")
    return app_data_dir() / "google-geolocation-key"


def default_state_dir() -> Path:
    return app_data_dir()


def default_evidence_dir() -> Path:
    return app_data_dir() / "evidence"


def default_queue_dir() -> Path:
    return app_data_dir() / "queue"
