from laptopguard.monitor import suspicious_from_line


def test_monitor_only_emits_suspicious_auth_lines():
    assert suspicious_from_line('pam_unix(login:auth): authentication failure') == 'failed_auth'
    assert suspicious_from_line('session opened for user alice') is None
