# LaptopGuard

**Open-source laptop anti-theft evidence and recovery agent. Full automated protection on Linux Mint/Ubuntu, with a portable recovery mode for Windows and macOS.**

LaptopGuard collects useful recovery evidence while keeping credentials and runtime data on the protected computer. It can capture a quality-checked webcam photo, take a desktop screenshot when the OS permits it, resolve trustworthy physical location, record network context, deliver alerts by SMTP, and preserve offline evidence in an encrypted local queue for later retry.

Current version: **v0.1.25**

## Platform support

| Platform | Support level | Available now |
| --- | --- | --- |
| Linux Mint / Ubuntu with systemd | **Full protection** | Failed-local-login trigger, protected lock/login-screen power-off handling, webcam and screenshot evidence, location, encrypted queue, SMTP/ntfy alerts, tracking, tamper monitoring, watchdog/resume integration, hardening audit |
| Windows | **Portable mode** | Manual evidence test, webcam capture, desktop screenshot, location/browser geolocation, encrypted queue, SMTP delivery, tracking, flush, diagnostics |
| macOS | **Portable mode** | Manual evidence test, webcam capture, desktop screenshot, location/browser geolocation, encrypted queue, SMTP delivery, tracking, flush, diagnostics |

Windows and macOS portable mode does **not yet** install autonomous failed-login monitoring, protected power-off interception, Linux tamper rules, or systemd-style service hooks. Camera, screen-capture, and location features also depend on the OS privacy permissions granted to Python/Terminal and the browser. GitHub Actions runs portable smoke tests on both Windows and macOS so these platforms cannot silently regress.

## Why LaptopGuard

LaptopGuard is designed for people looking for a self-hosted Linux laptop anti-theft, stolen-laptop recovery, failed-login monitoring, webcam evidence, geolocation, tamper detection, and offline alerting tool without a mandatory cloud account.

Key capabilities:

- Local failed-login protection with a strict **third-attempt-within-2-minutes** trigger.
- Quality-checked webcam evidence with face, brightness, and sharpness checks.
- Desktop screenshot capture when the active graphical session permits it.
- VPN-aware location using GNSS/GPS, Wi-Fi positioning, GeoClue, a dedicated browser geolocation profile, and optional low-confidence IP fallback.
- Encrypted offline evidence queue with retry after connectivity returns.
- Optional SMTP/Gmail email alerts.
- Optional private-topic **ntfy** alerts for protected power-off events.
- Locked-session and initial-login-screen power-off protection.
- Tamper monitoring for critical LaptopGuard and Linux account/boot files.
- systemd service, watchdog timer, resume readiness handling, and trusted-update recovery.
- Read-only hardening audit for Secure Boot, disk encryption, GRUB protection, and related controls.

## Trigger policy

LaptopGuard deliberately avoids treating ordinary laptop activity as theft.

- First and second wrong local passwords only increment the short-lived failed-auth counter.
- The third wrong local password within two minutes triggers the full evidence workflow.
- Failed SSH, sudo, polkit, and other remote/non-local authentication failures are ignored by the local-theft policy.
- Normal boot, suspend/resume, lock/unlock, unlocked shutdown, and reboot do not create new theft evidence.
- Power-off while the desktop is already locked, or from the initial login screen, can enter the protected power-off evidence path.

See [docs/TESTING.md](docs/TESTING.md) for the real-device verification matrix.

## Privacy model

LaptopGuard has **no LaptopGuard-operated central server** and no built-in analytics/telemetry service. Runtime data stays on the laptop unless a configured feature needs to contact an external service.

Depending on your configuration, external communication may include:

- your configured SMTP server for email alerts;
- `https://ntfy.sh` when optional ntfy push is enabled;
- BeaconDB and Mylnikov for Wi-Fi positioning;
- Google Geolocation only when a local Google geolocation key is configured;
- `ipapi.co` only when IP fallback is allowed and VPN policy permits it;
- the browser Geolocation API through LaptopGuard's dedicated browser profile.

Wi-Fi positioning can send nearby access-point identifiers/signal information to the selected positioning provider. Review [PRIVACY.md](PRIVACY.md) before enabling location features.

Credentials and runtime secrets are not stored in this repository. Installed configuration is root-private under `/etc/laptopguard`; runtime state/evidence is under `/var/lib/laptopguard`.

## Install

LaptopGuard requires Python 3.10+.

### Linux Mint / Ubuntu — full protection

After cloning or downloading the repository:

```bash
cd LaptopGuard
sudo bash install.sh
```

