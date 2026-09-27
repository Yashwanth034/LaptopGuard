from pathlib import Path
from laptopguard.boot_marker import BootMarker


def test_boot_marker_fires_once_per_boot_id(tmp_path: Path):
    marker = BootMarker(tmp_path / 'boot-id')
    assert marker.is_new('abc') is True
    assert marker.is_new('abc') is False
    assert marker.is_new('def') is True
