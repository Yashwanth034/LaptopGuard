# Changelog

Release notes retained from the v0.1.x development series. Newer entries supersede older behavior where policies changed.

## v0.1.25

- Fixes screenshot capture under unprivileged CI/test environments without weakening the root-owned Linux runtime path.
- Adds Windows and macOS portable mode for manual webcam/screenshot evidence, encrypted queueing, SMTP delivery, location/browser geolocation, tracking, flush, and diagnostics.
- Adds platform-safe application-data/config paths, hostname/boot/session helpers, portable timeline locking, browser discovery, camera probing, and screenshot helpers.
- Keeps Linux Mint/Ubuntu as the full-protection platform: failed-login monitoring, protected power-off hooks, Linux tamper rules, systemd integration, and hardening audit remain Linux-only.
- Adds Windows/macOS GitHub Actions smoke coverage while retaining the complete Linux regression suite.

## v0.1.24

- Fixes `sudo laptopguard hardening-audit` so GRUB PBKDF2 authentication configured in `/etc/grub.d/01_users` is detected correctly.
- Adds regression coverage for the `/etc/grub.d/01_users` layout used by the verified GRUB hardening setup.
- No capture, alert, shutdown/reboot, tamper, location, queue, ntfy, Gmail, or other runtime security policy is changed.

## v0.1.23

- Restores the strict protected-poweroff policy: **normal unlocked shutdown, restart/reboot, and ordinary lock/unlock do not capture or notify**, even when ntfy is enabled. Only power-off while already locked or power-off from the initial login screen enters the shutdown evidence path.
- ntfy protected-poweroff alerts now attach the captured webcam JPEG directly to the notification and include a physical-location map link/accuracy when available. A recent last-known fix (maximum age 30 minutes) is used only when the live shutdown probe cannot finish quickly, and is clearly labeled `last-known:` in the location source.
- A successful ntfy send no longer deletes the encrypted Gmail queue item. The same photo/screenshot/location evidence stays queued and is delivered by the existing Gmail retry path after boot/reconnect. ntfy mode still never attempts SMTP inside the shutdown window.
- Removes visible shutdown-capture effects: the shutdown webcam retry no longer raises brightness or opens the white-screen illuminator, and X11 screenshots prefer silent `scrot` before `gnome-screenshot`. The installer now includes `scrot`.
- The shutdown guard keeps the existing **5-second maximum** safety deadline, but it does not intentionally wait 5 seconds; it returns as soon as protected-shutdown work finishes.
- All non-shutdown LaptopGuard policies remain unchanged.

## v0.1.22

- Adds optional ntfy shutdown/reboot push notifications through the public `https://ntfy.sh` service. Configure only a private random topic name with `sudo laptopguard configure-push TOPIC_NAME`, then activate it with `sudo laptopguard test-push`.
- `test-push` is isolated: it sends one small HTTPS POST and does not invoke the webcam, screenshot, location, VPN, brightness, failed-login, or full intrusion workflow.
- Once `test-push` succeeds, shutdown/reboot alerts use ntfy during a hard 5-second maximum guard window. The push contains only event type, timestamp, hostname, and photo/location evidence flags; photo binaries are never placed in the push payload.
- If ntfy fails or times out, shutdown/reboot continues. The already-encrypted evidence queue is retained/enriched and the existing Gmail queue path retries it after the next boot/reconnect. Gmail is not attempted inside the ntfy shutdown window.
- When push has not been activated, v0.1.21 shutdown behavior is unchanged, including its bounded fast Gmail path for lock-screen and initial-login-screen power-off. All non-shutdown LaptopGuard behavior remains unchanged.
- Android ntfy should use the normal Google Play/FCM path: **Use another server = OFF** and **Instant delivery in doze mode = OFF**. Do not paste the topic URL into the Android server field; subscribe to the private topic name on the default ntfy.sh server.

## v0.1.21

- Adds **fast pre-shutdown Gmail delivery** for lock-screen and initial login-screen power-off alerts. LaptopGuard now fsyncs the captured photo to the encrypted queue, reads only the current Wi-Fi SSID with a sub-second budget, then attempts one bounded SMTP delivery **before** slower screenshot/location enrichment.
- The built-in shutdown SMTP path uses a short 2-second network timeout so it fits inside systemd's finite delay-inhibitor window. Normal/manual alerts keep the ordinary SMTP timeout.
- If the fast pre-shutdown email succeeds, shutdown proceeds without waiting for geolocation; the message may therefore show `Location: unavailable` and may contain only the photo plus current Wi-Fi. This is intentional: immediate delivery is prioritized over slow enrichment.
- If fast SMTP cannot complete, the already-encrypted queue item remains safe and is enriched with screenshot/full metadata/location as time permits. The next boot/reconnect sends that same queued alert once, with recovered location when available.
- v0.1.20's strict third-wrong-password-only policy and initial login-screen shutdown detection remain unchanged.

## v0.1.20

