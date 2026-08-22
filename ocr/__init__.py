"""ocr — Image & PDF OCR with pluggable backends.

Backends:
    paddlevl (default): PaddleOCR-VL-1.6 + PP-DocLayoutV3 + MLX-VLM.
    ovis:              OvisOCR2 MLX — Markdown OCR with visual-region cropping.
    mineru:            MinerU 3.4.4 — formula→LaTeX, table→HTML.
    deepseek:          DeepSeek-OCR-2 — Vision-Language OCR, GPU/MPS/CPU.
    logics:            Logics-Parsing-v2 — Qwen3VL-based OCR, GPU/MPS/CPU.
    paddle:            PaddleOCR — PP-OCRv5, 109 languages, doc unwarping.
    api:               Generic API — OpenAI-compatible vision API.

Usage:
    import ocr

    print(ocr.list_models())
    engine = ocr.create_backend()
    text = engine.ocr_image("scan.png")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["create_backend", "get_default_model", "list_models", "set_default_model"]


def create_backend(name: str | None = None) -> Any:
    """Create a backend by key, or create the global default backend."""
    from ocr.registry import create_backend as _create_backend

    return _create_backend(name)


def list_models(check: bool = False) -> list[dict[str, Any]]:
    """Return supported model metadata without eagerly importing runtimes."""
    from ocr.registry import list_models as _list_models

    return _list_models(check)


def get_default_model() -> str:
    """Return the globally selected OCR model key."""
    from ocr.config import get_default_model as _get_default_model

    return _get_default_model()


def set_default_model(model: str) -> Path:
    """Persist the globally selected OCR model key."""
    from ocr.config import set_default_model as _set_default_model

    return _set_default_model(model)


def render_pdf_pages_to_images(pdf_path: Path, output_dir: Path, dpi: int = 150) -> list[Path]:
    """Render every page of a PDF to PNG images, returning them in page order.

    Shared helper used by OCR backends to avoid duplicating the PyMuPDF →
    page-image boilerplate.  Falls back to pdf2image when PyMuPDF is unavailable.

    The canonical implementation lives in compile_v2._render_pdf_pages_to_images;
    keep the two in sync.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        images: list[Path] = []
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(doc.page_count):
            pix = doc.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"page-{page_index + 1:03d}.png"
            pix.save(str(image_path))
            images.append(image_path)
        doc.close()
        return images
    except Exception as fitz_error:
        try:
            from pdf2image import convert_from_path

            pages = convert_from_path(str(pdf_path), dpi=dpi)
            images = []
            for page_index, page in enumerate(pages, start=1):
                image_path = output_dir / f"page-{page_index:03d}.png"
                page.save(str(image_path), "PNG")
                images.append(image_path)
            return images
        except Exception as pdf2image_error:
            raise RuntimeError(
                "Could not render PDF pages with PyMuPDF or pdf2image: "
                f"{fitz_error}; {pdf2image_error}"
            ) from pdf2image_error
