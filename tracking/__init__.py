"""Tracking: ByteTrack (via Ultralytics) plus a dependency-free IoU fallback."""

from tracking.fallback_tracker import SimpleTracker, iou
from tracking.trails import TrailStore, direction_label

__all__ = ["SimpleTracker", "iou", "TrailStore", "direction_label"]
