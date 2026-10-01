import sqlite3

import pytest
import yaml

from services.kiosk_display.data_source import KioskDataSource
from services.metrics_engine import store


@pytest.fixture
def booth_config(tmp_path):
    path = tmp_path / "booth.yaml"
    path.write_text(yaml.safe_dump({
        "booth_id": "booth-01",
        "cameras": [
            {"id": "cam_overhead_1", "role": "overhead", "source": "rtsp://x", "zones": {}},
            {"id": "cam_overhead_2", "role": "overhead", "source": "rtsp://x", "zones": {}},
            {"id": "cam_eyelevel", "role": "eyelevel", "source": "rtsp://x"},
        ],
    }))
    return str(path)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "events.db"
    store.connect(p)  # creates schema
    return str(p)


def test_only_overhead_cameras_are_tracked(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    assert ds.overhead_camera_ids == {"cam_overhead_1", "cam_overhead_2"}


def test_fetch_frame_refuses_eyelevel_camera(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    with pytest.raises(ValueError, match="refusing to fetch video"):
        ds.fetch_frame("cam_eyelevel")


def test_fetch_frame_refuses_unknown_camera(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    with pytest.raises(ValueError):
        ds.fetch_frame("not_a_real_camera")


def test_fetch_frame_returns_none_when_no_data(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    assert ds.fetch_frame("cam_overhead_1") is None


def test_fetch_frame_returns_stored_jpeg(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    write_conn = store.connect(db_path)
    store.set_live_debug_frame(write_conn, "cam_overhead_1", ts=__import__("time").time(), jpg_bytes=b"\xff\xd8fake")
    assert ds.fetch_frame("cam_overhead_1") == b"\xff\xd8fake"


def test_fetch_live_state_excludes_eyelevel_tracks(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    write_conn = store.connect(db_path)
    now = __import__("time").time()
    store.replace_live_tracks(write_conn, "cam_overhead_1", now, 640, 480,
                               [{"track_id": "t1", "x1": 0, "y1": 0, "x2": 10, "y2": 10, "zone": "stand"}])
    state = ds.fetch_live_state()
    assert "cam_overhead_1" in state["cameras"]
    assert "cam_eyelevel" not in state["cameras"]
    assert len(state["cameras"]["cam_overhead_1"]["tracks"]) == 1


def test_no_overhead_camera_raises_at_construction(db_path, tmp_path):
    path = tmp_path / "booth_no_overhead.yaml"
    path.write_text(yaml.safe_dump({
        "booth_id": "booth-01",
        "cameras": [{"id": "cam_eyelevel", "role": "eyelevel", "source": "rtsp://x"}],
    }))
    with pytest.raises(ValueError, match="no camera with role: overhead"):
        KioskDataSource(db_path, str(path))


def test_data_source_connection_is_read_only(db_path, booth_config):
    ds = KioskDataSource(db_path, booth_config)
    with pytest.raises(sqlite3.OperationalError):
        ds._conn.execute("INSERT INTO live_cameras (camera_id, frame_w, frame_h, ts) VALUES ('x', 1, 1, 1)")
