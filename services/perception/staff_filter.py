"""Staff marker detection. v1: a distinct color range (lanyard/badge) inside the person's crop.

ponytail: color-range detection only; swap to QR/badge-code detection later if color proves
unreliable under venue lighting - marker_config['type'] == 'qr' is reserved for that upgrade.
"""
import cv2
import numpy as np

MIN_MARKER_PIXEL_FRACTION = 0.02  # crop must be at least 2% marker-colored pixels


def is_staff(track_crop: np.ndarray, marker_config: dict) -> bool:
    if marker_config.get("type") != "color_range" or track_crop.size == 0:
        return False

    hsv = cv2.cvtColor(track_crop, cv2.COLOR_BGR2HSV)
    lower = np.array(marker_config["hsv_lower"], dtype=np.uint8)
    upper = np.array(marker_config["hsv_upper"], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)

    fraction = float(np.count_nonzero(mask)) / mask.size
    return fraction >= MIN_MARKER_PIXEL_FRACTION
