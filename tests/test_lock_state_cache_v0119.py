from laptopguard.session import ActiveSession
from laptopguard.shutdown_guard import (
    LockStateTracker,
    cached_or_probe_lock_state,
    parse_user_lock_watch_line,
    user_lock_watch_command,
)


def test_cached_locked_state_wins_when_shutdown_time_probe_is_false():
    tracker = LockStateTracker()
    tracker.update(True, 'cinnamon-active-changed')

    calls = []
    result = cached_or_probe_lock_state(tracker, lambda: calls.append('probe') or False)

    assert result is True
    assert calls == []


def test_cached_unlocked_state_prevents_false_alert_without_reprobe():
    tracker = LockStateTracker()
    tracker.update(False, 'cinnamon-active-changed')

    calls = []
    result = cached_or_probe_lock_state(tracker, lambda: calls.append('probe') or True)

    assert result is False
    assert calls == []


def test_unknown_cache_falls_back_to_existing_lock_probe():
    tracker = LockStateTracker()
    assert cached_or_probe_lock_state(tracker, lambda: True) is True


def test_tracker_accepts_logind_lock_and_unlock_transitions():
    tracker = LockStateTracker()
    tracker.handle_logind_signal('Lock')
    assert tracker.locked is True
    assert tracker.source == 'logind-lock'

    tracker.handle_logind_signal('Unlock')
    assert tracker.locked is False
    assert tracker.source == 'logind-unlock'


def test_user_lock_watch_line_tracks_cinnamon_active_changed():
    assert parse_user_lock_watch_line('LOCKED 1 cinnamon') == (True, 'cinnamon')
    assert parse_user_lock_watch_line('LOCKED 0 cinnamon') == (False, 'cinnamon')
    assert parse_user_lock_watch_line('noise') is None


def test_user_lock_watch_command_runs_helper_inside_graphical_session():
    session = ActiveSession('c2', 'alice', 1000, 'x11', ':0', '/run/user/1000')
    command = user_lock_watch_command(session, launcher='/usr/local/bin/laptopguard')

    assert command[:4] == ['runuser', '-u', 'alice', '--']
    assert 'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus' in command
    assert command[-2:] == ['/usr/local/bin/laptopguard', 'lock-watch-user']


def test_shutdown_guard_run_uses_pre_shutdown_cached_lock_state(monkeypatch, tmp_path):
    import laptopguard.shutdown_guard as guard

    handled = []

    class FakeEngine:
        def __init__(self, settings):
            pass

        def handle_event(self, name):
            handled.append(name)
            class Result:
                delivery = 'queued'
                photo_captured = True
                location_captured = False
            return Result()

    def fake_start(tracker, stop_event):
        tracker.update(True, 'cinnamon-active-changed')
        return None

    def fake_subscribe(on_signal, tracker):
        assert tracker.locked is True
        on_signal(True, {'type': 'poweroff'})

    monkeypatch.setattr(guard, 'SecurityEngine', FakeEngine)
    monkeypatch.setattr(guard, '_start_user_lock_state_watcher', fake_start, raising=False)
    monkeypatch.setattr(guard, '_subscribe_and_wait', fake_subscribe)

    guard.run(_settings_for_guard_test(tmp_path), lock_checker=lambda: False)
    assert handled == ['lockscreen_shutdown']


def _settings_for_guard_test(tmp_path):
    from laptopguard.config import Settings
    return Settings(
        state_dir=str(tmp_path / 'state'),
        evidence_dir=str(tmp_path / 'evidence'),
        queue_dir=str(tmp_path / 'queue'),
    )
