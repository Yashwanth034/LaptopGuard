from pathlib import Path
from laptopguard.config import load_config


def test_load_config_reads_password_file(tmp_path: Path):
    password = tmp_path / 'smtp.secret'
    password.write_text('app-pass\n')
    cfg = tmp_path / 'config.toml'
    cfg.write_text(f'''[mail]\nenabled=true\nhost="smtp.example.com"\nport=465\nusername="me@example.com"\nfrom_address="me@example.com"\nto_address="alerts@example.com"\npassword_file="{password}"\n''')
    settings = load_config(cfg)
    assert settings.mail.password() == 'app-pass'
    assert settings.mail.enabled is True


def test_migrate_failed_auth_policy_updates_existing_threshold(tmp_path: Path):
    from laptopguard.config import migrate_failed_auth_policy

    cfg = tmp_path / 'config.toml'
    cfg.write_text('''state_dir = "/var/lib/laptopguard"\nfailed_auth_threshold = 2\nfailed_auth_window_seconds = 120\n\n[mail]\nenabled = true\n''')

    changed = migrate_failed_auth_policy(cfg, threshold=3)

    assert changed is True
    text = cfg.read_text()
    assert 'failed_auth_threshold = 3' in text
    assert 'failed_auth_threshold = 2' not in text
    assert '[mail]' in text


def test_migrate_failed_auth_policy_adds_missing_threshold(tmp_path: Path):
    from laptopguard.config import migrate_failed_auth_policy

    cfg = tmp_path / 'config.toml'
    cfg.write_text('''state_dir = "/var/lib/laptopguard"\nfailed_auth_window_seconds = 120\n\n[mail]\nenabled = true\n''')

    changed = migrate_failed_auth_policy(cfg, threshold=3)

    assert changed is True
    text = cfg.read_text()
    assert 'failed_auth_threshold = 3' in text.split('[mail]', 1)[0]


def test_migrate_failed_auth_policy_is_idempotent(tmp_path: Path):
    from laptopguard.config import migrate_failed_auth_policy

    cfg = tmp_path / 'config.toml'
    cfg.write_text('failed_auth_threshold = 3\nfailed_auth_window_seconds = 120\n')

    changed = migrate_failed_auth_policy(cfg, threshold=3)

    assert changed is False
    assert cfg.read_text().count('failed_auth_threshold') == 1
