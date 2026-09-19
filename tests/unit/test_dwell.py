from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap

ZONES = {
    "aisle": [[0, 0], [100, 0], [100, 20], [0, 20]],
    "stand": [[0, 20], [100, 20], [100, 80], [0, 80]],
}


def _tracker(threshold=5.0):
    return VisitTracker(booth_id="booth-01", zone_map=ZoneMap(ZONES), stopper_threshold_s=threshold)


def test_passerby_through_aisle_is_not_a_stopper():
    vt = _tracker()
    t0 = 1000.0
    vt.update("1", 10, 10, t0)
    vt.update("1", 50, 10, t0 + 1)
    vt.update("1", 90, 10, t0 + 2)
    visit = vt.finalize("1", t0 + 2)
    assert visit["is_stopper"] is False
    assert visit["dwell_seconds"] == 0.0


def test_dwell_in_stand_zone_marks_stopper():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    vt.update("1", 50, 10, t0)          # aisle
    vt.update("1", 50, 50, t0 + 1)      # enters stand
    vt.update("1", 50, 50, t0 + 8)      # still in stand, 7s later
    visit = vt.finalize("1", t0 + 8)
    assert visit["is_stopper"] is True
    assert visit["dwell_seconds"] == 7.0
    assert visit["zone_path"] == "aisle→stand"


def test_below_threshold_dwell_is_not_a_stopper():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    vt.update("1", 50, 50, t0)
    vt.update("1", 50, 50, t0 + 2)
    visit = vt.finalize("1", t0 + 2)
    assert visit["is_stopper"] is False


def test_staff_flag_persists_once_set():
    vt = _tracker()
    t0 = 1000.0
    vt.update("1", 50, 50, t0, is_staff=False)
    vt.update("1", 50, 50, t0 + 1, is_staff=True)
    visit = vt.finalize("1", t0 + 1)
    assert visit["is_staff"] is True


def test_expire_stale_finalizes_missing_tracks():
    vt = _tracker()
    t0 = 1000.0
    vt.update("1", 50, 50, t0)
    finalized = vt.expire_stale(now=t0 + 10, grace_seconds=2.0)
    assert len(finalized) == 1
    assert vt.active_count() == 0


def test_active_and_staff_counts():
    vt = _tracker()
    t0 = 1000.0
    vt.update("1", 50, 50, t0, is_staff=False)
    vt.update("2", 50, 50, t0, is_staff=True)
    assert vt.active_count(exclude_staff=True) == 1
    assert vt.staff_count() == 1


def test_active_stopper_visit_ids_reflects_live_dwell():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    vt.update("1", 50, 50, t0)          # enters stand at t0
    assert vt.active_stopper_visit_ids(now=t0 + 2) == []       # not dwelling long enough yet
    assert len(vt.active_stopper_visit_ids(now=t0 + 6)) == 1   # now over threshold, still tracked


def test_active_stopper_visit_ids_excludes_staff_and_aisle():
    vt = _tracker(threshold=5.0)
    t0 = 1000.0
    vt.update("1", 50, 10, t0)                    # aisle the whole time
    vt.update("2", 50, 50, t0, is_staff=True)      # stand, but staff
    assert vt.active_stopper_visit_ids(now=t0 + 10) == []
