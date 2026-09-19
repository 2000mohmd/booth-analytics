"""Face detection + age/gender classification, run only on stoppers on the eye-level stream
(never on every passerby - keeps compute down and avoids over-collecting per the build plan).

Below-threshold results come back as 'unknown' rather than a guessed label.
"""
from dataclasses import dataclass

import cv2
import numpy as np

GENDERS = ["female", "male"]
AGE_BRACKETS = ["under18", "18-35", "36-55", "55+"]


@dataclass
class DemographicEstimate:
    gender: str
    gender_conf: float
    age_bracket: str
    age_conf: float


class FaceDetector:
    """SCRFD/RetinaFace-mobile ONNX model. Returns face crops (BGR) from a frame."""

    def __init__(self, weights_path: str, confidence_threshold: float = 0.5):
        import onnxruntime as ort

        self.session = ort.InferenceSession(weights_path, providers=self._providers())
        self.confidence_threshold = confidence_threshold

    @staticmethod
    def _providers() -> list[str]:
        import onnxruntime as ort

        available = ort.get_available_providers()
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def detect_faces(self, frame: np.ndarray) -> list[np.ndarray]:
        raise NotImplementedError(
            "Model-specific pre/post-processing depends on the exact SCRFD export used - "
            "wire up against the real weights during Phase 3, see scripts/export_models.py."
        )


class DemographicsClassifier:
    def __init__(self, weights_path: str, confidence_threshold: float = 0.6):
        import onnxruntime as ort

        self.session = ort.InferenceSession(weights_path, providers=FaceDetector._providers())
        self.confidence_threshold = confidence_threshold
        self.input_name = self.session.get_inputs()[0].name

    def _preprocess(self, face_crop: np.ndarray) -> np.ndarray:
        resized = cv2.resize(face_crop, (64, 64))
        chw = resized.transpose(2, 0, 1).astype(np.float32) / 255.0
        return np.expand_dims(chw, axis=0)

    def estimate(self, face_crop: np.ndarray) -> DemographicEstimate:
        outputs = self.session.run(None, {self.input_name: self._preprocess(face_crop)})
        gender_probs, age_probs = outputs[0][0], outputs[1][0]

        g_idx = int(np.argmax(gender_probs))
        a_idx = int(np.argmax(age_probs))
        g_conf, a_conf = float(gender_probs[g_idx]), float(age_probs[a_idx])

        return DemographicEstimate(
            gender=GENDERS[g_idx] if g_conf >= self.confidence_threshold else "unknown",
            gender_conf=g_conf,
            age_bracket=AGE_BRACKETS[a_idx] if a_conf >= self.confidence_threshold else "unknown",
            age_conf=a_conf,
        )
