# Data-preserving anti-reset hardening

LaptopGuard detects several forms of tampering, but detection is not a substitute for protecting the boot chain and disk.

## Target state

A well-protected laptop should have:

1. **LUKS full-disk encryption** for the Linux system/data volume.
2. **Secure Boot enabled** where the installed kernel/modules support it.
3. A **UEFI/firmware administrator password**.
4. External/USB boot disabled or firmware-password protected.
5. A **GRUB password** protecting recovery/edit access.
6. A strong Linux login password and a separately stored LUKS recovery passphrase/key.

Together, these make a simple offline Linux-password reset ineffective because the attacker cannot mount the encrypted system volume without the disk secret.

## Check first

```bash
sudo laptopguard hardening-audit
```

The command is read-only. It does not change partitions, firmware or boot configuration.

## LUKS warning

Do **not** run an automated in-place root-disk encryption command merely to satisfy this project. Converting an existing live root filesystem is a high-risk operation if power, storage, bootloader or recovery-key handling goes wrong.

If the audit reports that the system is not encrypted, make a verified backup first. The safest route is normally enabling full-disk encryption during a supported Linux installation/migration process, then restoring data.

## Firmware / boot

Firmware-password and external-boot settings are vendor-specific and must be configured in the laptop's UEFI setup. Record the firmware password in a secure password manager; losing it can create a recovery problem.

Secure Boot state can usually be checked with:

```bash
mokutil --sb-state
```

GRUB password configuration is distro-specific. After enabling it, verify normal boot and recovery behavior before relying on it.

## What LaptopGuard monitors

The daemon fingerprints critical account/boot files such as `/etc/passwd`, `/etc/group`, `/etc/shadow`, `/etc/sudoers`, `/etc/default/grub`, and `/boot/grub/grub.cfg`. A change between checks or across reboots creates a tamper event and activates temporary location tracking.

A root-level attacker can ultimately disable software controls. The disk/firmware protections above are what protect your data when the attacker has physical access.
