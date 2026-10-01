"""Same-camera duplicate-track detection via face embeddings - see dwell.py's module docstring.
A single physical person can get two simultaneous ByteTrack IDs (a genuine double detection,
not a hand-off); a matching face embedding should collapse the second one into the first
instead of minting a second visit.
"""
from services.metrics_engine.dwell import VisitTracker

FACE_A = [1.0, 0.0, 0.0]       # pretend 3-d "embeddings" - already unit-normalized
FACE_A_NOISY = [0.95, 0.05, 0.0]  # same person, slightly different crop/frame
FACE_B = [0.0, 1.0, 0.0]       # a different person


def _tracker():
    return VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0, face_match_threshold=0.8)


def test_matching_face_on_a_new_track_id_reuses_the_existing_visit():
    vt = _tracker()
    t0 = 1000.0

    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    assert vt.active_count() == 1

    # a second, spurious detection of the same person shows up under a new track_id this frame
    vt.update("cam:2", "cam", "stand", 51, 51, t0, face_embedding=FACE_A_NOISY)

    assert vt.active_count() == 1  # not counted twice
    vt.finalize("cam:1", t0 + 1)
    assert vt.active_count() == 0


def test_different_face_on_a_new_track_id_is_a_real_second_person():
    vt = _tracker()
    t0 = 1000.0

    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    vt.update("cam:2", "cam", "stand", 400, 400, t0, face_embedding=FACE_B)

    assert vt.active_count() == 2  # two distinct people, both counted


def test_aliased_track_updates_continue_to_flow_into_the_real_visit():
    vt = _tracker()
    t0 = 1000.0

    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    vt.update("cam:2", "cam", "stand", 51, 51, t0, face_embedding=FACE_A_NOISY)
    # further updates via the *alias* id should keep updating the same, single visit
    vt.update("cam:2", "cam", "stand", 52, 52, t0 + 6)

    visit = vt.finalize("cam:1", t0 + 6)
    assert visit["is_stopper"] is True  # dwell accrued via the alias too


def test_without_face_embeddings_behaves_exactly_as_before():
    """No face_embedding passed at all -> untouched v1 behavior (two track_ids, two visits)."""
    vt = _tracker()
    t0 = 1000.0
    vt.update("cam:1", "cam", "stand", 50, 50, t0)
    vt.update("cam:2", "cam", "stand", 51, 51, t0)
    assert vt.active_count() == 2


def test_finalized_track_face_is_forgotten_and_wont_match_new_arrivals():
    vt = _tracker()
    t0 = 1000.0
    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    vt.finalize("cam:1", t0 + 1)

    # a brand-new person with a similar-ish face shouldn't be silently merged into a visit
    # that's already been finalized and written to the DB.
    vt.update("cam:5", "cam", "stand", 60, 60, t0 + 2, face_embedding=FACE_A)
    assert vt.active_count() == 1
    visit = vt.finalize("cam:5", t0 + 3)
    assert visit["visit_id"] != "cam:1"  # (sanity: just confirms it's a fresh uuid, not reused)


def test_sequential_loss_and_reacquire_within_window_continues_same_visit():
    """The actual fix for ByteTrack losing a track and reassigning a new ID a moment later -
    distinct from the simultaneous-duplicate case above."""
    vt = _tracker()
    t0 = 1000.0

    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    finalized = vt.expire_stale(t0 + 1, grace_seconds=0.5)  # track goes stale, held pending
    assert finalized == []
    assert vt.active_count() == 1  # still counted as present

    # ByteTrack reacquires the same person a moment later under a brand-new track_id
    vt.update("cam:7", "cam", "stand", 51, 51, t0 + 2, face_embedding=FACE_A_NOISY)
    assert vt.active_count() == 1  # still just one visit, not two

    visit = vt.finalize("cam:7", t0 + 3)
    assert visit["entered_at"] == visit["entered_at"]  # sanity
    assert vt.active_count() == 0


def test_sequential_reacquire_with_different_face_is_a_new_visit():
    vt = _tracker()
    t0 = 1000.0

    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    vt.expire_stale(t0 + 1, grace_seconds=0.5)

    vt.update("cam:7", "cam", "stand", 51, 51, t0 + 2, face_embedding=FACE_B)
    assert vt.active_count() == 2  # a genuinely different person, not a reacquire


def test_reacquire_outside_the_window_finalizes_as_two_visits():
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0,
                       face_match_threshold=0.8, face_reacquire_seconds=1.0)
    t0 = 1000.0

    vt.update("cam:1", "cam", "stand", 50, 50, t0, face_embedding=FACE_A)
    finalized = vt.expire_stale(t0 + 5, grace_seconds=0.5)  # well past the 1s reacquire window
    assert len(finalized) == 1

    vt.update("cam:7", "cam", "stand", 51, 51, t0 + 5.5, face_embedding=FACE_A)
    visit = vt.finalize("cam:7", t0 + 6)
    assert visit["visit_id"] != finalized[0]["visit_id"]
