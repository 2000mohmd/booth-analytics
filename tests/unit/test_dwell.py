import pytest

from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap

ZONES = {
    "aisle": [[0, 0], [100, 0], [100, 20], [0, 20]],
    "stand": [[0, 20], [100, 20], [100, 80], [0, 80]],
}
ZONE_MAP = ZoneMap(ZONES)
CAM = "cam_overhead_1"


def _tracker(threshold=5.0):
    return VisitTracker(booth_id="booth-01", stopper_threshold_s=threshold)


def _update(vt, track_id, x, y, ts, is_staff=False):
    zone = ZONE_MAP.zone_for_point(x, y)
    vt.update(track_id, CAM, zone, x, y, ts, is_staff=is_staff)


def test_passerby_through_aisle_is_not_a_stopper():
    vt = _tracker()
    t0 = 1000.0
    _update(vt, "1", 10, 10, t0)
    _update(vt, "1", 50, 10, t0 + 1)
    _update(vt, "1", 90, 10, t0 + 2)
    visit = vt.finalize("1", t0 + 2)
    assert visit["is_stopper"] is False
    assert visit["dwell_seconds"] == 0.0


def test_dwell_in_stand_zone_marks_stopper():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    _update(vt, "1", 50, 10, t0)          # aisle
    _update(vt, "1", 50, 50, t0 + 1)      # enters stand
    _update(vt, "1", 50, 50, t0 + 8)      # still in stand, 7s later
    visit = vt.finalize("1", t0 + 8)
    assert visit["is_stopper"] is True
    assert visit["dwell_seconds"] == 7.0
    assert visit["zone_path"] == "aisle→stand"


def test_below_threshold_dwell_is_not_a_stopper():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)
    _update(vt, "1", 50, 50, t0 + 2)
    visit = vt.finalize("1", t0 + 2)
    assert visit["is_stopper"] is False


def test_staff_flag_persists_once_set():
    vt = _tracker()
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0, is_staff=False)
    _update(vt, "1", 50, 50, t0 + 1, is_staff=True)
    visit = vt.finalize("1", t0 + 1)
    assert visit["is_staff"] is True


def test_expire_stale_finalizes_missing_tracks():
    vt = _tracker()
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)
    finalized = vt.expire_stale(now=t0 + 10, grace_seconds=2.0)
    assert len(finalized) == 1
    assert vt.active_count() == 0


def test_active_and_staff_counts():
    vt = _tracker()
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0, is_staff=False)
    _update(vt, "2", 50, 50, t0, is_staff=True)
    assert vt.active_count(exclude_staff=True) == 1
    assert vt.staff_count() == 1


def test_active_stopper_visit_ids_reflects_live_dwell():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)          # enters stand at t0
    assert vt.active_stopper_visit_ids(now=t0 + 2) == []       # not dwelling long enough yet
    assert len(vt.active_stopper_visit_ids(now=t0 + 6)) == 1   # now over threshold, still tracked


def test_active_stopper_visit_ids_excludes_staff_and_aisle():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    _update(vt, "1", 50, 10, t0)                    # aisle the whole time
    _update(vt, "2", 50, 50, t0, is_staff=True)      # stand, but staff
    assert vt.active_stopper_visit_ids(now=t0 + 10) == []


def test_track_ids_must_be_namespaced_per_camera_by_caller():
    """Two different cameras' ByteTrack streams both number their first track '1' - callers
    MUST namespace (e.g. f"{camera_id}:1") or they collide into one track in here."""
    vt = _tracker()
    t0 = 1000.0
    vt.update("cam_a:1", "cam_a", "stand", 50, 50, t0)
    vt.update("cam_b:1", "cam_b", "stand", 50, 50, t0)
    assert vt.active_count() == 2


def test_position_trace_is_prefixed_with_its_camera():
    vt = _tracker()
    t0 = 1000.0
    for i in range(6):  # POSITION_TRACE_STRIDE is 5, so this records at least one point
        _update(vt, "1", 50, 50, t0 + i)
    visit = vt.finalize("1", t0 + 6)
    assert visit["position_trace"].startswith(f"{CAM}|")


def test_finalize_unknown_track_raises_keyerror():
    """finalize() pops with no default - calling it twice for the same track_id (e.g. a bug
    that double-finalizes) must fail loudly rather than silently returning a bogus visit."""
    vt = _tracker()
    with pytest.raises(KeyError):
        vt.finalize("never-seen", 1000.0)


def test_zero_threshold_is_immediately_a_stopper():
    vt = _tracker(threshold=0.0)
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)  # enters stand
    visit = vt.finalize("1", t0)  # 0s elapsed
    assert visit["is_stopper"] is True


def test_dwell_at_exact_threshold_boundary_counts_as_stopper():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)
    visit = vt.finalize("1", t0 + 5.0)  # exactly the threshold, not over it
    assert visit["dwell_seconds"] == 5.0
    assert visit["is_stopper"] is True


def test_dwell_accumulates_across_separate_visits_to_same_zone():
    """A track that leaves the stand for the aisle and comes back must have its two stand
    stints summed, not overwritten by the second one."""
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)          # enters stand
    _update(vt, "1", 50, 10, t0 + 3)      # back to aisle: stand stint #1 = 3s
    _update(vt, "1", 50, 50, t0 + 4)      # re-enters stand
    visit = vt.finalize("1", t0 + 9)      # stand stint #2 = 5s
    assert visit["dwell_seconds"] == 8.0
    assert visit["zone_path"] == "stand→aisle→stand"
    assert visit["is_stopper"] is True


def test_track_never_in_any_zone_has_empty_path_and_zero_dwell():
    vt = _tracker()
    t0 = 1000.0
    _update(vt, "1", 500, 500, t0)        # outside every zone -> zone is None
    _update(vt, "1", 500, 500, t0 + 10)
    visit = vt.finalize("1", t0 + 10)
    assert visit["zone_path"] == ""
    assert visit["dwell_seconds"] == 0.0
    assert visit["is_stopper"] is False


def test_expire_stale_with_negative_grace_flushes_everything():
    """services/ingestion/pipeline.py calls expire_stale(now, grace_seconds=-1) on shutdown to
    flush every still-active track, however recently it was last seen."""
    vt = _tracker()
    t0 = 1000.0
    _update(vt, "1", 50, 50, t0)
    _update(vt, "2", 50, 50, t0)
    finalized = vt.expire_stale(now=t0, grace_seconds=-1)
    assert len(finalized) == 2
    assert vt.active_count() == 0
