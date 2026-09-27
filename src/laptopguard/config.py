from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .platform_support import (
    default_config_path,
    default_evidence_dir,
    default_push_topic_path,
    default_queue_dir,
    default_secret_path,
    default_state_dir,
)

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass(frozen=True)
class MailSettings:
    enabled: bool = False
    host: str = "smtp.gmail.com"
    port: int = 465
    username: str = ""
    from_address: str = ""
    to_address: str = ""
    password_file: str = field(default_factory=lambda: str(default_secret_path()))
    use_ssl: bool = True

    def password(self) -> str:
        path = Path(self.password_file)
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


@dataclass(frozen=True)
class PushSettings:
    topic_file: str = field(default_factory=lambda: str(default_push_topic_path()))


@dataclass(frozen=True)
class CaptureSettings:
    camera_index: int = -1
    auto_camera: bool = True
    max_seconds: float = 5.0
    min_brightness: float = 45.0
    min_sharpness: float = 90.0
    require_face: bool = True
    boost_brightness: int = 100
    capture_on_resume: bool = False
    capture_on_boot: bool = False


@dataclass(frozen=True)
class LocationSettings:
    enabled: bool = True
    allow_ip_fallback: bool = True
    tracking_minutes: int = 360
    tracking_interval_seconds: int = 300
    auto_tracking_after_alert: bool = False
    browser_geolocation_enabled: bool = True
    browser_max_vpn_accuracy_m: float = 250.0


@dataclass(frozen=True)
class Settings:
    mail: MailSettings = field(default_factory=MailSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    location: LocationSettings = field(default_factory=LocationSettings)
    state_dir: str = field(default_factory=lambda: str(default_state_dir()))
    evidence_dir: str = field(default_factory=lambda: str(default_evidence_dir()))
    queue_dir: str = field(default_factory=lambda: str(default_queue_dir()))
    rate_limit_seconds: int = 180
    failed_auth_threshold: int = 3
    failed_auth_window_seconds: int = 120
    push: PushSettings = field(default_factory=PushSettings)


def _build(cls, values: dict):
    allowed = cls.__dataclass_fields__.keys()
    return cls(**{k: v for k, v in values.items() if k in allowed})


def migrate_failed_auth_policy(path: Path | str, threshold: int = 3) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    replacement = f"failed_auth_threshold = {max(1, int(threshold))}"
    changed = False
    found = False
    for index, line in enumerate(lines):
        if line.strip().startswith("failed_auth_threshold") and "=" in line:
            found = True
            if line.strip() != replacement:
                lines[index] = replacement
                changed = True
            break
    if not found:
        section_index = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
        lines.insert(section_index, replacement)
        changed = True
    if not changed:
        return False
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") or lines else ""), encoding="utf-8")
    return True



def migrate_normal_lifecycle_policy(path: Path | str) -> bool:
    """Disable alert capture for ordinary boot/resume in saved configs.

    The fields are kept for backward-compatible parsing, but normal boot and
    resume are lifecycle/readiness events rather than security alerts.
    """
    path = Path(path)
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "[capture]"), None)
    if start is None:
        # Do not invent an entire capture section in unusual hand-written configs;
        # the dataclass defaults are already safe.
        return False
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    changed = False
    for key in ("capture_on_resume", "capture_on_boot"):
        replacement = f"{key} = false"
        found = False
        for i in range(start + 1, end):
            stripped = lines[i].strip()
            if stripped.startswith(key) and "=" in stripped:
                found = True
                if stripped != replacement:
                    lines[i] = replacement
                    changed = True
                break
        if not found:
            lines.insert(end, replacement)
            end += 1
            changed = True
    if changed:
        path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") or lines else ""), encoding="utf-8")
    return changed

def load_config(path: Path | str | None = None) -> Settings:
    path = Path(path) if path is not None else default_config_path()
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    root = {k: v for k, v in data.items() if k not in {"mail", "push", "capture", "location"}}
    return Settings(
        **{k: v for k, v in root.items() if k in Settings.__dataclass_fields__},
        mail=_build(MailSettings, data.get("mail", {})),
        push=_build(PushSettings, data.get("push", {})),
        capture=_build(CaptureSettings, data.get("capture", {})),
        location=_build(LocationSettings, data.get("location", {})),
    )
