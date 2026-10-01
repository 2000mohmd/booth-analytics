"""Tests services/perception/detector.py's loud CUDA-active check without loading a real model -
stubs out ultralytics.YOLO and onnxruntime so this stays a fast unit test, not an integration
test needing real weights/a GPU."""
import sys
import types

import pytest


class _FakeSession:
    def __init__(self, providers):
        self._providers = providers

    def get_providers(self):
        return self._providers


class _FakePredictor:
    def __init__(self, providers):
        self.model = types.SimpleNamespace(session=_FakeSession(providers))


class _FakeYOLO:
    def __init__(self, weights_path):
        self.predictor = None  # set by the fake predict() call, mirroring ultralytics' laziness


@pytest.fixture
def stub_ultralytics(monkeypatch):
    module = types.ModuleType("ultralytics")
    module.YOLO = _FakeYOLO
    monkeypatch.setitem(sys.modules, "ultralytics", module)
    return module


@pytest.fixture
def stub_onnxruntime(monkeypatch):
    module = types.ModuleType("onnxruntime")
    module.get_available_providers = lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    return module


def test_raises_if_cuda_not_compiled_in(stub_ultralytics, monkeypatch):
    module = types.ModuleType("onnxruntime")
    module.get_available_providers = lambda: ["CPUExecutionProvider"]
    monkeypatch.setitem(sys.modules, "onnxruntime", module)

    from services.perception.detector import PersonDetector

    with pytest.raises(RuntimeError, match="not compiled into this onnxruntime install"):
        PersonDetector(weights_path="fake.onnx", device="cuda")


def test_does_not_raise_at_construction_if_cuda_compiled_in(stub_ultralytics, stub_onnxruntime):
    from services.perception.detector import PersonDetector

    detector = PersonDetector(weights_path="fake.onnx", device="cuda")
    assert detector._cuda_checked is False  # session-activation check is deferred to first detect()


def test_cpu_device_skips_cuda_check_entirely(stub_ultralytics, monkeypatch):
    # no onnxruntime stub at all - if this path touched onnxruntime, importing it would fail
    monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)

    from services.perception.detector import PersonDetector

    detector = PersonDetector(weights_path="fake.onnx", device="cpu")
    assert detector._cuda_checked is True  # nothing to verify for CPU


def test_session_active_check_passes_when_cuda_is_first_provider(stub_ultralytics, stub_onnxruntime):
    from services.perception.detector import PersonDetector

    detector = PersonDetector(weights_path="fake.onnx", device="cuda")
    detector.model.predictor = _FakePredictor(["CUDAExecutionProvider", "CPUExecutionProvider"])
    detector._assert_cuda_session_active()  # should not raise


def test_session_active_check_raises_when_cuda_did_not_activate(stub_ultralytics, stub_onnxruntime):
    from services.perception.detector import PersonDetector

    detector = PersonDetector(weights_path="fake.onnx", device="cuda")
    detector.model.predictor = _FakePredictor(["CPUExecutionProvider"])  # silently fell back
    with pytest.raises(RuntimeError, match="did not activate"):
        detector._assert_cuda_session_active()


def test_session_active_check_warns_but_does_not_raise_if_introspection_fails(
    stub_ultralytics, stub_onnxruntime, caplog,
):
    from services.perception.detector import PersonDetector

    detector = PersonDetector(weights_path="fake.onnx", device="cuda")
    detector.model.predictor = None  # simulates ultralytics' internal API having changed
    detector._assert_cuda_session_active()  # should not raise, just log a warning
    assert "could not introspect" in caplog.text
