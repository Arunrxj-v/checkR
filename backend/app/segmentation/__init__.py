"""Question ↔ answer segmentation."""

from app.segmentation.segmenter import DetectedAnswer, Line, flatten_pages, segment_answers

__all__ = ["segment_answers", "flatten_pages", "DetectedAnswer", "Line"]
