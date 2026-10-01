"""Cross-camera re-identification via declared zone_transitions (see dwell.py's module
docstring): a visitor who walks from one overhead camera's section into an adjacent one, through
a configured (camera, zone) boundary pair, continues as the *same* visit instead of two.

max_gap_seconds is measured from the track's actual last_seen time, not from whenever
expire_stale() happens to run - so grace_seconds (how long before a missing track is even
considered stale) must leave room inside it for the real walk-between-cameras gap.
"""
from services.metrics_engine.dwell import VisitTracker

TRANSITIONS = [
    (("cam_a", "aisle"), ("cam_b", "aisle"), 3.0),  # max_gap_seconds, from last_seen
]


def test_handoff_within_window_continues_same_visit():
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0, zone_transitions=TRANSITIONS)
    t0 = 1000.0

    for i in range(5):  # >= POSITION_TRACE_STRIDE frames, so cam_a records a trace point
        vt.update("cam_a:1", "cam_a", "aisle", 90, 10, t0 + i * 0.1)
    last_seen = t0 + 0.4
    # visitor leaves cam_a's frame near the boundary; grace period (0.5s) elapses
    finalized = vt.expire_stale(last_seen + 0.5, grace_seconds=0.4)
    assert finalized == []  # held as a pending handoff, not finalized yet
    assert vt.active_count() == 1  # still counted as present in the booth

    # ...and reappears in cam_b's aisle zone 1.5s after last_seen - within the 3s window
    for i in range(5):  # >= POSITION_TRACE_STRIDE frames again, for cam_b's own trace point
        vt.update("cam_b:1", "cam_b", "aisle", 5, 10, last_seen + 1.5 + i * 0.1)
    assert vt.active_count() == 1  # still just one visitor, not two

    visit = vt.finalize("cam_b:1", last_seen + 2)
    assert visit["zone_path"] == "aisle"  # zone_path doesn't duplicate the shared zone name
    # position trace carries both camera segments, in order
    assert visit["position_trace"] == "cam_a|90,10/cam_b|5,10"


def test_handoff_outside_window_is_two_separate_visits():
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0, zone_transitions=TRANSITIONS)
    t0 = 1000.0

    vt.update("cam_a:1", "cam_a", "aisle", 90, 10, t0)
    finalized = vt.expire_stale(t0 + 10, grace_seconds=1.5)  # gap (10s) exceeds max_gap (3s)
    assert len(finalized) == 1  # finalized as its own complete visit, not held

    vt.update("cam_b:1", "cam_b", "aisle", 5, 10, t0 + 10.5)
    visit = vt.finalize("cam_b:1", t0 + 11)
    assert visit["visit_id"] != finalized[0]["visit_id"]  # a genuinely new, separate visit


def test_handoff_through_unconfigured_zone_is_two_separate_visits():
    """No zone_transitions entry for (cam_a, stand) -> cam_c anywhere - should behave exactly
    like the no-re-id v1 baseline."""
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0, zone_transitions=TRANSITIONS)
    t0 = 1000.0

    vt.update("cam_a:1", "cam_a", "stand", 50, 50, t0)
    finalized = vt.expire_stale(t0 + 10, grace_seconds=1.5)
    assert len(finalized) == 1  # not a configured boundary - finalized right away

    vt.update("cam_c:1", "cam_c", "stand", 50, 50, t0 + 10.5)
    visit = vt.finalize("cam_c:1", t0 + 11)
    assert visit["visit_id"] != finalized[0]["visit_id"]


def test_shutdown_flush_finalizes_pending_handoffs_immediately():
    """grace_seconds=-1 (process shutdown) must not leave a visit stuck waiting for a handoff
    that will now never come, since no camera thread is still running to claim it."""
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0, zone_transitions=TRANSITIONS)
    t0 = 1000.0

    vt.update("cam_a:1", "cam_a", "aisle", 90, 10, t0)
    vt.expire_stale(t0 + 0.5, grace_seconds=0.4)  # becomes a pending handoff
    assert vt.active_count() == 1

    finalized = vt.expire_stale(t0 + 0.5, grace_seconds=-1)  # shutdown flush
    assert len(finalized) == 1
    assert vt.active_count() == 0


def test_staff_flag_carries_across_the_handoff():
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0, zone_transitions=TRANSITIONS)
    t0 = 1000.0

    vt.update("cam_a:1", "cam_a", "aisle", 90, 10, t0, is_staff=True)
    vt.expire_stale(t0 + 0.5, grace_seconds=0.4)
    vt.update("cam_b:1", "cam_b", "aisle", 5, 10, t0 + 1.5)

    visit = vt.finalize("cam_b:1", t0 + 2)
    assert visit["is_staff"] is True
