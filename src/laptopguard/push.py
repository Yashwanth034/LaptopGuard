from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib import request as urllib_request

from .platform_support import hostname

_TOPIC_RE = re.compile(r'^[A-Za-z0-9._-]{12,128}$')


def validate_topic(topic: str) -> str:
    value = str(topic or '').strip()
    if value.lower().startswith(('http://', 'https://')):
        raise ValueError('enter topic name only, not a URL')
    if not _TOPIC_RE.fullmatch(value):
        raise ValueError('topic must be 12-128 characters using letters, numbers, dot, underscore, or hyphen')
    return value


NTFY_SERVER = "https://ntfy.sh"


def _notification_message(
    *,
    event: str,
    timestamp: str,
    hostname: str,
    photo_captured: bool,
    location_captured: bool,
    location: dict | None = None,
) -> str:
    lines = [
        f"Event: {event}",
        f"Timestamp: {timestamp}",
        f"Hostname: {hostname}",
        f"Photo evidence: {'yes' if photo_captured else 'no'}",
        f"Location evidence: {'yes' if location_captured else 'no'}",
    ]
    if isinstance(location, dict):
        try:
            latitude = float(location['latitude'])
            longitude = float(location['longitude'])
        except (KeyError, TypeError, ValueError):
            latitude = longitude = None
        if latitude is not None and longitude is not None:
            lat_text = f'{latitude:.6f}'.rstrip('0').rstrip('.')
            lon_text = f'{longitude:.6f}'.rstrip('0').rstrip('.')
            lines.append(f'Location: https://maps.google.com/?q={lat_text},{lon_text}')
            accuracy = location.get('accuracy_m')
            if accuracy is not None:
                try:
                    lines.append(f'Accuracy: ±{float(accuracy):.0f} m')
                except (TypeError, ValueError):
                    pass
            source = str(location.get('source') or '').strip()
            if source:
                lines.append(f'Location source: {source}')
    return '\n'.join(lines)


def send_notification(
    topic: str,
    *,
    event: str,
    timestamp: str,
    hostname: str,
    photo_captured: bool,
    location_captured: bool,
    photo_path: Path | str | None = None,
    location: dict | None = None,
    opener=urllib_request.urlopen,
    timeout: float = 2.0,
) -> None:
    value = validate_topic(topic)
    message = _notification_message(
        event=event,
        timestamp=timestamp,
        hostname=hostname,
        photo_captured=photo_captured,
        location_captured=location_captured,
        location=location,
    )

    headers = {'Title': 'LaptopGuard Security Alert'}
    data = message.encode('utf-8')
    photo = Path(photo_path) if photo_path is not None else None
    if photo is not None and photo.is_file() and photo.stat().st_size > 0:
        # ntfy accepts the request body as an attachment. Keep the human-readable
        # alert in the Message header so the same notification contains both the
        # webcam JPEG and the location details.
        data = photo.read_bytes()
        headers.update({
            'Message': ' | '.join(message.splitlines()),
            'Filename': photo.name,
            'Content-Type': 'image/jpeg',
        })

    req = urllib_request.Request(
        f'{NTFY_SERVER}/{value}',
        data=data,
        headers=headers,
        method='POST',
    )
    with opener(req, timeout=float(timeout)) as response:
        status = int(getattr(response, 'status', 200) or 200)
        if status < 200 or status >= 300:
            raise OSError(f'ntfy returned HTTP {status}')


def _enabled_marker(state_dir: Path | str) -> Path:
    return Path(state_dir) / 'push-enabled'


def _topic_digest(topic: str) -> str:
    return hashlib.sha256(validate_topic(topic).encode('utf-8')).hexdigest()


def mark_enabled(state_dir: Path | str, topic: str) -> None:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    marker = _enabled_marker(state)
    marker.write_text(_topic_digest(topic) + '\n', encoding='utf-8')
    os.chmod(marker, 0o600)


def disable(state_dir: Path | str) -> None:
    _enabled_marker(state_dir).unlink(missing_ok=True)


def read_topic(topic_file: Path | str) -> str:
    path = Path(topic_file)
    if not path.is_file():
        raise ValueError('ntfy topic is not configured')
    return validate_topic(path.read_text(encoding='utf-8').strip())


def is_enabled(state_dir: Path | str, topic_file: Path | str) -> bool:
    marker = _enabled_marker(state_dir)
    if not marker.is_file():
        return False
    try:
        topic = read_topic(topic_file)
        tested_digest = marker.read_text(encoding='utf-8').strip()
    except (OSError, ValueError):
        return False
    return tested_digest == _topic_digest(topic)


def configure_topic(topic_file: Path | str, state_dir: Path | str, topic: str) -> None:
    value = validate_topic(topic)
    target = Path(topic_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.ntfy-topic-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(value + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, target)
        os.chmod(target, 0o600)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    disable(state_dir)


def run_test(settings, sender=send_notification) -> bool:
    topic_file = Path(settings.push.topic_file)
    try:
        topic = read_topic(topic_file)
        sender(
            topic,
            event="push_test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            hostname=hostname(),
            photo_captured=False,
            location_captured=False,
        )
    except Exception:
        disable(settings.state_dir)
        return False
    mark_enabled(settings.state_dir, topic)
    return True
