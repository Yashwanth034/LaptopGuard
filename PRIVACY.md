# Privacy

LaptopGuard is designed to run locally on the protected Linux laptop. The project does not operate a LaptopGuard cloud service, analytics service, advertising service, or user-account backend.

## Data LaptopGuard may collect

Only enabled features and qualifying security events determine what is collected. Depending on the event and available hardware, LaptopGuard may process:

- webcam photographs;
- desktop screenshots;
- timestamps, hostname, event type, and local security state;
- connected Wi-Fi SSID and nearby Wi-Fi BSSID/signal information;
- physical-location coordinates, accuracy, and location-source metadata;
- VPN/network state;
- integrity hashes and event/tamper metadata.

Normal boot, resume, lock/unlock, ordinary unlocked shutdown, and reboot are not treated as new theft events by the current policy.

## Local storage

Installed configuration is stored under `/etc/laptopguard` with restrictive permissions. Runtime state, evidence, queue data, location cache, and event history are stored under `/var/lib/laptopguard`.

Offline queued evidence is encrypted with Fernet using a machine-local key stored outside this repository. Temporary event evidence directories older than roughly 24 hours are cleaned by the engine. Queued evidence can remain until delivery, quarantine/pruning, or manual removal.

To remove LaptopGuard while preserving local configuration/evidence:

```bash
sudo bash uninstall.sh
```

To remove LaptopGuard and its local configuration/evidence:

```bash
sudo bash uninstall.sh --purge
```

## External services

LaptopGuard communicates externally only when a configured feature requires it.

### Email

When SMTP delivery is enabled, alert text and selected evidence attachments are sent to the SMTP server and recipient configured by the administrator. Gmail is supported through SMTP, but LaptopGuard is not tied to a LaptopGuard-operated mail service.

### ntfy

When optional ntfy support is configured and activated, protected power-off notifications are sent to `https://ntfy.sh` using the private topic stored locally. Depending on the protected-shutdown path, the notification may include event metadata and a webcam image/location summary.

Treat an ntfy topic as a secret capability URL component. Use a long, random topic name and never commit it to source control.

### Wi-Fi positioning

Wi-Fi positioning can send nearby access-point identifiers and signal/channel information to supported geolocation providers, including BeaconDB and Mylnikov. If a local Google Geolocation API key is configured, Google Geolocation may also be queried.

Do not enable Wi-Fi positioning if sharing nearby access-point identifiers with those providers is unacceptable for your environment.

### IP location

When enabled and allowed by VPN policy, the low-confidence IP fallback can query `ipapi.co`. LaptopGuard does not present a detected VPN exit IP as the laptop's physical location.

### Browser geolocation

Optional browser geolocation uses a dedicated LaptopGuard Chrome/Chromium/Brave profile. It does not reuse the user's normal browser profile, cookies, tabs, or history. The browser/vendor's own geolocation implementation and privacy policy apply to that request.

### Local location services

GNSS/GPS through ModemManager/gpsd and GeoClue can be used when available. Their behavior depends on the operating system, hardware, and any upstream services configured by the distribution.

## Credentials and secrets

Repository source and examples do not contain runtime credentials. The installer/configuration flow keeps SMTP credentials, ntfy topic data, and optional Google geolocation credentials in local root-controlled files outside the repository.

Do not place credentials in `config.example.toml`, issues, screenshots, logs shared publicly, commits, or pull requests.

## No stealth guarantee

LaptopGuard does not attempt to disable webcam privacy indicators. Operating-system notifications, camera LEDs, browser permission UI, or other platform indicators may remain visible.

## Legal use

Use LaptopGuard only on systems you own or are authorized to administer. Laws concerning monitoring, location collection, photography, and employee/device tracking vary by jurisdiction.
