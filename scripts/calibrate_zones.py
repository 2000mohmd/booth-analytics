"""Interactive tool: click points to draw zone polygons on a paused frame from a video/camera
source, save them into one overhead camera's `zones` block in the booth config (zones are
per-camera - pixel coordinates from one camera aren't meaningful on another). Left-click adds
a point, 'n' moves to the next zone, 's' saves, 'q' quits without saving, 'r' resets the
current zone.
"""
import argparse

import cv2
import numpy as np
import yaml

DEFAULT_ZONE_ORDER = ["aisle", "stand", "table"]
COLORS = {"aisle": (255, 200, 0), "stand": (0, 255, 0), "table": (0, 128, 255)}


def _grab_first_frame(source: str | int):
    cap = cv2.VideoCapture(source)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read a frame from {source}")
    return frame


def _find_camera(cfg: dict, camera_id: str) -> dict:
    for cam in cfg["cameras"]:
        if cam["id"] == camera_id:
            return cam
    raise ValueError(f"no camera '{camera_id}' in booth config - check configs/booth.yaml's cameras list")


def run(source: str | int, booth_config_path: str, camera_id: str):
    with open(booth_config_path) as f:
        cfg = yaml.safe_load(f)
    camera = _find_camera(cfg, camera_id)

    # only calibrate the zones this camera's config already declares (e.g. a back-of-booth
    # camera that only ever sees the 'table' zone doesn't need aisle/stand points drawn on it)
    zone_order = list(camera.get("zones") or {}) or DEFAULT_ZONE_ORDER
    zone_colors = {name: COLORS.get(name, (200, 200, 200)) for name in zone_order}

    frame = _grab_first_frame(source)
    zones: dict[str, list[list[int]]] = {z: [] for z in zone_order}
    zone_idx = 0

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            zones[zone_order[zone_idx]].append([x, y])

    window = f"calibrate_zones [{camera_id}] - left-click: add point, n: next zone, r: reset, s: save, q: quit"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_click)

    while True:
        preview = frame.copy()
        for name, pts in zones.items():
            if len(pts) >= 2:
                cv2.polylines(preview, [np.array(pts, dtype=np.int32)],
                              isClosed=True, color=zone_colors[name], thickness=2)
            for p in pts:
                cv2.circle(preview, tuple(p), 4, zone_colors[name], -1)
        cv2.putText(preview, f"zone: {zone_order[zone_idx]}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, zone_colors[zone_order[zone_idx]], 2)
        cv2.imshow(window, preview)

        key = cv2.waitKey(20) & 0xFF
        if key == ord("n"):
            zone_idx = (zone_idx + 1) % len(zone_order)
        elif key == ord("r"):
            zones[zone_order[zone_idx]] = []
        elif key == ord("s"):
            _save(cfg, camera_id, zones, booth_config_path)
            break
        elif key == ord("q"):
            break

    cv2.destroyAllWindows()


def _save(cfg: dict, camera_id: str, zones: dict, booth_config_path: str):
    _find_camera(cfg, camera_id)["zones"] = zones
    with open(booth_config_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"saved zones for {camera_id} to {booth_config_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="video file path, RTSP URL, or USB index")
    parser.add_argument("--camera-id", required=True, help="must match a camera 'id' in booth.yaml")
    parser.add_argument("--booth-config", default="configs/booth.yaml")
    args = parser.parse_args()
    run(args.source, args.booth_config, args.camera_id)
