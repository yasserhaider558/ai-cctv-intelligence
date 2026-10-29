"""Object detection: model resolution, YOLO inference, class catalogue."""

from detection.detector import Detector, DetectorError
from detection.types import Detection, DetectionResult

__all__ = ["Detector", "DetectorError", "Detection", "DetectionResult"]
