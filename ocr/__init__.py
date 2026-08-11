"""ocr — Image & PDF OCR with pluggable backends.

Backends:
    ovis    (default): OvisOCR2 MLX — Markdown OCR with visual-region cropping.
    mineru:            MinerU 3.4.4 — formula→LaTeX, table→HTML.
    deepseek:          DeepSeek-OCR-2 — Vision-Language OCR, GPU/MPS/CPU.
    logics:            Logics-Parsing-v2 — Qwen3VL-based OCR, GPU/MPS/CPU.
    paddle:            PaddleOCR — PP-OCRv5, 109 languages, doc unwarping.
    api:               Generic API — OpenAI-compatible vision API.

Usage:
    from ocr._ovis_ocr import OvisOCR2
    from ocr._mineru_ocr import MinerUOCR
    from ocr._ocr_api import OCRApiBackend
    from ocr.cli import main
"""

from __future__ import annotations

from pathlib import Path


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
