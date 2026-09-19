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
Face detector (SCRFD / RetinaFace-mobile) and age-gender classifier are NOT auto-downloaded
here - pick and vet a specific export before Phase 3, then drop the .onnx files at the paths
in configs/models.yaml (models.face_detector.weights / models.demographics.weights) and update
services/perception/demographics.py's FaceDetector.detect_faces() pre/post-processing to match
that export's input/output layout.
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
