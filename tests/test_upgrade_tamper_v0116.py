from pathlib import Path

import laptopguard.daemon as daemon
from laptopguard.tamper import TamperBaseline


def test_trusted_upgrade_refreshes_only_managed_paths(tmp_path: Path):
    os_file = tmp_path / 'shadow'
    managed_file = tmp_path / 'laptopguard.service'
    os_file.write_text('os-before', encoding='utf-8')
    managed_file.write_text('managed-before', encoding='utf-8')

    baseline = TamperBaseline(tmp_path / 'baseline.json', [os_file, managed_file])
    assert baseline.check() == []

    # Simulate an unrelated security-sensitive file changing before/during the
    # trusted LaptopGuard upgrade, while the installer legitimately replaces
    # its own managed service file.
    os_file.write_text('os-after', encoding='utf-8')
    managed_file.write_text('managed-after', encoding='utf-8')

    baseline.trust_current([managed_file])
    changes = baseline.check()

    assert [change.path for change in changes] == [str(os_file)]


def test_trusted_file_is_still_monitored_after_upgrade_refresh(tmp_path: Path):
    managed_file = tmp_path / 'config.toml'
    managed_file.write_text('v1', encoding='utf-8')
    baseline = TamperBaseline(tmp_path / 'baseline.json', [managed_file])
    assert baseline.check() == []

    managed_file.write_text('trusted-v2', encoding='utf-8')
    baseline.trust_current([managed_file])
    assert baseline.check() == []

    managed_file.write_text('unauthorized-v3', encoding='utf-8')
    changes = baseline.check()
    assert [change.path for change in changes] == [str(managed_file)]


def test_daemon_skips_tamper_check_during_maintenance_but_checks_after(tmp_path: Path):
    target = tmp_path / 'config.toml'
    target.write_text('before', encoding='utf-8')
    baseline = TamperBaseline(tmp_path / 'baseline.json', [target])
    assert baseline.check() == []

    target.write_text('changed', encoding='utf-8')
    maintenance = tmp_path / 'maintenance'
    maintenance.touch()

    assert daemon._tamper_changes(baseline, maintenance) == []

    maintenance.unlink()
    changes = daemon._tamper_changes(baseline, maintenance)
    assert [change.path for change in changes] == [str(target)]


def test_installer_refreshes_trusted_tamper_baseline_before_service_restart():
    install = Path('install.sh').read_text(encoding='utf-8')

    refresh = "baseline.trust_current(TRUSTED_INSTALL_PATHS)"
    assert refresh in install
    assert "from laptopguard.tamper import (" in install

    refresh_index = install.index(refresh)
    daemon_reload_index = install.rindex('systemctl daemon-reload')
    service_start_index = install.index('systemctl enable --now laptopguard.service')

    assert refresh_index < daemon_reload_index < service_start_index


def test_every_trusted_install_path_is_monitored():
    from laptopguard.tamper import CRITICAL_PATHS, TRUSTED_INSTALL_PATHS

    monitored = {str(path) for path in CRITICAL_PATHS}
    assert {str(path) for path in TRUSTED_INSTALL_PATHS} <= monitored
