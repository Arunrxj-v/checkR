"""Non-destructive page preprocessing.

The pipeline applies, in order: EXIF-based rotation correction, grayscale
conversion, deskew estimation and correction, contrast enhancement, light
denoising, and resolution normalisation. Every step records what it did in
``PreprocessResult.applied`` so the process is explainable.

The original image is never overwritten; callers store the result as a new
derivative.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Long-edge target for normalised pages (keeps OCR quality, bounds memory).
NORMALISED_LONG_EDGE = 2200
THUMBNAIL_LONG_EDGE = 320
#: Do not bother auto-rotating tiny skews.
MIN_SKEW_DEGREES = 0.4
MAX_SKEW_DEGREES = 12.0


class PreprocessError(Exception):
    """Raised when a page image cannot be preprocessed."""


@dataclass(slots=True)
class PreprocessResult:
    processed: bytes
    thumbnail: bytes
    width: int
    height: int
    rotation_degrees: int = 0
    deskew_angle: float = 0.0
    applied: list[str] = field(default_factory=list)


def _open(data: bytes):
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def estimate_skew_angle(image) -> float:
    """Estimate document skew using projection-profile variance.

    A correctly aligned page of text has sharp peaks in its horizontal
    projection profile; rotating by the true skew minimises the profile's
    spread. We search a coarse-to-fine range and return degrees clockwise.
    """
    import numpy as np
    from PIL import Image

    try:
        gray = image.convert("L")
        # Downscale for speed; skew is scale-invariant.
        gray.thumbnail((900, 900))
        arr = np.asarray(gray, dtype=np.float32)
        if arr.size == 0:
            return 0.0
        # Binarise: text is dark.
        binary = (arr < 160).astype(np.float32)
        if binary.sum() < 50:  # essentially blank page
            return 0.0
    except Exception:  # pragma: no cover - defensive
        return 0.0

    best_angle = 0.0
    best_score = -1.0

    def score(angle: float) -> float:
        rotated = Image.fromarray((binary * 255).astype("uint8")).rotate(
            angle, resample=Image.BILINEAR, expand=False, fillcolor=0
        )
        prof = np.asarray(rotated, dtype=np.float32).sum(axis=1)
        if prof.size == 0:
            return 0.0
        # Variance of the row-sum profile: higher when lines align.
        return float(((prof - prof.mean()) ** 2).mean())

    angle = -MAX_SKEW_DEGREES
    while angle <= MAX_SKEW_DEGREES:
        s = score(angle)
        if s > best_score:
            best_score, best_angle = s, angle
        angle += 1.0

    # Refine around the coarse best in 0.25 degree steps.
    for angle in (best_angle + d * 0.25 for d in range(-3, 4)):
        s = score(angle)
        if s > best_score:
            best_score, best_angle = s, angle

    return round(best_angle, 2)


def preprocess_page(data: bytes) -> PreprocessResult:
    """Run the full preprocessing pipeline on one page image."""
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise PreprocessError("Image support is unavailable (Pillow not installed).") from exc

    try:
        img = _open(data)
    except Exception as exc:
        raise PreprocessError(f"Could not open page image: {exc}") from exc

    applied: list[str] = []
    rotation_degrees = 0

    # 1. EXIF orientation (phone photos).
    try:
        if img.getexif().get(0x0112):  # orientation tag present
            img = ImageOps.exif_transpose(img)
            applied.append("exif_rotation")
    except Exception:  # pragma: no cover
        pass

    # 2. Deskew.
    deskew_angle = 0.0
    try:
        deskew_angle = estimate_skew_angle(img)
        if MIN_SKEW_DEGREES < abs(deskew_angle) <= MAX_SKEW_DEGREES:
            img = img.rotate(
                deskew_angle, resample=Image.BICUBIC, expand=True, fillcolor="white"
            )
            applied.append("deskew")
        else:
            deskew_angle = 0.0
    except Exception:  # pragma: no cover - never fail a page over deskew
        deskew_angle = 0.0

    # 3. Grayscale + autocontrast for legibility on low-contrast scans.
    try:
        img = img.convert("L")
        img = ImageOps.autocontrast(img, cutoff=1)
        applied.append("grayscale_autocontrast")
    except Exception as exc:  # pragma: no cover
        raise PreprocessError(f"Failed to enhance contrast: {exc}") from exc

    # 4. Light denoising (median) — removes scan speckle without blurring strokes.
    try:
        img = img.filter(ImageFilter.MedianFilter(size=3))
        applied.append("denoise_median3")
    except Exception:  # pragma: no cover
        pass

    # 5. Resolution normalisation (never upscale aggressively).
    try:
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > NORMALISED_LONG_EDGE:
            scale = NORMALISED_LONG_EDGE / long_edge
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            applied.append("downscaled")
        elif long_edge < 1000:
            scale = 1000 / long_edge
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            applied.append("upscaled_small")
    except Exception:  # pragma: no cover
        pass

    width, height = img.size

    processed_buf = io.BytesIO()
    img.save(processed_buf, format="JPEG", quality=88, optimize=True)
    processed = processed_buf.getvalue()

    thumb = img.copy()
    thumb.thumbnail((THUMBNAIL_LONG_EDGE, THUMBNAIL_LONG_EDGE))
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, format="JPEG", quality=80)
    thumbnail = thumb_buf.getvalue()

    return PreprocessResult(
        processed=processed,
        thumbnail=thumbnail,
        width=width,
        height=height,
        rotation_degrees=rotation_degrees,
        deskew_angle=deskew_angle,
        applied=applied,
    )
