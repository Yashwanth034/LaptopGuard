from __future__ import annotations


def format_alert(metadata: dict) -> tuple[str, str]:
    event = str(metadata.get('event', 'security_event'))
    timestamp = str(metadata.get('timestamp', 'unknown time'))
    host = str(metadata.get('hostname', 'unknown host'))
    lines = [
        'LaptopGuard security alert',
        f'Time: {timestamp}',
        f'Device: {host}',
    ]
    if metadata.get('wifi_ssid'):
        lines.append(f"Wi-Fi: {metadata['wifi_ssid']}")
    location = metadata.get('location') or {}
    lat = location.get('latitude')
    lon = location.get('longitude')
    if lat is not None and lon is not None:
        lines.append(f'Location: https://maps.google.com/?q={lat},{lon}')
        if location.get('accuracy_m') is not None:
            lines.append(f'Accuracy: ±{location["accuracy_m"]:.0f} m')
    else:
        lines.append('Location: unavailable')
    evidence = metadata.get('evidence') or {}
    if (evidence.get('prior_attempt_photo') or evidence.get('first_attempt_photo')) and evidence.get('photo'):
        lines.append('Photos: 2 attached')
    elif evidence.get('photo'):
        lines.append('Photo: attached')
    if evidence.get('screenshot'):
        lines.append('Screenshot: attached')
    return f'[LaptopGuard] {event} on {host}', '\n'.join(lines)
