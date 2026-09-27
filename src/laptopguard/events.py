from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityEvent:
    kind: str
    suspicious: bool
    raw: str


_LOCAL_AUTH_MARKERS = (
    'lightdm',
    'gdm-password',
    'sddm',
    'cinnamon-screensaver',
    'mate-screensaver',
    'kscreenlocker',
    'pam_unix(login:auth)',
)
_REMOTE_OR_PRIVILEGE_MARKERS = ('sudo', 'sshd', 'polkit', 'pkexec', 'pam_unix(su:', 'cockpit')
_FAILURE_MARKERS = ('authentication failure', 'failed password', 'authentication error', 'pam_authenticate failed')


def classify_auth_event(line: str) -> SecurityEvent:
    text = line.lower()
    if any(token in text for token in _REMOTE_OR_PRIVILEGE_MARKERS):
        return SecurityEvent('other', False, line)
    failed = any(token in text for token in _FAILURE_MARKERS)
    local = any(token in text for token in _LOCAL_AUTH_MARKERS)
    if failed and local:
        return SecurityEvent('failed_auth', True, line)
    if 'systemd-logind' in text and ('lid opened' in text or 'resumed' in text):
        return SecurityEvent('resume', False, line)
    return SecurityEvent('other', False, line)
