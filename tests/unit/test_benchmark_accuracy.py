import pytest

from scripts.benchmark_accuracy import compare
from services.metrics_engine import store


@pytest.fixture
def conn(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    store.upsert_daily_summary(conn, {
        "booth_id": "booth-01", "day": "2026-09-19", "passersby": 100, "stoppers": 40,
        "capture_rate": 0.4, "avg_dwell": 12.0, "median_dwell": 10.0,
        "gender_split": {}, "age_split": {}, "peak_hour": "14",
    })
    return conn


def test_compare_computes_diffs(conn):
    ground_truth = {"2026-09-19": {"passersby": "98", "stoppers": "41", "avg_dwell": "11.0"}}
    results = compare(conn, "booth-01", ground_truth)
    assert results[0]["passersby_diff"] == 2
    assert results[0]["stoppers_diff"] == -1
    assert results[0]["avg_dwell_diff_s"] == 1.0


def test_compare_flags_missing_summary(conn):
    ground_truth = {"2099-01-01": {"passersby": "1", "stoppers": "1", "avg_dwell": "1"}}
    results = compare(conn, "booth-01", ground_truth)
    assert "error" in results[0]
