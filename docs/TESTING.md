# Real-device verification checklist — v0.1.25

## Update and pre-flight

```bash
sudo bash install.sh
sudo laptopguard doctor
```

On an upgrade, do not rerun `configure` unless SMTP details need changing.

## VPN-aware location

1. Leave the VPN enabled.
2. Run `sudo laptopguard location-test` first.
3. Confirm it returns `modem-gps`, `gpsd`, `wifi-beacondb`, `wifi-mylnikov`, `wifi-google`, `wifi-consensus`, Wi-Fi cache, or a sufficiently precise GeoClue fix.
4. Confirm the returned map point matches the laptop's real physical area and review the accuracy radius.
5. Run `sudo laptopguard test` and confirm the email reports `VPN: detected` when applicable.
6. Confirm a VPN exit IP is never reported as physical location.
7. Disable VPN and repeat; IP location may appear only as a low-confidence fallback if stronger sources are unavailable.

## Daylight capture

1. Sit in front of the laptop in normal light.
2. Run `sudo laptopguard test`.
3. Confirm the face is recognizable and sharp.
4. Confirm an RGB image is used rather than an IR/depth stream.

## Low-light capture

1. Note current display brightness.
2. Test in a dark room.
3. Confirm the internal display temporarily brightens and a white fullscreen illuminator appears when a desktop session exists.
4. Confirm brightness returns to the exact previous level after success and failure.

## Screenshot/session

1. Run a manual test while logged into Cinnamon/X11 or Wayland.
2. Confirm `screenshot.png` is attached.
3. Lock/log out and test an event path; camera/location must continue even if no screenshot can be taken.

## Failed login filtering

1. Enter one wrong password at the local lock/login screen; confirm no photo/email/location action.
2. Enter a second wrong password within 2 minutes; confirm there is still no camera capture, screenshot, location lookup, or email.
3. Enter a third wrong password within 2 minutes; confirm the complete alert is delivered.
4. Enter one wrong `sudo` password in a terminal; confirm no theft alert.
5. If SSH is enabled, a remote failed SSH password must not trigger a local-theft photo event.

## Offline queue and corruption recovery

1. Disconnect all network paths.
2. Trigger `sudo laptopguard test` and confirm a `.lgq` file appears under `/var/lib/laptopguard/queue`.
3. Reconnect and run `sudo laptopguard flush`.
4. Confirm successful delivery removes the queue item.
5. Corrupt only a disposable test queue item if specifically testing recovery; `doctor` should report corruption and normal retry must continue with later valid items.

## Boot/resume lifecycle safety

1. Suspend and resume the laptop. Confirm no new photo, screenshot, location prompt, or Gmail alert is created solely because of wake-up.
2. Confirm the resume hook restores readiness and the service/watchdog remain active.
3. Reboot normally and confirm no new boot photo/email is generated.
4. If a real security alert was already queued, boot/resume may retry that existing queued alert; that is not a new lifecycle alert.

## Browser permission privacy

1. `sudo laptopguard doctor` must remain passive: no browser, location-permission prompt, camera capture/light, or screenshot capture.
2. Normal failed-auth/tamper/flush/tracking/location-test background probes must never show a permission prompt.
3. If the dedicated browser permission is reset to prompt/denied, those paths must fail silently.
4. Only `sudo laptopguard browser-location-setup` may intentionally display the browser permission prompt.

## Tracking

```bash
sudo laptopguard tracking on
sudo laptopguard tracking status
```

Move between known Wi-Fi areas if practical and verify location-history entries show their source and accuracy. If no GNSS exists, completely new locations still require connectivity once so their Wi-Fi fingerprint can be resolved and cached.

## Trusted-update tamper safety

1. Install/update LaptopGuard normally with `sudo bash install.sh`.
2. Confirm the update itself creates no new `tamper` event/Gmail alert.
3. Confirm `sudo laptopguard doctor` reports the service/watchdog healthy after update.
4. Do not edit `/etc/shadow`, GRUB, LUKS, or firmware settings for testing. If testing tamper detection, change only a disposable LaptopGuard-managed test copy in an isolated test environment.

## Tamper and hardening

```bash
sudo laptopguard hardening-audit
```

Use only safe account/config changes for testing. Do not alter bootloader, LUKS keys or firmware settings solely to force a test.

## Lock-screen shutdown

1. Confirm an unlocked normal shutdown does not send an alert.
2. Confirm a restart from the lock screen does not send an alert.
3. Lock the session using the normal Mint lock screen, wait a moment for the lock-state cache, choose Shut Down, then power the laptop back on.
4. Confirm exactly one `lockscreen_shutdown` alert is sent. Preferably it arrives before power-off; if SMTP cannot finish inside the shutdown window, it must arrive from the encrypted queue on next boot.
5. For a pre-shutdown fast delivery, confirm the photo is present and current Wi-Fi is shown when available. Location/screenshot may be absent by design because delivery is prioritized. For queued fallback, screenshot/location are enriched when available and missing location is recovered before delivery.

## Initial login-screen shutdown

1. Reboot to the normal LightDM/Slick Greeter password screen and do not log in.
2. Choose Shut Down, not Restart.
3. Power the laptop back on and log in normally.
4. Confirm event history contains `login_screen_shutdown` followed by the next `boot`, and confirm exactly one alert is delivered. Preferably the fast photo/Wi-Fi email arrives before power-off; otherwise the encrypted queue must recover it on next boot.
5. A fast pre-shutdown email may show `Location: unavailable`; queued fallback should recover location when connectivity/session capability returns.
6. A Restart from the same screen must not generate this security event.


## Protected-poweroff ntfy + queued Gmail (v0.1.23)

1. Run `sudo laptopguard test-push` once and confirm the test push arrives without camera/screenshot/location activity.
2. While logged in and unlocked, choose **Shut Down**. Confirm there is **no** LaptopGuard capture, ntfy alert, or new Gmail evidence.
3. Perform **Restart** from both unlocked and locked/login screens. Confirm there is **no** LaptopGuard capture or notification.
4. Lock the session, wait briefly for the lock-state cache, then choose **Shut Down**. Confirm ntfy arrives with the webcam JPEG attached and a location/map link when a live or recent fix exists. Shutdown must not be held for an artificial 5-second wait.
5. Reboot to the LightDM/Slick Greeter login screen without entering a password and choose **Shut Down**. Confirm the same protected alert behavior.
6. After the next boot/network recovery, confirm the queued Gmail alert is delivered with the retained photo and any captured screenshot/location.
7. During protected shutdown capture, confirm there is no white-screen/brightness flash. On X11, `scrot` should be used before `gnome-screenshot`.


## ntfy shutdown/reboot push (v0.1.22)

1. Configure only a private random topic name: `sudo laptopguard configure-push TOPIC_NAME`. Full `http://` or `https://` URLs must be rejected.
2. On Android ntfy, keep **Use another server** OFF and **Instant delivery in doze mode** OFF; subscribe on the default ntfy.sh server.
3. Run `sudo laptopguard test-push`. Confirm one push arrives and that no webcam light, screenshot, location probe, VPN change, or brightness change occurs.
4. After a successful test, perform a normal reboot and shutdown. Confirm the push arrives before power-off/restart and shutdown is never held beyond the finite guard window.
5. Repeat a shutdown while ntfy is unreachable. Confirm shutdown still proceeds, evidence remains queued, and Gmail delivers that queued evidence after the next boot/reconnect.
6. Confirm failed-login, tamper, manual test, suspend/resume, camera quality, location, VPN/network, brightness restoration, and existing Gmail behavior outside this shutdown/reboot path are unchanged.
