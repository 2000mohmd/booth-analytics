"""Lightweight face-identity matching for single-camera deployments, where the overhead camera
is the only camera in the booth and there's no separate eye-level stream to attach faces to
tracks unambiguously (see services/ingestion/pipeline.py's inline face-id path, used when a
booth has no configured eyelevel camera).

This is NOT a production face-recognition system: embeddings come from an unaligned face crop
(no 5-point landmark alignment - FaceDetector.detect_faces_with_boxes() returns boxes, not
landmarks), so matches are coarser than a properly aligned ArcFace pipeline. It's good enough to
answer "is this the same person I was just tracking a moment ago" (same session, same lighting,
same camera) within a short time window - not "is this person X in a gallery of thousands".
"""
import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Both embeddings are pre-normalized by FaceEmbedder.embed(), so this is just a dot product."""
    return float(np.dot(a, b))


class FaceEmbedder:
    """w600k_mbf.onnx (MobileFaceNet, from insightface's buffalo_sc pack - see
    scripts/export_models.py) or any compatible ArcFace-style model: 112x112 BGR input,
    single 512-d embedding output."""

    INPUT_SIZE = 112

    def __init__(self, weights_path: str):
        import onnxruntime as ort

        from services.perception.demographics import FaceDetector

        self.session = ort.InferenceSession(weights_path, providers=FaceDetector._providers())
        self.input_name = self.session.get_inputs()[0].name

    def embed(self, face_crop: np.ndarray) -> np.ndarray:
        import cv2

        resized = cv2.resize(face_crop, (self.INPUT_SIZE, self.INPUT_SIZE))
        blob = cv2.dnn.blobFromImage(
            resized, 1.0 / 127.5, (self.INPUT_SIZE, self.INPUT_SIZE),
            (127.5, 127.5, 127.5), swapRB=True,
        )
        embedding = self.session.run(None, {self.input_name: blob})[0][0]
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 0 else embedding
