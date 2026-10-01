"""YOLO person detector. Thin wrapper over ultralytics so callers don't touch the model API directly."""
import logging
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

PERSON_CLASS_ID = 0  # COCO 'person'


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def centroid(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


class PersonDetector:
    """One instance can safely be shared across several overhead camera threads (detect() is
    lock-serialized) - worth doing on constrained GPU memory, where loading N separate model
    copies for N cameras burns memory a shared model doesn't need. Serializing inference calls
    costs some throughput under concurrency, but booth analytics doesn't need per-camera
    framerate much above a few fps, so this trades a little latency for a lot less memory."""

    def __init__(self, weights_path: str, confidence_threshold: float = 0.4, device: str = "cuda"):
        from ultralytics import YOLO  # imported lazily - heavy dep, only needed at runtime

        self.model = YOLO(weights_path)
        self.confidence_threshold = confidence_threshold
        self.device = device
        self._lock = threading.Lock()
        self._cuda_checked = device != "cuda"  # nothing to verify if CPU was actually requested

        if device == "cuda":
            self._assert_cuda_compiled_in()

    def _assert_cuda_compiled_in(self):
        """First-line check: does this onnxruntime-gpu install even have the CUDA provider
        compiled in? Catches the most common failure (wrong package/version installed) at
        startup rather than as an unexplained slowdown discovered live at the event. This alone
        isn't sufficient - see _assert_cuda_session_active(), called after the first real
        inference, for the check that confirms the provider actually activated for this model."""
        import onnxruntime as ort

        available = ort.get_available_providers()
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError(
                f"device='cuda' requested but CUDAExecutionProvider is not compiled into this "
                f"onnxruntime install (sees: {available}). Detection would silently run on CPU - "
                f"check onnxruntime-gpu / CUDA / cuDNN version compatibility (see "
                f"requirements.txt) rather than deploying like this."
            )
        log.info("onnxruntime CUDAExecutionProvider is compiled in: %s", available)

    def _assert_cuda_session_active(self):
        """ultralytics' ONNX backend does not raise if CUDAExecutionProvider fails to *activate*
        for this session even when it's compiled in (e.g. a driver/cuDNN mismatch at session
        creation) - it silently falls back to CPU execution per-call. The only symptom would be
        detection running ~10-20x slower under real camera load, discovered live at the event
        instead of at startup. Inspect the actual onnxruntime session ultralytics created and
        confirm CUDAExecutionProvider is genuinely active, not just available in principle."""
        try:
            session = self.model.predictor.model.session
            active = session.get_providers()
        except AttributeError:
            log.warning("could not introspect the underlying onnxruntime session to confirm "
                        "CUDAExecutionProvider is active - ultralytics' internal API may have "
                        "changed; verify GPU usage manually (e.g. nvidia-smi during inference)")
            return
        if not active or active[0] != "CUDAExecutionProvider":
            raise RuntimeError(
                f"CUDAExecutionProvider was compiled in but did not activate for this model's "
                f"session (active providers: {active}) - detection is silently running on CPU. "
                f"Check CUDA/cuDNN driver compatibility on this machine."
            )
        log.info("confirmed CUDAExecutionProvider is active for the detection session")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._lock:
            results = self.model.predict(
                frame, classes=[PERSON_CLASS_ID], conf=self.confidence_threshold,
                device=self.device, verbose=False,
            )[0]
            if not self._cuda_checked:
                self._assert_cuda_session_active()
                self._cuda_checked = True
        return [
            Detection(x1=float(b[0]), y1=float(b[1]), x2=float(b[2]), y2=float(b[3]), confidence=float(c))
            for b, c in zip(results.boxes.xyxy.tolist(), results.boxes.conf.tolist())
        ]