On a fresh installation:

```bash
sudo laptopguard configure
sudo laptopguard doctor
sudo laptopguard test
```

The Linux installer preserves existing `/etc/laptopguard` configuration and `/var/lib/laptopguard` runtime state during normal upgrades.

### Windows — portable mode

From PowerShell in the repository folder:

```powershell
py -m pip install .
laptopguard configure
laptopguard doctor
laptopguard test
```

Runtime data is stored under `%LOCALAPPDATA%\LaptopGuard`. Windows may ask for Camera and screen-capture permissions when those features are first used.

### macOS — portable mode

From Terminal in the repository folder:

```bash
python3 -m pip install .
laptopguard configure
laptopguard doctor
laptopguard test
```

Runtime data is stored under `~/Library/Application Support/LaptopGuard`. Grant Terminal/Python Camera and Screen Recording permissions when macOS requests them.

On Windows/macOS, `laptopguard daemon` can keep queue retry and temporary location tracking active in the current user session. Automatic OS security-event hooks are currently Linux-only.

## Optional ntfy backup alerts

Configure only a private random topic name, not a full URL:

```bash
sudo laptopguard configure-push YOUR_PRIVATE_RANDOM_TOPIC
sudo laptopguard test-push
```

The topic is stored in a root-only local file and is not committed to the repository.

## Optional browser geolocation

When VPN use or local Linux location services prevent a good physical fix, LaptopGuard can use a dedicated Chrome/Chromium/Brave profile.

Run once from the normal logged-in desktop account:

```bash
sudo laptopguard browser-location-setup
```

LaptopGuard does not reuse the user's normal browser profile, cookies, tabs, or history. Background probes proceed only after permission has already been granted; they do not silently create a permission prompt.

## Useful commands

```bash
sudo laptopguard status
sudo laptopguard doctor
sudo laptopguard test
sudo laptopguard location-test
sudo laptopguard browser-location-setup
sudo laptopguard flush
sudo laptopguard tracking status
sudo laptopguard tracking on
sudo laptopguard tracking off
sudo laptopguard hardening-audit
```

Service logs:

```bash
sudo journalctl -u laptopguard.service -f
```

## Location strategy

LaptopGuard prefers stronger physical-location sources over weaker ones:

1. GNSS/GPS through ModemManager or gpsd when compatible hardware exists.
2. Wi-Fi positioning through supported providers.
3. Previously verified local Wi-Fi/location cache.
4. GeoClue when it returns a sufficiently trustworthy fix.
5. Dedicated browser geolocation when configured.
6. IP geolocation only as a low-confidence fallback when allowed and a VPN is not being mistaken for physical location.

A VPN exit IP is not presented as the laptop's physical location.

## Security design

LaptopGuard is intentionally conservative about privileged behavior:

- it does not disable webcam privacy LEDs;
- it does not wipe disks;
- it does not automatically modify LUKS, UEFI, Secure Boot, or firmware settings;
- it stores SMTP credentials and optional ntfy topics outside the source tree;
- queued evidence is encrypted locally with a machine-local key;
- normal upgrades refresh tamper baselines only for LaptopGuard-managed files.

Read [SECURITY.md](SECURITY.md) and [docs/HARDENING.md](docs/HARDENING.md) before relying on LaptopGuard as part of a physical-security plan.

## Important limitations

LaptopGuard is a recovery/evidence aid, not a guarantee against physical theft. A root-level attacker, disk replacement, factory reset/reinstallation, destroyed storage, disabled networking, removed power, or hardware destruction can defeat software controls. Location accuracy depends on available hardware, nearby Wi-Fi data, provider coverage, permissions, and connectivity.

Use LaptopGuard only on computers you own or are authorized to administer, and comply with applicable privacy and monitoring laws.

## Uninstall

Remove the application while preserving configuration/evidence:

```bash
sudo bash uninstall.sh
```

Remove the application **and** local LaptopGuard configuration/evidence:

```bash
sudo bash uninstall.sh --purge
```

## Development and tests

```bash
PYTHONPATH=src python3 -m pytest -q
```

The v0.1.25 Linux regression suite passes **159 tests** with 2 non-Linux-only smoke tests skipped; Windows and macOS run their portable smoke suite separately in GitHub Actions.

More documentation:

- [Changelog](CHANGELOG.md)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Hardening guide](docs/HARDENING.md)
- [Real-device testing](docs/TESTING.md)

## License

LaptopGuard is released under the [MIT License](LICENSE).
