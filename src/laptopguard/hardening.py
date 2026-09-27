from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class HardeningCheck:
    name: str
    ok: bool | None
    detail: str


def parse_secure_boot(text: str) -> bool | None:
    value = text.strip().lower()
    if 'enabled' in value:
        return True
    if 'disabled' in value:
        return False
    return None


def lsblk_has_crypt(text: str) -> bool:
    return any(line.strip().lower() == 'crypt' for line in text.splitlines())


def audit() -> list[HardeningCheck]:
    checks: list[HardeningCheck] = []

    uefi = Path('/sys/firmware/efi').exists()
    checks.append(HardeningCheck('UEFI boot', uefi, 'UEFI firmware detected' if uefi else 'System does not appear to be booted in UEFI mode'))

    if shutil.which('mokutil'):
        try:
            result = subprocess.run(['mokutil', '--sb-state'], capture_output=True, text=True, timeout=5, check=False)
            state = parse_secure_boot(result.stdout + result.stderr)
            checks.append(HardeningCheck('Secure Boot', state, (result.stdout + result.stderr).strip() or 'Unable to determine Secure Boot state'))
        except Exception as exc:
            checks.append(HardeningCheck('Secure Boot', None, str(exc)))
    else:
        checks.append(HardeningCheck('Secure Boot', None, 'mokutil is not installed'))

    encrypted = None
    detail = 'Unable to determine root storage encryption'
    if shutil.which('findmnt') and shutil.which('lsblk'):
        try:
            source = subprocess.run(['findmnt', '-no', 'SOURCE', '/'], capture_output=True, text=True, timeout=5, check=False).stdout.strip()
            if source:
                chain = subprocess.run(['lsblk', '-s', '-no', 'TYPE', source], capture_output=True, text=True, timeout=5, check=False).stdout
                encrypted = lsblk_has_crypt(chain)
                detail = f'Root source: {source}; crypt layer ' + ('found' if encrypted else 'not found')
        except Exception as exc:
            detail = str(exc)
    checks.append(HardeningCheck('LUKS/root encryption', encrypted, detail))

    grub_files = [Path('/etc/grub.d/01_users'), Path('/etc/grub.d/40_custom'), Path('/boot/grub/user.cfg')]
    grub_text = ''
    for path in grub_files:
        try:
            if path.is_file():
                grub_text += path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            pass
    grub_protected = 'password_pbkdf2' in grub_text
    checks.append(HardeningCheck('GRUB password', grub_protected, 'GRUB password entry detected' if grub_protected else 'No GRUB password entry detected'))

    return checks