- Failed-auth policy is now strict **third-attempt only**: the first and second wrong local passwords only advance the 2-minute counter. They do not open the camera, take a screenshot, resolve location, enable tracking, or send email. The third wrong password performs the complete evidence capture and sends/queues one full alert.
- Adds **initial login-screen shutdown protection** for Linux Mint/LightDM. A real `poweroff` from the boot/login greeter now uses the same crash-safe queue-first evidence path as a lock-screen shutdown. Restart is still ignored, and an ordinary shutdown from an unlocked user session still does nothing.
- Login-screen detection prefers an active local logind `greeter` session and includes a Mint Slick Greeter fallback for LightDM builds whose greeter session disappears or is not exposed during shutdown.

## v0.1.19

- Replaces shutdown-time-only lock detection with a **pre-shutdown lock-state cache**. LaptopGuard now remembers lock/unlock transitions before systemd begins tearing down the desktop, so Linux Mint reporting `LockedHint=no` during a visible password screen can no longer erase a previously observed lock.
- Watches systemd-logind `Session.Lock` / `Session.Unlock` on the system bus and Cinnamon/GNOME `ScreenSaver.ActiveChanged` on the logged-in user session bus. Either source can update the cache; the existing shutdown-time probe is now only a fallback when no transition has ever been observed.
- Keeps the shutdown policy unchanged: **locked + power-off** can alert, `reboot` is ignored, and ordinary unlocked shutdown remains non-alerting.
- The session-bus watcher runs as the graphical user and does not read the root-only LaptopGuard configuration or secrets.
- Adds regression coverage for the exact Mint failure mode: cached `locked=True` must win even when the later shutdown-time probe incorrectly returns false.

## v0.1.18

- Fixes the real Linux Mint/systemd 255 lock-screen shutdown path: systemd v255 emits shutdown metadata type `poweroff`, while v0.1.17 only matched the documented spelling `power-off`. LaptopGuard now normalizes both forms and still explicitly ignores `reboot`.
- Hardens lock detection during shutdown by checking all local graphical user sessions for `LockedHint=yes` before falling back to the active desktop screensaver API. This avoids losing the locked state if session activity changes during shutdown teardown.
- Adds shutdown-guard journal diagnostics (`type`, `locked`, delivery result) so any future real-device failure is directly observable instead of silently ignored.
- All v0.1.17 queue-first encrypted shutdown evidence, failed-auth, offline/reconnect, passive-doctor, boot/resume, and tamper protections remain unchanged.

## v0.1.17

- Adds a **shutdown-only lock-screen guard**. A normal unlocked shutdown remains normal, and restart is explicitly ignored. When systemd-logind reports a real `power-off` while the graphical session is locked, LaptopGuard captures a fast photo, persists it immediately to the encrypted queue, then enriches the same queue item with screenshot, Wi-Fi/location metadata and sends one full alert when possible.
- Uses systemd's delay inhibitor only while waiting for a shutdown request. It never permanently blocks shutdown; a forced physical power-off still cannot be guaranteed by software.
- The queue-first path is crash-safe: if the machine powers off before location/SMTP complete, the durable alert is retried and location-enriched after connectivity/boot returns.
- Reboot from the lock screen does **not** trigger this alert.

## v0.1.16

- Trusted upgrades no longer create false tamper events. The installer refreshes **only** the baseline entries for LaptopGuard-managed files after replacing them; monitored OS/account/boot files keep their previous hashes and are never trusted by an update.
- The tamper daemon is maintenance-aware, so checks are suppressed only while `/run/laptopguard-maintenance` exists and resume normally after the trusted install window.
- Tamper coverage now includes every installed LaptopGuard integration point used by the service: launcher, config, main/resume/watchdog systemd units, watchdog timer, sleep hook, and watchdog script.
- `sudo laptopguard doctor` is now fully passive for evidence collection: it no longer opens the webcam or takes a test screenshot. It checks device/session/helper availability only. Active capture remains exclusive to explicit security/test events.
- Tamper baseline writes are atomic and root-private, preventing partial-state files from update/service races.
- All v0.1.15 lifecycle, browser-permission, failed-auth, offline queue, reconnect-location, and one-email policies remain unchanged.
## Older retained release notes

### v0.1.15

- Normal boot and sleep/resume no longer create new photo/screenshot/location/email alerts.
- Resume is readiness/reconnect only and may retry previously queued security evidence.
- Doctor location diagnostics are passive and do not launch the browser.
- Background browser-location paths proceed only after permission is already granted; only the explicit setup command may prompt.

### v0.1.14

- Queued alerts created without a trustworthy location are re-checked before delivery after connectivity returns.
- Recovered location enriches the outgoing alert without replacing the original event timestamp/evidence.

### v0.1.13

- Offline operation no longer launches browser geolocation or network-only Wi-Fi/IP positioning providers.
- Offline evidence is encrypted/queued for later delivery; local GNSS/cache/GeoClue paths can still be used when available.
- Failed local-password handling uses the three-attempt/two-minute policy: attempts one and two are counter-only, and attempt three triggers the evidence workflow.
