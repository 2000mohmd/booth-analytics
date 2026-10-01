"""Fetch + export the detector to ONNX under models/. Run once per dev/edge machine.

Only the YOLO detector has a well-known public weight file (COCO-pretrained, Ultralytics
hub). The face detector (SCRFD) and age/gender classifier need a specific vetted export
per configs/models.yaml's licensing/accuracy requirements (Phase 3) - this script documents
where to get them rather than silently downloading an unvetted third-party model.
"""
import argparse
import os

DETECTOR_SOURCES = {
    "yolov8n": "yolov8n.pt",   # ultralytics resolves + downloads this by name
    "yolo11n": "yolo11n.pt",
}

MANUAL_MODEL_NOTES = """
Face detector (SCRFD) and age-gender classifier weights are NOT auto-downloaded here - pick and
vet a specific export (license + accuracy) before Phase 3, then drop the weights file at the path
in configs/models.yaml. services/perception/demographics.py's pre/post-processing is already
wired up against these two specific, publicly documented exports - no code changes needed if you
use them as-is:

  face_detector (models/scrfd.onnx): any standard insightface SCRFD export (500m/2.5g/10g all
  share the same output layout). Official distribution channel (GitHub releases under
  deepinsight/insightface) - review the license first:
      pip install insightface
      python -c "from insightface.utils.storage import ensure_available; \\
          print(ensure_available('models', 'buffalo_sc', root='~/.insightface'))"
  then copy the extracted det_500m.onnx to models/scrfd.onnx. If you use a different input
  resolution than 640x640, pass input_size= to FaceDetector().

  face_recognition (models/face_recognition.onnx, optional): the SAME buffalo_sc pack's other
  file, w600k_mbf.onnx - copy it too if you want same-camera duplicate-track detection on a
  single-camera booth (see services/perception/face_id.py). Skip it if you don't need that -
  everything else works fine without a face_recognition section in configs/models.yaml.
  Note: insightface's newer model_zoo.get_model(..., download=True) has a bug in some releases
  where it silently returns None instead of downloading - use ensure_available() above instead.

  demographics (models/age_gender.xml + sibling .bin): Intel Open Model Zoo's
  age-gender-recognition-retail-0013 (Apache 2.0), official distribution via Intel's public
  storage. openvino-dev needs Python <=3.12 (no wheels for newer Pythons as of writing) and a
  pinned version to avoid pip's resolver backtracking through incompatible old releases:
      pip install "openvino-dev==2024.6.0"   # in a 3.12-or-older venv if your main one is newer
      python -m omz_tools.omz_downloader --name age-gender-recognition-retail-0013 -o models/omz
  then copy models/omz/intel/age-gender-recognition-retail-0013/FP32/*.{xml,bin} to
  models/age_gender.{xml,bin}. This model ships as OpenVINO IR, not ONNX, and there's no
  maintained IR->ONNX converter - DemographicsClassifier runs the .xml directly via the
  `openvino` runtime package (a normal Python 3.14-compatible wheel, no build tools needed) when
  given a .xml path; it still accepts a .onnx export too if you have one.

If you pick a different export for either model, its exact pre/post-processing (input
size/normalization, output tensor order/shape) still needs to match what
services/perception/demographics.py implements - see that module's docstring.
"""


def export_detector(name: str, out_dir: str) -> str:
    from ultralytics import YOLO

    weights = DETECTOR_SOURCES[name]
    model = YOLO(weights)
    onnx_path = model.export(format="onnx")
    dest = os.path.join(out_dir, f"{name}.onnx")
    os.replace(onnx_path, dest)
    return dest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", choices=DETECTOR_SOURCES, default="yolov8n")
    parser.add_argument("--out-dir", default="models")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    dest = export_detector(args.detector, args.out_dir)
    print(f"detector exported to {dest}")
    print(MANUAL_MODEL_NOTES)


if __name__ == "__main__":
    main()
