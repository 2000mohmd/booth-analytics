from services.ingestion.pipeline import attribute_demographics


def test_attributes_when_exactly_one_stopper_and_one_face():
    assert attribute_demographics(["v1"], [object()]) == "v1"


def test_skips_when_multiple_stoppers_present():
    assert attribute_demographics(["v1", "v2"], [object()]) is None


def test_skips_when_multiple_faces_detected():
    assert attribute_demographics(["v1"], [object(), object()]) is None


def test_skips_when_no_stoppers_or_no_faces():
    assert attribute_demographics([], [object()]) is None
    assert attribute_demographics(["v1"], []) is None


def test_skips_when_both_empty():
    assert attribute_demographics([], []) is None


def test_skips_when_multiple_stoppers_and_multiple_faces():
    assert attribute_demographics(["v1", "v2"], [object(), object()]) is None
