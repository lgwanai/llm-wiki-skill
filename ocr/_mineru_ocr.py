#!/usr/bin/env python3
"""_mineru_ocr.py — MinerU OCR backend (v3.x).

MinerU is a high-precision PDF parsing tool that supports:
- Formula → LaTeX conversion
- Table → HTML conversion
- Multi-column layout detection
- Header/footer removal
- DOCX, PPTX, XLSX parsing

Uses mineru v3.x Python API (mineru.cli.common.do_parse) with model paths
configured via ocr/mineru.json (MINERU_TOOLS_CONFIG_JSON).

Usage:
    from ocr._mineru_ocr import MinerUOCR

    ocr = MinerUOCR.from_config()
    markdown = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_MODELS_PATH = PROJECT_ROOT / "models" / "mineru" / "models"
MINERU_JSON = Path(__file__).resolve().parent / "mineru.json"


def _ensure_mineru_config():
    """Set MINERU_TOOLS_CONFIG_JSON env var so mineru finds its config."""
    if "MINERU_TOOLS_CONFIG_JSON" not in os.environ:
        if MINERU_JSON.exists():
            os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(MINERU_JSON)
            logger.debug(f"MINERU_TOOLS_CONFIG_JSON set to {MINERU_JSON}")


class MinerUOCR:
    """MinerU OCR client using mineru v3.x Python API.

    Model paths are configured via ocr/mineru.json, not passed directly.
    Wiki config (wiki_config.yaml) controls lang/formula/table settings.
    """

    def __init__(
        self,
        models_path: Optional[str] = None,
        backend: str = "pipeline",
        lang: str = "ch",
        formula: bool = True,
        table: bool = True,
    ):
        # models_path is kept for backward compat but not used directly —
        # mineru reads model paths from mineru.json via MINERU_TOOLS_CONFIG_JSON
        self.models_path = Path(models_path) if models_path else DEFAULT_MODELS_PATH
        self.backend = backend
        self.lang = lang
        self.formula = formula
        self.table = table

        # Ensure mineru can find its config
        _ensure_mineru_config()

    @classmethod
    def from_config(cls, path: Optional[Path] = None) -> "MinerUOCR":
        """Create instance from unified OCR config (wiki_config.yaml)."""
        _scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        sys.path.insert(0, str(_scripts_dir))
        from config import get_ocr_config

        mineru_config = get_ocr_config().get("options", {})

        models_path = (
            mineru_config.get("models_path")
            or os.environ.get("MINERU_MODELS_PATH")
            or str(DEFAULT_MODELS_PATH)
        )

        return cls(
            models_path=models_path,
            backend=mineru_config.get("backend", "pipeline"),
            lang=mineru_config.get("lang", "ch"),
            formula=mineru_config.get("formula", True),
            table=mineru_config.get("table", True),
        )

    def ocr_image(self, image_path: str) -> str:
        """Extract text from an image file using MinerU.

        MinerU treats images as single-page PDFs internally via read_fn().

        Args:
            image_path: Path to image file (PNG, JPG, etc.)

        Returns:
            Extracted text in markdown format.
        """
        with tempfile.TemporaryDirectory(prefix="mineru_img_") as tmpdir:
            md_path = self._run_mineru(image_path, Path(tmpdir))
            return Path(md_path).read_text(encoding="utf-8")

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: Optional[int] = None,
    ) -> Path:
        """Extract text from a PDF file using MinerU.

        Args:
            pdf_path: Path to PDF file.
            output_dir: Directory to save results.
            max_pages: Not directly supported by mineru v3 API; processed via
                       environment or config. (Ignored in this version.)

        Returns:
            Path to the output markdown file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        if max_pages is not None:
            logger.warning(
                "max_pages is not directly supported by mineru v3.x API; "
                "all pages will be processed."
            )

        result = self._run_mineru(pdf_path, output_dir, max_pages)
        return Path(result)

    def _run_mineru(
        self,
        input_path: str,
        output_dir: Path,
        max_pages: Optional[int] = None,
    ) -> str:
        """Run MinerU v3.x do_parse() API.

        Sets MINERU_TOOLS_CONFIG_JSON so mineru finds its config with model paths.
        Uses mineru.cli.common.do_parse() for the actual parsing.

        Output structure: {output_dir}/{stem}/{backend}/{stem}.md
        """
        _ensure_mineru_config()

        from mineru.cli.common import do_parse, read_fn

        input_path = Path(input_path)
        stem = input_path.stem

        # read_fn() handles PDF, images, DOCX, PPTX, XLSX — converts to PDF bytes
        try:
            pdf_bytes = read_fn(input_path)
        except Exception as e:
            raise RuntimeError(
                f"MinerU failed to read {input_path}: {e}"
            ) from e

        logger.info(
            "MinerU processing %s (backend=%s, lang=%s, formula=%s, table=%s)",
            input_path.name, self.backend, self.lang, self.formula, self.table,
        )

        try:
            do_parse(
                output_dir=str(output_dir),
                pdf_file_names=[stem],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[self.lang],
                backend=self.backend,
                formula_enable=self.formula,
                table_enable=self.table,
                f_dump_md=True,
                f_dump_middle_json=False,
                f_dump_model_output=False,
                f_dump_orig_pdf=False,
                f_dump_content_list=False,
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
                start_page_id=0,
                end_page_id=max_pages,
            )
        except Exception as e:
            raise RuntimeError(
                f"MinerU do_parse failed for {input_path}: {e}"
            ) from e

        # The output structure is: {output_dir}/{stem}/{backend}/{stem}.md
        md_path = output_dir / stem / self.backend / f"{stem}.md"
        if md_path.exists():
            return str(md_path)

        # Fallback: search for any .md file in the output tree
        md_files = sorted(output_dir.rglob("*.md"))
        if md_files:
            logger.info("Found markdown output: %s", md_files[0])
            return str(md_files[0])

        # Show what was actually produced for debugging
        produced = list(output_dir.rglob("*"))
        raise RuntimeError(
            f"No markdown output found in {output_dir}. "
            f"Produced: {[str(p.relative_to(output_dir)) for p in produced[:20]]}"
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MinerU OCR backend (v3.x)")
    parser.add_argument("file", help="Image or PDF file")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("--models-path", help="Path to MinerU models (for compat, not used)")
    args = parser.parse_args()

    ocr = MinerUOCR()

    if Path(args.file).suffix.lower() == ".pdf":
        output_dir = Path(args.output or f"{Path(args.file).stem}_ocr")
        result = ocr.ocr_pdf(args.file, output_dir)
        print(f"Output: {result}")
    else:
        text = ocr.ocr_image(args.file)
        print(text)
