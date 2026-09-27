# Security Policy

## Supported version

The current supported public source release is **v0.1.25**. Security fixes should be evaluated against the latest commit on the default branch.

## Reporting a vulnerability

Please do not publish exploitable details, credentials, private evidence, or real device/location data in a public issue.

After the GitHub repository is published, use GitHub's private vulnerability-reporting / security-advisory flow when available. If a public issue is the only available channel, report only enough information to establish that a security problem exists and wait before sharing sensitive reproduction details.

## Security model

LaptopGuard runs privileged components because it integrates with systemd, authentication-event monitoring, hardware capture, and protected configuration/state directories. Its security design therefore focuses on limiting what those privileged components can do.

Important controls include:

- runtime credentials stored outside the repository in root-controlled files;
- `/etc/laptopguard` and `/var/lib/laptopguard` created with restrictive permissions;
- encrypted offline queue data using a machine-local Fernet key;
- atomic queue/tamper-state updates where data integrity matters;
- a strict local failed-auth trigger policy that excludes sudo, SSH, and unrelated authentication failures;
- no arbitrary remote shell or remote-code-execution interface;
- no disk wipe or automatic firmware/LUKS modification;
- passive `doctor` and read-only `hardening-audit` behavior;
- trusted installer maintenance windows that refresh tamper baselines only for LaptopGuard-managed files.

## Threat model and limitations

LaptopGuard can help collect evidence and retain useful state during theft-related events, but software cannot guarantee control of a physically captured machine.

A sufficiently privileged attacker can stop/replace services, boot another operating system when the boot chain permits it, replace or destroy storage, disable networking, remove power, or reinstall the operating system. LaptopGuard should therefore be combined with full-disk encryption, Secure Boot where supported, firmware/boot protections, and strong account credentials.

Run:

```bash
sudo laptopguard hardening-audit
```

and review [docs/HARDENING.md](docs/HARDENING.md).

## Secret-handling rules for contributors

Never commit:

- SMTP/app passwords;
- ntfy private topics;
- Google geolocation API keys;
- browser profiles/cookies;
- real evidence photos/screenshots;
- queue keys or encrypted runtime queues;
- personal configuration files;
- private host/user paths that identify a real contributor unnecessarily.

Use placeholders and `example.com` addresses in tests/documentation.

## Dependency and update safety

Before publishing a change:

```bash
PYTHONPATH=src python3 -m pytest -q
```

Review installer/systemd changes carefully because they execute with elevated privileges. Avoid expanding capture triggers or network destinations without explicit documentation and regression tests.
