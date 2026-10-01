"""Face detection + age/gender classification, run only on stoppers on the eye-level stream
(never on every passerby - keeps compute down and avoids over-collecting per the build plan).

Below-threshold results come back as 'unknown' rather than a guessed label.

Pinned to two specific, publicly documented ONNX exports (see scripts/export_models.py for how
to fetch + vet them - weights are not auto-downloaded here):
  - face_detector: SCRFD (any of the standard insightface exports - 500m/2.5g/10g all share the
    same output layout, just different anchor counts/strides), decoded per the reference decode
    in insightface's own scrfd.py (anchor centers + distance2bbox per FPN level, greedy NMS).
  - demographics: Intel Open Model Zoo's age-gender-recognition-retail-0013 - fixed 62x62 BGR
    input (no mean/scale normalization), a single scalar age regression output (multiply by 100
    for years) and a 2-class [female, male] softmax output.
"""
from dataclasses import dataclass

import cv2
import numpy as np

GENDERS = ["female", "male"]
AGE_BRACKETS = ["under18", "18-35", "36-55", "55+"]

SCRFD_STRIDES = (8, 16, 32)
SCRFD_NUM_ANCHORS = 2  # true for all standard scrfd_{500m,2.5g,10g} exports


@dataclass
class DemographicEstimate:
    gender: str
    gender_conf: float
    age_bracket: str
    age_conf: float


def _scrfd_anchor_centers(height: int, width: int, stride: int, num_anchors: int) -> np.ndarray:
    """Grid of anchor center points for one FPN level, in input-pixel space - matches the anchor
    layout SCRFD was trained/exported with (row-major grid, `num_anchors` stacked identical
    centers per cell since scrfd uses same-center anchors of different scale)."""
    centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
    centers = (centers * stride).reshape((-1, 2))
    if num_anchors > 1:
        centers = np.stack([centers] * num_anchors, axis=1).reshape((-1, 2))
    return centers


def _distance2bbox(centers: np.ndarray, distances: np.ndarray) -> np.ndarray:
    x1 = centers[:, 0] - distances[:, 0]
    y1 = centers[:, 1] - distances[:, 1]
    x2 = centers[:, 0] + distances[:, 2]
    y2 = centers[:, 1] + distances[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[1:][iou <= iou_threshold]
    return keep


def decode_scrfd_outputs(
    outputs: list[np.ndarray],
    input_size: int,
    strides: tuple[int, ...] = SCRFD_STRIDES,
    num_anchors: int = SCRFD_NUM_ANCHORS,
    score_threshold: float = 0.5,
    nms_threshold: float = 0.4,
) -> tuple[np.ndarray, np.ndarray]:
    """Pure-numpy SCRFD postprocessing: raw onnxruntime outputs -> (boxes_xyxy, scores) in the
    model's square input-pixel space (caller rescales to the original frame). Outputs are
    grouped by kind across levels (all scores, then all bboxes, then optional kps) - this is
    the order every standard scrfd export uses, not interleaved per-level.
    """
    num_levels = len(strides)
    all_boxes, all_scores = [], []
    for i, stride in enumerate(strides):
        scores = outputs[i].reshape(-1)
        bbox_preds = outputs[num_levels + i].reshape(-1, 4) * stride
        side = input_size // stride
        centers = _scrfd_anchor_centers(side, side, stride, num_anchors)
        boxes = _distance2bbox(centers, bbox_preds)
        mask = scores >= score_threshold
        all_boxes.append(boxes[mask])
        all_scores.append(scores[mask])

    boxes = np.concatenate(all_boxes, axis=0) if all_boxes else np.zeros((0, 4), dtype=np.float32)
    scores = np.concatenate(all_scores, axis=0) if all_scores else np.zeros((0,), dtype=np.float32)
    if len(boxes) == 0:
        return boxes, scores
    keep = _nms(boxes, scores, nms_threshold)
    return boxes[keep], scores[keep]


class FaceDetector:
    """SCRFD ONNX model. Returns face crops (BGR) from a frame."""

    def __init__(
        self, weights_path: str, confidence_threshold: float = 0.5,
        input_size: int = 640, nms_threshold: float = 0.4,
    ):
        import onnxruntime as ort

        self.session = ort.InferenceSession(weights_path, providers=self._providers())
        self.input_name = self.session.get_inputs()[0].name
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.input_size = input_size

    @staticmethod
    def _providers() -> list[str]:
        import onnxruntime as ort

        available = ort.get_available_providers()
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _preprocess(self, frame: np.ndarray) -> tuple[np.ndarray, float]:
        """Letterbox to a square `input_size` canvas (SCRFD is trained on square inputs) and
        return the resize scale so decoded boxes can be mapped back to the original frame."""
        h, w = frame.shape[:2]
        scale = self.input_size / max(h, w)
        resized = cv2.resize(frame, (round(w * scale), round(h * scale)))
        canvas = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 128.0, (self.input_size, self.input_size),
            (127.5, 127.5, 127.5), swapRB=True,
        )
        return blob, scale

    def detect_faces(self, frame: np.ndarray) -> list[np.ndarray]:
        return [crop for crop, _ in self.detect_faces_with_boxes(frame)]

    def detect_faces_with_boxes(
        self, frame: np.ndarray,
    ) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
        """Like detect_faces(), but also returns each crop's (x1, y1, x2, y2) in the original
        frame - needed to spatially match a face to a specific person track (see
        services/ingestion/pipeline.py's inline face-id path for single-camera booths)."""
        blob, scale = self._preprocess(frame)
        outputs = self.session.run(None, {self.input_name: blob})
        boxes, _ = decode_scrfd_outputs(
            outputs, self.input_size, score_threshold=self.confidence_threshold,
            nms_threshold=self.nms_threshold,
        )
        boxes = boxes / scale

        h, w = frame.shape[:2]
        results = []
        for x1, y1, x2, y2 in boxes:
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(w, int(x2)), min(h, int(y2))
            if x2 > x1 and y2 > y1:
                results.append((frame[y1:y2, x1:x2], (x1, y1, x2, y2)))
        return results


