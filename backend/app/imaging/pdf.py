"""PDF inspection, validation and page rendering.

The original uploaded PDF is never modified. Pages are rasterised into images
that flow through the same preprocessing pipeline as direct image uploads.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Rasterisation target — ~200 DPI is a good balance of OCR quality and size.
RENDER_DPI = 200


class DocumentError(Exception):
    """Raised when an uploaded document cannot be read as a PDF or image."""


@dataclass(slots=True)
class RenderedPage:
    page_number: int
    image_bytes: bytes
    width: int
    height: int


def is_pdf(content_type: str | None, filename: str | None, data: bytes | None = None) -> bool:
    if data is not None and data[:5] == b"%PDF-":
        return True
    if content_type and "pdf" in content_type.lower():
        return True
    return bool(filename and filename.lower().endswith(".pdf"))


def pdf_page_count(data: bytes) -> int:
    """Return the number of pages, raising :class:`DocumentError` if unreadable."""
    try:
        import pymupdf  # PyMuPDF (module renamed from `fitz`)
        fitz = pymupdf
    except ImportError as exc:  # pragma: no cover
        raise DocumentError("PDF support is unavailable (PyMuPDF not installed).") from exc

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise DocumentError("The PDF is password-protected and cannot be read.")
            return doc.page_count
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Could not read the PDF: {exc}") from exc


def render_pdf_pages(
    data: bytes,
    *,
    dpi: int = RENDER_DPI,
    max_pages: int | None = None,
) -> list[RenderedPage]:
    """Rasterise every PDF page to PNG bytes (in memory)."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise DocumentError("PDF support is unavailable (PyMuPDF not installed).") from exc
    fitz = pymupdf

    limit = max_pages or settings.max_submission_pages
    pages: list[RenderedPage] = []

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise DocumentError("The PDF is password-protected and cannot be read.")
            if doc.page_count > limit:
                raise DocumentError(
                    f"PDF has {doc.page_count} pages, which exceeds the limit of {limit}."
                )
            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            for index in range(doc.page_count):
                page = doc.load_page(index)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                png = pix.tobytes("png")
                pages.append(
                    RenderedPage(
                        page_number=index + 1,
                        image_bytes=png,
                        width=pix.width,
                        height=pix.height,
                    )
                )
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Failed while rendering the PDF: {exc}") from exc

    if not pages:
        raise DocumentError("The PDF contained no pages.")
    return pages


def normalise_upload_image(data: bytes, *, content_type: str | None = None) -> bytes:
    """Validate and normalise a directly-uploaded image to PNG bytes."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover
        raise DocumentError("Image support is unavailable (Pillow not installed).") from exc

    try:
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except UnidentifiedImageError as exc:
        raise DocumentError("The uploaded file is not a readable image.") from exc
    except Exception as exc:
        raise DocumentError(f"Could not read the image: {exc}") from exc
