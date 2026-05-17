from __future__ import annotations
"""_paddle_ocr.py — PaddleOCR wrapper for text recognition and document parsing.

PaddleOCR (https://github.com/PaddlePaddle/PaddleOCR) provides PP-OCRv5 for
accurate text recognition (109 languages) and PaddleOCR-VL for document parsing.

Configuration: see ../wiki_config.yaml (paddleocr section).

Usage:
    from _paddle_ocr import PaddleOCRWrapper

    ocr = PaddleOCRWrapper.from_config()
    markdown = ocr.ocr_pdf("document.pdf", Path("results/"))
    text = ocr.ocr_image("screenshot.png")
"""

import logging
import os
import tempfile
from pathlib import Path

import yaml
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"


class PaddleOCRWrapper:
    def __init__(
        self,
        lang: str = "ch",
        use_doc_orientation_classify: bool = True,
        use_doc_unwarping: bool = True,
        text_det_thresh: float = 0.3,
        text_rec_score_thresh: float = 0.5,
    ):
        self.lang = lang
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.text_det_thresh = text_det_thresh
        self.text_rec_score_thresh = text_rec_score_thresh
        self._ocr = None

    @classmethod
    def from_config(cls, path: Path | None = None) -> "PaddleOCRWrapper":
        config_path = path or CONFIG_PATH
        cfg: dict = {}
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            cfg = config.get("paddleocr", {})

        return cls(
            lang=cfg.get("lang", "ch"),
            use_doc_orientation_classify=cfg.get("use_doc_orientation_classify", True),
            use_doc_unwarping=cfg.get("use_doc_unwarping", True),
            text_det_thresh=cfg.get("text_det_thresh", 0.3),
            text_rec_score_thresh=cfg.get("text_rec_score_thresh", 0.5),
        )

    @property
    def ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            logger.info("Initializing PaddleOCR (PP-OCRv5, lang=%s)...", self.lang)
            self._ocr = PaddleOCR(
                lang=self.lang,
                use_doc_orientation_classify=self.use_doc_orientation_classify,
                use_doc_unwarping=self.use_doc_unwarping,
                text_det_thresh=self.text_det_thresh,
                text_rec_score_thresh=self.text_rec_score_thresh,
            )
        return self._ocr

    def _image_to_markdown(self, image_path: str) -> str:
        result = self.ocr.predict(image_path)
        lines: list[str] = []
        for item in result:
            if isinstance(item, dict):
                rec_texts = item.get("rec_texts", [])
                if rec_texts:
                    lines.append(" ".join(rec_texts))
                    continue
                rec_text = item.get("rec_text", "")
                if rec_text:
                    lines.append(rec_text)
            elif isinstance(item, (list, tuple)):
                for sub in item:
                    if isinstance(sub, dict):
                        text = sub.get("text", "") or " ".join(sub.get("rec_texts", []))
                        if text:
                            lines.append(text)
                    elif isinstance(sub, (list, tuple)) and len(sub) >= 2:
                        text = sub[1] if isinstance(sub[1], str) else sub[1][0] if isinstance(sub[1], (list, tuple)) else ""
                        if text:
                            lines.append(str(text))
        return "\n".join(lines)

    def ocr_image(self, filepath: str) -> str:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        return self._image_to_markdown(filepath)

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: int | None = None,
    ) -> Path:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        import fitz

        doc = fitz.open(pdf_path)
        total = min(len(doc), max_pages) if max_pages else len(doc)
        logger.info("PaddleOCR PDF: %d pages → %s", total, output_dir)

        pages_md: list[str] = []
        for i in range(total):
            page = doc[i]
            pix = page.get_pixmap(dpi=200)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                pix.save(f.name)
                tmp_path = f.name
            try:
                text = self._image_to_markdown(tmp_path)
                pages_md.append(f"## Page {i + 1}\n\n{text}")
            finally:
                os.unlink(tmp_path)

        doc.close()
        output_path = output_dir / "output.md"
        output_path.write_text("\n\n".join(pages_md), encoding="utf-8")
        logger.info("Output: %s (%d bytes)", output_path, output_path.stat().st_size)
        return output_path
