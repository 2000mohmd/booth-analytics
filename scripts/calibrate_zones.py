"""Interactive tool: click points to draw aisle/stand/table polygons on a paused frame from a
video/camera source, save them into a booth config's `zones` block. Left-click adds a point,
'n' moves to the next zone, 's' saves, 'q' quits without saving, 'r' resets the current zone.
"""
import argparse

import cv2
import numpy as np
import yaml

ZONE_ORDER = ["aisle", "stand", "table"]
COLORS = {"aisle": (255, 200, 0), "stand": (0, 255, 0), "table": (0, 128, 255)}


def _grab_first_frame(source: str | int):
    cap = cv2.VideoCapture(source)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read a frame from {source}")
    return frame


def run(source: str | int, booth_config_path: str):
    frame = _grab_first_frame(source)
    zones: dict[str, list[list[int]]] = {z: [] for z in ZONE_ORDER}
    zone_idx = 0

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            zones[ZONE_ORDER[zone_idx]].append([x, y])

    window = "calibrate_zones - left-click: add point, n: next zone, r: reset, s: save, q: quit"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_click)

    while True:
        preview = frame.copy()
        for name, pts in zones.items():
            if len(pts) >= 2:
                cv2.polylines(preview, [np.array(pts, dtype=np.int32)],
                              isClosed=True, color=COLORS[name], thickness=2)
            for p in pts:
                cv2.circle(preview, tuple(p), 4, COLORS[name], -1)
        cv2.putText(preview, f"zone: {ZONE_ORDER[zone_idx]}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS[ZONE_ORDER[zone_idx]], 2)
        cv2.imshow(window, preview)

        key = cv2.waitKey(20) & 0xFF
        if key == ord("n"):
            zone_idx = (zone_idx + 1) % len(ZONE_ORDER)
        elif key == ord("r"):
            zones[ZONE_ORDER[zone_idx]] = []
        elif key == ord("s"):
            _save(zones, booth_config_path)
            break
        elif key == ord("q"):
            break

    cv2.destroyAllWindows()


def _save(zones: dict, booth_config_path: str):
    with open(booth_config_path) as f:
        cfg = yaml.safe_load(f)
    cfg["zones"] = zones
    with open(booth_config_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"saved zones to {booth_config_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="video file path, RTSP URL, or USB index")
    parser.add_argument("--booth-config", default="configs/booth.yaml")
    args = parser.parse_args()
    run(args.source, args.booth_config)
