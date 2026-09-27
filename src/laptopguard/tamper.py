from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile


MAINTENANCE_MARKER = Path('/run/laptopguard-maintenance')

# Security-sensitive operating-system files plus LaptopGuard integration points.
CRITICAL_PATHS = [
    Path('/etc/passwd'),
    Path('/etc/group'),
    Path('/etc/shadow'),
    Path('/etc/sudoers'),
    Path('/etc/default/grub'),
    Path('/boot/grub/grub.cfg'),
    Path('/etc/laptopguard/config.toml'),
    Path('/usr/local/bin/laptopguard'),
    Path('/etc/systemd/system/laptopguard.service'),
    Path('/etc/systemd/system/laptopguard-resume.service'),
    Path('/etc/systemd/system/laptopguard-watchdog.service'),
    Path('/etc/systemd/system/laptopguard-watchdog.timer'),
    Path('/usr/lib/systemd/system-sleep/laptopguard'),
    Path('/opt/laptopguard/app/scripts/watchdog.sh'),
]

# These files are legitimately replaced or edited by install.sh. Only these
# baseline entries may be refreshed by a trusted LaptopGuard upgrade. OS files
# above are deliberately excluded so an upgrade can never bless an unrelated
# security-sensitive modification.
TRUSTED_INSTALL_PATHS = [
    Path('/etc/laptopguard/config.toml'),
    Path('/usr/local/bin/laptopguard'),
    Path('/etc/systemd/system/laptopguard.service'),
    Path('/etc/systemd/system/laptopguard-resume.service'),
    Path('/etc/systemd/system/laptopguard-watchdog.service'),
    Path('/etc/systemd/system/laptopguard-watchdog.timer'),
    Path('/usr/lib/systemd/system-sleep/laptopguard'),
    Path('/opt/laptopguard/app/scripts/watchdog.sh'),
]


@dataclass(frozen=True)
class TamperChange:
    path: str
    previous: str | None
    current: str | None


def _digest(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open('rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class TamperBaseline:
    def __init__(self, state_path: Path, paths: list[Path]):
        self.state_path = Path(state_path)
        self.paths = [Path(p) for p in paths]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _snapshot(self) -> dict[str, str | None]:
        return {str(path): _digest(path) for path in self.paths}

    def _read_state(self) -> dict[str, str | None]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): value if value is None or isinstance(value, str) else None for key, value in data.items()}

    def _write_state(self, state: dict[str, str | None]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix='.tamper-baseline-', suffix='.tmp', dir=self.state_path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(state, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.state_path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def trust_current(self, trusted_paths: list[Path]) -> None:
        """Refresh only explicitly trusted monitored paths.

        This is for the installer after it legitimately replaces LaptopGuard's
        own managed files. Unrelated monitored files retain their previous
        digests so a simultaneous OS/security-file modification is still
        reported on the next check.
        """
        monitored = {str(path) for path in self.paths}
        requested = [Path(path) for path in trusted_paths]
        unmonitored = [str(path) for path in requested if str(path) not in monitored]
        if unmonitored:
            raise ValueError(f'Cannot trust unmonitored path(s): {", ".join(unmonitored)}')

        previous = self._read_state()
        if not previous:
            previous = self._snapshot()
        else:
            for path in requested:
                previous[str(path)] = _digest(path)
        self._write_state(previous)

    def check(self) -> list[TamperChange]:
        current = self._snapshot()
        if not self.state_path.exists():
            self._write_state(current)
            return []
        previous = self._read_state()
        if not previous:
            # A missing/corrupt baseline cannot be compared safely. Re-seed it
            # rather than crashing the security daemon or inventing tamper.
            self._write_state(current)
            return []
        changes = [
            TamperChange(path, previous.get(path), digest)
            for path, digest in current.items()
            if path in previous and previous.get(path) != digest
        ]
        if changes or set(previous) != set(current):
            self._write_state(current)
        return changes
