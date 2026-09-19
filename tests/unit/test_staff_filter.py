import numpy as np

from services.perception.staff_filter import is_staff

MARKER = {"type": "color_range", "hsv_lower": [35, 80, 80], "hsv_upper": [85, 255, 255]}


def _solid_bgr_crop(bgr: tuple[int, int, int], size=40) -> np.ndarray:
    return np.full((size, size, 3), bgr, dtype=np.uint8)


def test_green_marker_crop_is_staff():
    green = _solid_bgr_crop((0, 255, 0))  # pure green -> hue ~60, within [35,85]
    assert is_staff(green, MARKER) is True


def test_unrelated_color_crop_is_not_staff():
    red = _solid_bgr_crop((0, 0, 255))  # pure red -> hue ~0, outside range
    assert is_staff(red, MARKER) is False


def test_empty_crop_is_not_staff():
    assert is_staff(np.zeros((0, 0, 3), dtype=np.uint8), MARKER) is False


def test_qr_marker_type_not_yet_implemented_returns_false():
    assert is_staff(_solid_bgr_crop((0, 255, 0)), {"type": "qr"}) is False
