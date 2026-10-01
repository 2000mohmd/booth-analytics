from services.kiosk_display.render.effects import PULSE_DURATION_S, TRAIL_WINDOW_S, TrailTracker


def _track(track_id="t1", x1=10, y1=10, x2=20, y2=20):
    return {"track_id": track_id, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "zone": "stand"}


def test_new_track_has_full_pulse():
    tracker = TrailTracker()
    tracker.update([_track()], now=100.0)
    assert tracker.pulse_alpha("t1", now=100.0) == 1.0


def test_pulse_fades_out_after_duration():
    tracker = TrailTracker()
    tracker.update([_track()], now=100.0)
    assert tracker.pulse_alpha("t1", now=100.0 + PULSE_DURATION_S * 2) == 0.0


def test_trail_accumulates_points_across_updates():
    tracker = TrailTracker()
    tracker.update([_track(x1=0, x2=10)], now=100.0)
    tracker.update([_track(x1=10, x2=20)], now=100.1)
    trail = tracker.trail("t1", now=100.1)
    assert len(trail) == 2


def test_trail_points_age_out_of_window():
    tracker = TrailTracker()
    tracker.update([_track()], now=100.0)
    tracker.update([_track()], now=100.0 + TRAIL_WINDOW_S + 1)
    trail = tracker.trail("t1", now=100.0 + TRAIL_WINDOW_S + 1)
    # only the most recent point should survive - the first is older than TRAIL_WINDOW_S
    assert len(trail) == 1


def test_vanished_track_is_dropped_after_window():
    tracker = TrailTracker()
    tracker.update([_track()], now=100.0)
    tracker.update([], now=100.0 + TRAIL_WINDOW_S + 1)
    assert "t1" not in tracker.active_track_ids()


def test_unknown_track_id_returns_empty_trail_and_no_pulse():
    tracker = TrailTracker()
    assert tracker.trail("nope") == []
    assert tracker.pulse_alpha("nope") == 0.0