def _age_to_bracket(age_years: float) -> str:
    if age_years < 18:
        return "under18"
    if age_years < 36:
        return "18-35"
    if age_years < 56:
        return "36-55"
    return "55+"


class _OnnxBackend:
    """onnxruntime backend - used if weights_path is a .onnx export."""

    def __init__(self, weights_path: str):
        import onnxruntime as ort

        self.session = ort.InferenceSession(weights_path, providers=FaceDetector._providers())
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]

    def run(self, blob: np.ndarray) -> list[np.ndarray]:
        return self.session.run(None, {self.input_name: blob})


class _OpenVinoBackend:
    """OpenVINO IR backend - used if weights_path is a .xml export (this model's actual official
    distribution format from Intel's Open Model Zoo - there is no maintained IR->ONNX converter,
    so rather than force a lossy/unofficial conversion, this backend runs the IR directly)."""

    def __init__(self, weights_path: str):
        import openvino as ov

        core = ov.Core()
        model = core.read_model(weights_path)
        self.compiled = core.compile_model(model, "CPU")
        self.output_names = [o.get_any_name() for o in model.outputs]

    def run(self, blob: np.ndarray) -> list[np.ndarray]:
        result = self.compiled(blob)
        return [result[i] for i in range(len(self.output_names))]


class DemographicsClassifier:
    """age-gender-recognition-retail-0013: 62x62 BGR input, raw pixel values (no mean/scale
    normalization per the model's published spec), one scalar age-regression output (age/100)
    and one 2-class [female, male] softmax output. The age head has no natural per-prediction
    confidence (it's a regression, not a classification), so age_conf is always 1.0 - only the
    gender softmax gets threshold-filtered to 'unknown'.

    Accepts either a .onnx export or this model's native OpenVINO IR (.xml + sibling .bin) -
    see scripts/export_models.py's MANUAL_MODEL_NOTES for where to get either.
    """

    INPUT_SIZE = 62

    def __init__(self, weights_path: str, confidence_threshold: float = 0.6):
        self.backend = (
            _OpenVinoBackend(weights_path) if weights_path.endswith(".xml")
            else _OnnxBackend(weights_path)
        )
        self.confidence_threshold = confidence_threshold
        self._age_output_idx, self._gender_output_idx = self._resolve_output_order()

    def _resolve_output_order(self) -> tuple[int, int]:
        names = [n.lower() for n in self.backend.output_names]
        try:
            age_idx = next(i for i, n in enumerate(names) if "age" in n)
            gender_idx = next(i for i, n in enumerate(names) if i != age_idx)
        except StopIteration:
            age_idx, gender_idx = 0, 1
        return age_idx, gender_idx

    def _preprocess(self, face_crop: np.ndarray) -> np.ndarray:
        resized = cv2.resize(face_crop, (self.INPUT_SIZE, self.INPUT_SIZE))
        chw = resized.transpose(2, 0, 1).astype(np.float32)
        return np.expand_dims(chw, axis=0)

    def estimate(self, face_crop: np.ndarray) -> DemographicEstimate:
        outputs = self.backend.run(self._preprocess(face_crop))
        age_years = float(outputs[self._age_output_idx].reshape(-1)[0]) * 100.0
        gender_probs = outputs[self._gender_output_idx].reshape(-1)

        g_idx = int(np.argmax(gender_probs))
        g_conf = float(gender_probs[g_idx])

        return DemographicEstimate(
            gender=GENDERS[g_idx] if g_conf >= self.confidence_threshold else "unknown",
            gender_conf=g_conf,
            age_bracket=_age_to_bracket(age_years),
            age_conf=1.0,
        )
