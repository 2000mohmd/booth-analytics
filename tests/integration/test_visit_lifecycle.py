"""Regression test for the ordering bug: demographics get attached to a track while it's
still active (before finalize() ever runs), on a row that must already exist in the DB -
and finalize() must not stomp that data back to NULL when the track later disappears.
"""
from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap

ZONES = {
    "aisle": [[0, 0], [100, 0], [100, 20], [0, 20]],
    "stand": [[0, 20], [100, 20], [100, 80], [0, 80]],
}


def test_demographics_survive_finalize(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    vt = VisitTracker(
        booth_id="booth-01", zone_map=ZoneMap(ZONES), stopper_threshold_s=5.0,
        on_track_created=lambda stub: store.insert_visit(conn, stub),
    )

    t0 = 1000.0
    vt.update("1", 50, 50, t0)  # track created -> stub row inserted via callback

    row = conn.execute("SELECT * FROM visits").fetchone()
    assert row is not None
    assert row["exited_at"] is None

    stopper_ids = vt.active_stopper_visit_ids(now=t0 + 6)
    assert len(stopper_ids) == 1
    visit_id = stopper_ids[0]

    # eye-level camera attaches demographics while the track is still active
    store.update_visit_demographics(conn, visit_id, "female", 0.92, "18-35", 0.88)

    # track disappears - overhead loop finalizes it
    visit = vt.finalize("1", t0 + 8)
    store.finalize_visit(conn, visit)

    row = conn.execute("SELECT * FROM visits WHERE visit_id=?", (visit_id,)).fetchone()
    assert row["exited_at"] is not None
    assert row["is_stopper"] == 1
    assert row["gender_est"] == "female"  # survived finalize, not wiped to NULL
    assert row["age_bracket"] == "18-35"
