import numpy as np
import pytest

from services.perception.demographics import (
    _age_to_bracket,
    _distance2bbox,
    _nms,
    _scrfd_anchor_centers,
    decode_scrfd_outputs,
)


def test_anchor_centers_grid_and_stacking():
    centers = _scrfd_anchor_centers(height=2, width=2, stride=32, num_anchors=2)
    # 2x2 grid * 2 anchors per cell = 8 rows of (x, y)
    assert centers.shape == (8, 2)
    # each grid cell's center should appear twice (once per stacked anchor)
    unique = {tuple(c) for c in centers}
    assert unique == {(0.0, 0.0), (32.0, 0.0), (0.0, 32.0), (32.0, 32.0)}


def test_distance2bbox_recovers_box_from_center_and_distances():
    centers = np.array([[10.0, 10.0]])
    distances = np.array([[4.0, 3.0, 6.0, 7.0]])  # left, top, right, bottom
    boxes = _distance2bbox(centers, distances)
    assert boxes.tolist() == [[6.0, 7.0, 16.0, 17.0]]


def test_nms_drops_heavily_overlapping_lower_score_box():
    boxes = np.array([
        [0.0, 0.0, 10.0, 10.0],
        [1.0, 1.0, 11.0, 11.0],  # heavy overlap with box 0
        [50.0, 50.0, 60.0, 60.0],  # separate face
    ])
    scores = np.array([0.9, 0.8, 0.7])
    keep = _nms(boxes, scores, iou_threshold=0.4)
    assert keep == [0, 2]


def test_decode_scrfd_outputs_single_level_picks_high_score_anchor():
    # stride=32 on a 64x64 input -> 2x2 grid, 2 anchors/cell = 8 anchors
    stride = 32
    input_size = 64
    num_anchors = 8
    scores = np.zeros((num_anchors, 1), dtype=np.float32)
    bbox_preds = np.zeros((num_anchors, 4), dtype=np.float32)

    winner = 3
    scores[winner, 0] = 0.95
    # distances (already divided by stride, decode multiplies back by stride)
    bbox_preds[winner] = [0.1, 0.1, 0.1, 0.1]

    boxes, out_scores = decode_scrfd_outputs(
        [scores, bbox_preds], input_size=input_size, strides=(stride,),
        num_anchors=2, score_threshold=0.5, nms_threshold=0.4,
    )

    assert len(boxes) == 1
    assert out_scores[0] == 0.95
    # anchor centers for this grid are stacked in pairs per cell in row-major order:
    # (0,0),(0,0),(32,0),(32,0),(0,32),(0,32),(32,32),(32,32) -> winner idx 3 -> center (32,0)
    cx, cy = 32.0, 0.0
    dist = 0.1 * stride
    expected = [cx - dist, cy - dist, cx + dist, cy + dist]
    assert boxes[0].tolist() == pytest.approx(expected)


def test_decode_scrfd_outputs_returns_empty_when_nothing_above_threshold():
    scores = np.zeros((8, 1), dtype=np.float32)
    bbox_preds = np.zeros((8, 4), dtype=np.float32)
    boxes, out_scores = decode_scrfd_outputs(
        [scores, bbox_preds], input_size=64, strides=(32,), num_anchors=2,
    )
    assert len(boxes) == 0
    assert len(out_scores) == 0


def test_age_to_bracket_boundaries():
    assert _age_to_bracket(17.9) == "under18"
    assert _age_to_bracket(18.0) == "18-35"
    assert _age_to_bracket(35.9) == "18-35"
    assert _age_to_bracket(36.0) == "36-55"
    assert _age_to_bracket(55.9) == "36-55"
    assert _age_to_bracket(56.0) == "55+"
