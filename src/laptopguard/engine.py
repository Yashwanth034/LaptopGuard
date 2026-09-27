from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Callable

from .alerts import format_alert
from .auth_attempts import FailedAuthTracker
from .brightness import BrightnessController
from .camera import capture_best
from .config import Settings
from .evidence import active_ssid, base_metadata, capture_screenshot, write_metadata
from .location import LocationSample, append_history, collect_location
from .illumination import ScreenIlluminator
from .mailer import send
from .queue_store import EncryptedQueue
from .push import is_enabled as push_is_enabled, read_topic, send_notification
from .platform_support import hostname
from .rate_limit import RateLimiter
from .readiness import wait_for_hardware
from .timeline import EventTimeline
from .storage import StorageReserve


@dataclass(frozen=True)
class EventResult:
    event: str
    delivery: str
    photo_captured: bool
    location_captured: bool


class SecurityEngine:
    def __init__(
        self,
        settings: Settings,
        camera_capture: Callable = capture_best,
        mail_send: Callable = send,
        screenshot_capture: Callable = capture_screenshot,
        location_collect: Callable = collect_location,
        metadata_factory: Callable = base_metadata,
        brightness_factory: Callable = BrightnessController,
        readiness_waiter: Callable = wait_for_hardware,
        illuminator_factory: Callable = ScreenIlluminator,
        shutdown_mail_send: Callable | None = None,
        push_send: Callable = send_notification,
    ):
        self.settings = settings
        self.camera_capture = camera_capture
        self.mail_send = mail_send
        # Normal alerts can use the ordinary SMTP timeout. Shutdown alerts run
        # under systemd's finite delay-inhibitor budget, so the built-in mailer
        # gets a deliberately short connect/login/send timeout. Tests and other
        # injected mail transports remain injectable without signature changes.
        if shutdown_mail_send is not None:
            self.shutdown_mail_send = shutdown_mail_send
        elif mail_send is send:
            self.shutdown_mail_send = lambda settings, subject, body, attachments: send(
                settings, subject, body, attachments, timeout=2.0
            )
        else:
            self.shutdown_mail_send = mail_send
        self.push_send = push_send
        self.screenshot_capture = screenshot_capture
        self.location_collect = location_collect
        self.metadata_factory = metadata_factory
        self.brightness_factory = brightness_factory
        self.readiness_waiter = readiness_waiter
        self.illuminator_factory = illuminator_factory
        self.state_dir = Path(settings.state_dir)
        self.evidence_dir = Path(settings.evidence_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.queue = EncryptedQueue(Path(settings.queue_dir), self.state_dir / 'queue.key')
        self.rate_limiter = RateLimiter(settings.rate_limit_seconds)
        self.failed_auth_tracker = FailedAuthTracker(
            self.state_dir / 'failed-auth-state.json',
            threshold=settings.failed_auth_threshold,
            window_seconds=settings.failed_auth_window_seconds,
        )
        self.pending_auth_dir = self.state_dir / 'pending-auth'
        self.pending_auth_dir.mkdir(parents=True, exist_ok=True)
        self.pending_auth_dir.chmod(0o700)
        self.pending_auth_photo = self.pending_auth_dir / 'attempt-2.jpg'
        self.tracking_path = self.state_dir / 'tracking-until'
        self.timeline = EventTimeline(self.state_dir)
        self.event_log = self.state_dir / 'event-history.jsonl'
        self.reserve = StorageReserve(self.state_dir / '.disk-reserve')
        try:
            self.reserve.ensure()
        except OSError:
            pass
        self._cleanup_stale_evidence()

    def push_enabled(self) -> bool:
        return push_is_enabled(self.state_dir, Path(self.settings.push.topic_file))

    def _cleanup_stale_evidence(self) -> None:
        cutoff = time.time() - 86400
        for path in self.evidence_dir.iterdir():
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass

    def _record_event(self, event: str, timeline: dict) -> None:
        record = {'event': event, **timeline}
        fd = os.open(self.event_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, separators=(',', ':')) + '\n')
            fh.flush()
            os.fsync(fh.fileno())

    def _capture_photo(self, target: Path):
        cfg = self.settings.capture
        kwargs = {
            'camera_index': -1 if getattr(cfg, 'auto_camera', True) else cfg.camera_index,
            'max_seconds': min(1.25, cfg.max_seconds),
            'min_brightness': cfg.min_brightness,
            'min_sharpness': cfg.min_sharpness,
            'require_face': cfg.require_face,
        }
        result = self.camera_capture(target, **kwargs)
        if result is not None:
            return result
        try:
            controller = self.brightness_factory()
            with controller.boosted(cfg.boost_brightness):
                with self.illuminator_factory().active():
                    time.sleep(0.35)
                    kwargs['max_seconds'] = cfg.max_seconds
                    return self.camera_capture(target, **kwargs)
        except Exception:
            try:
                kwargs['max_seconds'] = cfg.max_seconds
                return self.camera_capture(target, **kwargs)
            except Exception:
                return None

    def activate_tracking(self, minutes: int | None = None) -> None:
        duration = int(minutes if minutes is not None else self.settings.location.tracking_minutes)
        self.tracking_path.write_text(str(time.time() + max(1, duration) * 60), encoding='utf-8')
        os.chmod(self.tracking_path, 0o600)

    def deactivate_tracking(self) -> None:
        self.tracking_path.unlink(missing_ok=True)

    def tracking_active(self) -> bool:
        try:
            return float(self.tracking_path.read_text(encoding='utf-8').strip()) > time.time()
        except (OSError, ValueError):
            return False

    def cleanup_pending_failed_auth(self) -> None:
        try:
            age = time.time() - self.pending_auth_photo.stat().st_mtime
        except OSError:
            return
        if age > self.settings.failed_auth_window_seconds:
            self.pending_auth_photo.unlink(missing_ok=True)
            self.failed_auth_tracker.reset()

    def _recent_shutdown_location(self, max_age_seconds: float = 1800.0) -> LocationSample | None:
        """Return a recent last-known fix without doing any network/display work."""
        path = self.state_dir / 'location-history.jsonl'
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return None
        now = datetime.now(timezone.utc)
        for line in reversed(lines[-50:]):
            try:
                raw = json.loads(line)
                timestamp = str(raw.get('timestamp') or '')
                parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age = (now - parsed.astimezone(timezone.utc)).total_seconds()
                if age < 0 or age > float(max_age_seconds):
                    continue
                source = str(raw.get('source') or 'unknown')
                return LocationSample(
                    float(raw['latitude']),
                    float(raw['longitude']),
                    f'last-known:{source}',
                    float(raw['accuracy_m']) if raw.get('accuracy_m') is not None else None,
                    timestamp,
                    str(raw.get('confidence') or ''),
                    bool(raw.get('vpn_detected', False)),
                ).normalized()
            except Exception:
                continue
        return None

    def _shutdown_fast_photo(self, target: Path):
        """Capture shutdown evidence without any visible display effect."""
        cfg = self.settings.capture
        kwargs = {
            'camera_index': -1 if getattr(cfg, 'auto_camera', True) else cfg.camera_index,
            'max_seconds': min(1.0, cfg.max_seconds),
            'min_brightness': cfg.min_brightness,
            'min_sharpness': cfg.min_sharpness,
            'require_face': cfg.require_face,
        }
        try:
            result = self.camera_capture(target, **kwargs)
        except Exception:
            result = None
        if result is not None:
            return result

        # Shutdown/lock-screen capture must stay invisible. Retry the camera once
        # with a slightly larger frame budget, but never boost brightness or open
        # the white-screen illuminator used by ordinary alerts.
        try:
            kwargs['max_seconds'] = min(1.25, cfg.max_seconds)
            return self.camera_capture(target, **kwargs)
        except Exception:
            return None

    def _shutdown_fast_metadata(self, event: str, timeline: dict, photo_exists: bool) -> dict:
        """Build a bounded pre-poweroff alert without slow discovery.

        The normal metadata factory can scan nearby Wi-Fi and other interfaces,
        which is useful during ordinary alerts but too expensive while systemd
        is counting down a shutdown delay inhibitor. This snapshot intentionally
        asks only for the current SSID with a sub-second budget.
        """
        wifi = None
        try:
            wifi = active_ssid(timeout=0.75)
        except Exception:
            wifi = None
        return {
            'event': event,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'hostname': hostname(),
            **timeline,
            'wifi_ssid': wifi,
            'evidence': {
                'prior_attempt_photo': False,
                'photo': bool(photo_exists),
                'screenshot': False,
            },
            'shutdown_fast_delivery': True,
        }

    def _shutdown_payload(self, metadata: dict) -> dict:
        subject, body = format_alert(metadata)
        return {'subject': subject, 'body': body, 'metadata': metadata}

    def _handle_shutdown_security_event(self, event: str) -> EventResult:
        """Persist protected-shutdown evidence and send the fast ntfy alert.

        Only lock-screen and login-screen power-off events reach this path. In
        push mode, the encrypted Gmail queue is intentionally retained even
        after ntfy succeeds so the same evidence can be mailed after the next
        boot/network recovery.
        """
        if event not in {'lockscreen_shutdown', 'login_screen_shutdown'}:
            raise ValueError(f'unsupported shutdown security event: {event}')
        timeline = self.timeline.next()
        self._record_event(event, timeline)
        if not self.rate_limiter.allow(event):
            return EventResult(event, 'rate-limited', False, False)

        try:
            push_mode = bool(self.push_enabled())
        except Exception:
            push_mode = False

        # Location can be comparatively slow. Start it in parallel with camera
        # capture so ntfy can include a fix without imposing a fixed shutdown
        # delay. We wait only a short bounded interval after the photo is ready.
        location_done = None
        location_result: dict[str, object] = {}
        if push_mode and self.settings.location.enabled:
            location_done = threading.Event()

            def location_worker() -> None:
                try:
                    sample = self.location_collect(
                        allow_ip=self.settings.location.allow_ip_fallback,
                        cache_path=self.state_dir / 'wifi-location-cache.json',
                        browser_max_vpn_accuracy_m=self.settings.location.browser_max_vpn_accuracy_m,
                        browser_enabled=self.settings.location.browser_geolocation_enabled,
                    )
                    if sample is not None:
                        location_result['sample'] = sample.normalized()
                except Exception:
                    pass
                finally:
                    location_done.set()

            threading.Thread(
                target=location_worker,
                name='laptopguard-shutdown-location',
                daemon=True,
            ).start()

        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        event_dir = self.evidence_dir / f'{stamp}-{event}'
        event_dir.mkdir(parents=True, exist_ok=True)
        event_dir.chmod(0o700)

        photo = event_dir / 'photo.jpg'
        photo_result = self._shutdown_fast_photo(photo)
        minimal = self._shutdown_fast_metadata(event, timeline, photo.is_file())
        attachments = [photo] if photo.is_file() else []
        queued_item = self.queue.enqueue(self._shutdown_payload(minimal), attachments)

        delivery = 'queued'
        location = None
        location_from_history = False

        if push_mode:
            if location_done is not None:
                location_done.wait(1.25)
                location = location_result.get('sample')
            if location is None:
                location = self._recent_shutdown_location()
                location_from_history = location is not None
            if location is not None:
                minimal['location'] = asdict(location)
                if not location_from_history:
                    try:
                        append_history(self.state_dir / 'location-history.jsonl', location)
                    except Exception:
                        pass
                try:
                    self.queue.update(queued_item, self._shutdown_payload(minimal), attachments)
                except Exception:
                    pass

            try:
                topic = read_topic(self.settings.push.topic_file)
                self.push_send(
                    topic,
                    event=event,
                    timestamp=str(minimal.get('timestamp', '')),
                    hostname=str(minimal.get('hostname', '')),
                    photo_captured=photo.is_file(),
                    location_captured=location is not None,
                    photo_path=photo if photo.is_file() else None,
                    location=asdict(location) if location is not None else None,
                    timeout=2.0,
                )
                delivery = 'pushed'
            except Exception:
                delivery = 'queued'
        elif self.settings.mail.enabled:
            # Preserve the proven pre-v0.1.22 behavior when ntfy is not enabled:
            # one bounded SMTP attempt, then keep the durable queue on failure.
            subject, body = format_alert(minimal)
            try:
                self.shutdown_mail_send(self.settings.mail, subject, body, attachments)
                self.queue.remove(queued_item)
                delivery = 'sent'
            except Exception:
                delivery = 'queued'

        if delivery == 'sent':
            shutil.rmtree(event_dir, ignore_errors=True)
            return EventResult(event, delivery, photo_result is not None, False)

        # Push mode always keeps the Gmail queue. Capture the screenshot only
        # after the immediate ntfy attempt, then durably replace the queue item
        # with the richer evidence bundle. If shutdown cuts us off later, the
        # already-fsynced photo/location queue item still survives.
        screenshot = None
        try:
            screenshot = self.screenshot_capture(event_dir / 'screenshot.png')
        except Exception:
            screenshot = None
        attachments = [
            p for p in (photo if photo.is_file() else None, screenshot)
            if p is not None and Path(p).is_file()
        ]

        # The parallel location probe may finish while ntfy/screenshot are being
        # processed. It can still enrich the queued Gmail evidence even if it was
        # not ready soon enough for the first push.
        if push_mode and location is None and location_done is not None and location_done.is_set():
            location = location_result.get('sample')
            if location is not None and not str(getattr(location, 'source', '')).startswith('last-known:'):
                try:
                    append_history(self.state_dir / 'location-history.jsonl', location)
                except Exception:
                    pass

        core_metadata = dict(minimal)
        core_metadata.update(timeline)
        core_metadata['event'] = event
        core_metadata['evidence'] = {
            'prior_attempt_photo': False,
            'photo': photo.is_file(),
            'screenshot': screenshot is not None and Path(screenshot).is_file(),
        }
        core_metadata['shutdown_fast_delivery'] = False
        if location is not None:
            core_metadata['location'] = asdict(location)
        if photo_result is not None:
            try:
                core_metadata['photo_quality'] = asdict(photo_result.metrics)
                core_metadata['photo_frames_seen'] = photo_result.frames_seen
            except Exception:
                pass

        # Save the core queue state before any slower metadata discovery.
        try:
            self.queue.update(queued_item, self._shutdown_payload(core_metadata), attachments)
        except Exception:
            pass

        try:
            metadata = self.metadata_factory(event)
        except Exception:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.update(timeline)
        metadata['event'] = event
        metadata.setdefault('timestamp', minimal['timestamp'])
        metadata.setdefault('hostname', minimal['hostname'])
        metadata.setdefault('wifi_ssid', minimal.get('wifi_ssid'))
        metadata['evidence'] = dict(core_metadata['evidence'])
        metadata['shutdown_fast_delivery'] = False
        if location is not None:
            metadata['location'] = asdict(location)
        if photo_result is not None:
            try:
                metadata['photo_quality'] = asdict(photo_result.metrics)
                metadata['photo_frames_seen'] = photo_result.frames_seen
            except Exception:
                pass

        # Legacy no-push path collects location only after the failed fast SMTP
        # attempt, preserving the behavior and timing of v0.1.21.
        if not push_mode and self.settings.location.enabled:
            try:
                location = self.location_collect(
                    allow_ip=self.settings.location.allow_ip_fallback,
                    cache_path=self.state_dir / 'wifi-location-cache.json',
                    browser_max_vpn_accuracy_m=self.settings.location.browser_max_vpn_accuracy_m,
                    browser_enabled=self.settings.location.browser_geolocation_enabled,
                )
            except Exception:
                location = None
            if location is not None:
                location = location.normalized()
                metadata['location'] = asdict(location)
                try:
                    append_history(self.state_dir / 'location-history.jsonl', location)
                except Exception:
                    pass

        # One final non-blocking check can recover a location that completed
        # during metadata collection for the queued Gmail message.
        if push_mode and location is None and location_done is not None and location_done.is_set():
            location = location_result.get('sample')
            if location is not None:
                metadata['location'] = asdict(location)
                if not str(getattr(location, 'source', '')).startswith('last-known:'):
                    try:
                        append_history(self.state_dir / 'location-history.jsonl', location)
                    except Exception:
                        pass

        try:
            metadata = write_metadata(event_dir / 'metadata.json', metadata, attachments)
        except Exception:
            pass
        try:
            self.queue.update(queued_item, self._shutdown_payload(metadata), attachments)
        except Exception:
            pass

        shutil.rmtree(event_dir, ignore_errors=True)
        return EventResult(event, delivery, photo_result is not None, location is not None)

    def handle_event(self, event: str) -> EventResult:
        if event in {'shutdown', 'reboot_shutdown'}:
            # v0.1.22 briefly used these names for ordinary shutdown/restart.
            # Keep them inert so stale/manual invocations cannot trigger capture.
            return EventResult(event, 'ignored-lifecycle', False, False)
        if event in {'lockscreen_shutdown', 'login_screen_shutdown'}:
            return self._handle_shutdown_security_event(event)
        timeline = self.timeline.next()
        self._record_event(event, timeline)

        # Ordinary boot/resume are lifecycle events, not theft indicators.
        # They may restore readiness and retry already-queued evidence, but they
        # must never activate the camera, screenshot, location, or email capture
        # path merely because the owner started or woke the laptop.
        if event in {'boot', 'resume'}:
            if event == 'resume':
                try:
                    self.readiness_waiter()
                except Exception:
                    pass
            try:
                self.flush_queue()
            except Exception:
                pass
            return EventResult(event, 'readiness-only', False, False)

        if event == 'failed_auth':
            attempt = self.failed_auth_tracker.register()
            # v0.1.20 policy: attempts 1 and 2 are counter-only. Camera,
            # screenshot, location and mail all start only on attempt 3.
            self.pending_auth_photo.unlink(missing_ok=True)
            if not attempt.trigger:
                delivery = 'ignored-first-attempt' if attempt.count == 1 else 'ignored-second-attempt'
                return EventResult(event, delivery, False, False)
            if not self.rate_limiter.allow('failed_auth_alert'):
                return EventResult(event, 'rate-limited', False, False)
        elif not self.rate_limiter.allow(event):
            return EventResult(event, 'rate-limited', False, False)

        if (
            event in {'failed_auth', 'tamper'}
            and self.settings.location.enabled
            and self.settings.location.auto_tracking_after_alert
        ):
            self.activate_tracking()

        try:
            free = shutil.disk_usage(self.state_dir).free
            if free < 20 * 1024 * 1024:
                self.reserve.release()
                self.queue.prune_oldest(max(0, len(self.queue.items()) - 10))
        except OSError:
            pass

        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        event_dir = self.evidence_dir / f'{stamp}-{event}'
        event_dir.mkdir(parents=True, exist_ok=True)
        event_dir.chmod(0o700)

        photo = event_dir / 'photo.jpg'
        photo_result = self._capture_photo(photo)
        screenshot = self.screenshot_capture(event_dir / 'screenshot.png')

        metadata = self.metadata_factory(event)
        metadata.update(timeline)
        if event == 'failed_auth':
            metadata['failed_auth_attempts'] = self.settings.failed_auth_threshold
        location = None
        if self.settings.location.enabled:
            try:
                location = self.location_collect(allow_ip=self.settings.location.allow_ip_fallback, cache_path=self.state_dir / 'wifi-location-cache.json', browser_max_vpn_accuracy_m=self.settings.location.browser_max_vpn_accuracy_m, browser_enabled=self.settings.location.browser_geolocation_enabled)
            except Exception:
                location = None
        if location is not None:
            location = location.normalized()
            metadata['location'] = asdict(location)
            append_history(self.state_dir / 'location-history.jsonl', location)
        if photo_result is not None:
            metadata['photo_quality'] = asdict(photo_result.metrics)
            metadata['photo_frames_seen'] = photo_result.frames_seen

        attachments = [p for p in (photo if photo.is_file() else None, screenshot) if p is not None and Path(p).is_file()]
        metadata['evidence'] = {
            'prior_attempt_photo': False,
            'photo': photo.is_file(),
            'screenshot': screenshot is not None and Path(screenshot).is_file(),
        }
        metadata_path = event_dir / 'metadata.json'
        metadata = write_metadata(metadata_path, metadata, attachments)
        subject, body = format_alert(metadata)
        payload = {'subject': subject, 'body': body, 'metadata': metadata}

        delivery = 'queued'
        if self.settings.mail.enabled:
            try:
                self.mail_send(self.settings.mail, subject, body, attachments)
                delivery = 'sent'
            except Exception:
                self.queue.enqueue(payload, attachments)
        else:
            self.queue.enqueue(payload, attachments)

        if event == 'failed_auth':
            self.pending_auth_photo.unlink(missing_ok=True)
        shutil.rmtree(event_dir, ignore_errors=True)
        return EventResult(event, delivery, photo_result is not None, location is not None)

    def send_location_update(self) -> bool:
        if not self.settings.location.enabled or not self.tracking_active():
            return False
        try:
            location = self.location_collect(allow_ip=self.settings.location.allow_ip_fallback, cache_path=self.state_dir / 'wifi-location-cache.json', browser_max_vpn_accuracy_m=self.settings.location.browser_max_vpn_accuracy_m, browser_enabled=self.settings.location.browser_geolocation_enabled)
        except Exception:
            location = None
        if location is None:
            return False
        location = location.normalized()
        append_history(self.state_dir / 'location-history.jsonl', location)
        timeline = self.timeline.next()
        metadata = self.metadata_factory('location_update')
        metadata.update(timeline)
        metadata['location'] = asdict(location)
        subject, body = format_alert(metadata)
        payload = {'subject': subject, 'body': body}
        if self.settings.mail.enabled:
            try:
                self.mail_send(self.settings.mail, subject, body, [])
                return True
            except Exception:
                pass
        self.queue.enqueue(payload, [])
        return True

    def flush_queue(self) -> int:
        if not self.settings.mail.enabled:
            return 0
        sent_count = 0
        reconnect_location = None
        reconnect_location_checked = False
        for item in self.queue.readable_items():
            try:
                payload, files = self.queue.read(item)
            except Exception:
                self.queue.quarantine(item)
                continue

            metadata = payload.get('metadata')
            if (
                self.settings.location.enabled
                and isinstance(metadata, dict)
                and not metadata.get('location')
            ):
                if not reconnect_location_checked:
                    reconnect_location_checked = True
                    try:
                        reconnect_location = self.location_collect(
                            allow_ip=self.settings.location.allow_ip_fallback,
                            cache_path=self.state_dir / 'wifi-location-cache.json',
                            browser_max_vpn_accuracy_m=self.settings.location.browser_max_vpn_accuracy_m,
                            browser_enabled=self.settings.location.browser_geolocation_enabled,
                        )
                    except Exception:
                        reconnect_location = None
                    if reconnect_location is not None:
                        reconnect_location = reconnect_location.normalized()
                        append_history(self.state_dir / 'location-history.jsonl', reconnect_location)
                if reconnect_location is not None:
                    enriched_metadata = dict(metadata)
                    enriched_metadata['location'] = asdict(reconnect_location)
                    enriched_metadata['location_recovered_after_queue'] = True
                    payload = dict(payload)
                    payload['metadata'] = enriched_metadata
                    payload['subject'], payload['body'] = format_alert(enriched_metadata)

            try:
                with tempfile.TemporaryDirectory(prefix='laptopguard-') as temp:
                    attachments = []
                    root = Path(temp)
                    for name, content in files.items():
                        safe_name = Path(name).name
                        target = root / safe_name
                        target.write_bytes(content)
                        attachments.append(target)
                    self.mail_send(self.settings.mail, payload['subject'], payload['body'], attachments)
                self.queue.remove(item)
                sent_count += 1
            except Exception:
                break
        return sent_count
