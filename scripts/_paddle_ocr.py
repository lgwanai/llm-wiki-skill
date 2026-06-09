#!/usr/bin/env python3
"""_paddle_ocr.py — PaddleOCR backend for PDF and image OCR.

PaddleOCR supports:
- 109 languages
- Document orientation classification
- Document unwarping/deskewing
- PP-OCRv5 high-accuracy model

Usage:
    from _paddle_ocr import PaddleOCRWrapper
    
    ocr = PaddleOCRWrapper.from_config()
    text = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"


class PaddleOCRWrapper:
    """PaddleOCR wrapper with configurable parameters."""

    def __init__(
        self,
        lang: str = "ch",
        use_doc_orientation_classify: bool = True,
        use_doc_unwarping: bool = True,
        models_path: Optional[str] = None,
    ):
        self.lang = lang
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.models_path = models_path
        
        self._ocr = None

    @classmethod
    def from_config(cls, path: Optional[Path] = None) -> "PaddleOCRWrapper":
        """Create instance from unified OCR config."""
        from config import get_ocr_config

        paddleocr_config = get_ocr_config().get("options", {})
        
        return cls(
            lang=paddleocr_config.get("lang", "ch"),
            use_doc_orientation_classify=paddleocr_config.get("use_doc_orientation_classify", True),
            use_doc_unwarping=paddleocr_config.get("use_doc_unwarping", True),
            models_path=paddleocr_config.get("models_path"),
        )

    def _init_ocr(self):
        """Lazy initialization of PaddleOCR engine."""
        if self._ocr is not None:
            return self._ocr
        
        try:
            from paddleocr import PaddleOCR
            
            self._ocr = PaddleOCR(
                lang=self.lang,
                use_doc_orientation_classify=self.use_doc_orientation_classify,
                use_doc_unwarping=self.use_doc_unwarping,
                show_log=False,
            )
            return self._ocr
            
        except ImportError:
            raise RuntimeError(
                "PaddleOCR not installed. Install with: pip install paddleocr paddlepaddle"
            )

    def ocr_image(self, image_path: str) -> str:
        """Extract text from an image file.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Extracted text in markdown format
        """
        ocr = self._init_ocr()
        
        try:
            result = ocr.ocr(image_path, cls=True)
            
            if not result or not result[0]:
                return ""
            
            lines = []
            for item in result[0]:
                if item and len(item) >= 2:
                    text = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                    lines.append(text)
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"PaddleOCR failed for {image_path}: {e}")
            raise

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: Optional[int] = None
    ) -> Path:
        """Extract text from a PDF file.
        
        Args:
            pdf_path: Path to PDF file
            output_dir: Directory to save results
            max_pages: Maximum pages to process
            
        Returns:
            Path to output markdown file
        """
        ocr = self._init_ocr()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            import fitz as pymupdf
            
            doc = pymupdf.open(pdf_path)
            pages_to_process = range(min(len(doc), max_pages or len(doc)))
            
            all_text = []
            
            for page_num in pages_to_process:
                page = doc[page_num]
                
                pix = page.get_pixmap(dpi=150)
                img_data = pix.tobytes("png")
                
                temp_img = output_dir / f"page_{page_num}.png"
                temp_img.write_bytes(img_data)
                
                result = ocr.ocr(str(temp_img), cls=True)
                
                page_text = []
                if result and result[0]:
                    for item in result[0]:
                        if item and len(item) >= 2:
                            text = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                            page_text.append(text)
                
                all_text.append(f"## Page {page_num + 1}\n\n" + "\n".join(page_text))
                
                temp_img.unlink()
            
            doc.close()
            
            output_file = output_dir / f"{Path(pdf_path).stem}.md"
            output_file.write_text("\n\n".join(all_text), encoding="utf-8")
            
            return output_file
            
        except ImportError:
            raise RuntimeError(
                "PyMuPDF not installed. Install with: pip install pymupdf"
            )
        except Exception as e:
            logger.error(f"PaddleOCR PDF failed for {pdf_path}: {e}")
            raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PaddleOCR backend")
    parser.add_argument("file", help="Image or PDF file")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("--lang", default="ch", help="Language (ch, en, etc.)")
    args = parser.parse_args()
    
    ocr = PaddleOCRWrapper(lang=args.lang)
    
    if Path(args.file).suffix.lower() == ".pdf":
        output_dir = Path(args.output or f"{args.file}_ocr")
        result = ocr.ocr_pdf(args.file, output_dir)
        print(f"Output: {result}")
    else:
        text = ocr.ocr_image(args.file)
        print(text)
