from pathlib import Path
import json

import pytest

from laptopguard.events import classify_auth_event
from laptopguard.location import LocationSample, collect_location, parse_beacondb_response
from laptopguard.network import NetworkSnapshot, VpnState, classify_interface
from laptopguard.queue_store import EncryptedQueue
from laptopguard.session import ActiveSession, parse_loginctl_sessions
from laptopguard.timeline import EventTimeline
from laptopguard.validation import valid_email


def test_sudo_and_ssh_failures_are_not_physical_failed_auth():
    assert classify_auth_event('sudo: pam_unix(sudo:auth): authentication failure').suspicious is False
    assert classify_auth_event('sshd[22]: Failed password for user from 1.2.3.4').suspicious is False
    assert classify_auth_event('cinnamon-screensaver-pam-helper: pam_unix(cinnamon-screensaver:auth): authentication failure').kind == 'failed_auth'
    assert classify_auth_event('lightdm: pam_unix(lightdm:auth): authentication failure').kind == 'failed_auth'


def test_interface_classification_separates_vpn_virtual_and_physical():
    assert classify_interface('wg0') == 'vpn'
    assert classify_interface('tailscale0') == 'vpn'
    assert classify_interface('docker0') == 'virtual'
    assert classify_interface('vethabc') == 'virtual'
    assert classify_interface('wlp2s0') == 'physical'


def test_vpn_disables_ip_location_fallback():
    called = []
    vpn = VpnState(True, ('wg0',), ('wireguard',))
    sample = collect_location(
        allow_ip=True,
        vpn_state=vpn,
        gps_provider=lambda: None,
        wifi_provider=lambda: None,
        geoclue_provider=lambda: None,
        ip_provider=lambda: called.append('ip') or LocationSample(1, 2, 'ip'),
    )
    assert sample is None
    assert called == []


def test_high_confidence_source_wins_before_ip():
    called = []
    sample = collect_location(
        allow_ip=True,
        vpn_state=VpnState(False, (), ()),
        gps_provider=lambda: LocationSample(17.3, 78.4, 'modem-gps', 8),
        wifi_provider=lambda: called.append('wifi') or None,
        geoclue_provider=lambda: called.append('geoclue') or None,
        ip_provider=lambda: called.append('ip') or None,
    )
    assert sample is not None
    assert sample.source == 'modem-gps'
    assert called == []


def test_beacondb_ip_fallback_is_rejected():
    assert parse_beacondb_response({'location': {'lat': 1, 'lng': 2}, 'accuracy': 25000, 'fallback': 'ipf'}) is None
    sample = parse_beacondb_response({'location': {'lat': 17.3, 'lng': 78.4}, 'accuracy': 42})
    assert sample is not None
    assert sample.source == 'wifi-beacondb'
    assert sample.accuracy_m == 42


def test_session_parser_prefers_active_local_graphical_session():
    rows = [
        {'id': '2', 'user': 'alice', 'uid': 1000, 'active': False, 'remote': False, 'type': 'x11', 'display': ':0'},
        {'id': '3', 'user': 'bob', 'uid': 1001, 'active': True, 'remote': False, 'type': 'wayland', 'display': ''},
    ]
    session = parse_loginctl_sessions(rows)
    assert session == ActiveSession('3', 'bob', 1001, 'wayland', '', '/run/user/1001')


def test_queue_quarantines_corrupt_item_and_keeps_good_item(tmp_path: Path):
    queue = EncryptedQueue(tmp_path / 'queue', tmp_path / 'key')
    good = queue.enqueue({'subject': 'ok', 'body': 'ok'}, [])
    bad = queue.directory / '000-corrupt.lgq'
    bad.write_bytes(b'broken')
    items = queue.readable_items()
    assert items == [good]
    assert not bad.exists()
    assert any(queue.corrupt_dir.glob('000-corrupt*.lgq'))


def test_queue_atomic_write_leaves_no_tmp_files(tmp_path: Path):
    queue = EncryptedQueue(tmp_path / 'queue', tmp_path / 'key')
    queue.enqueue({'subject': 'x', 'body': 'y'}, [])
    assert list(queue.directory.glob('*.tmp')) == []


def test_timeline_sequence_persists_and_includes_boot_and_monotonic(tmp_path: Path):
    clock = EventTimeline(tmp_path, boot_id_provider=lambda: 'boot-123', monotonic_ns=lambda: 99)
    a = clock.next()
    b = clock.next()
    assert a['sequence'] == 1
    assert b['sequence'] == 2
    assert b['boot_id'] == 'boot-123'
    assert b['monotonic_ns'] == 99


def test_email_validation_rejects_app_password_in_recipient_field():
    assert valid_email('owner@example.com')
    assert not valid_email('abcd efgh ijkl mnop')
    assert not valid_email('abc')


def test_session_parser_accepts_graphical_environment_when_loginctl_type_is_tty():
    rows = [{
        'id': '2', 'user': 'alice', 'uid': 1000, 'active': True, 'remote': False,
        'type': 'tty', 'display': ':0', 'xauthority': '', 'wayland_display': ''
    }]
    session = parse_loginctl_sessions(rows)
    assert session is not None
    assert session.session_type == 'x11'
    assert session.display == ':0'
