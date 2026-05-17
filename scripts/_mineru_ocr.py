from __future__ import annotations
"""_mineru_ocr.py — MinerU OCR client for high-precision PDF/image parsing.

MinerU (https://github.com/opendatalab/MinerU) is a state-of-the-art document
parsing engine that converts PDF, DOCX, PPTX, XLSX, and images into structured
Markdown/JSON. It supports:

- Formula → LaTeX (not just images)
- Table → HTML with accurate structure
- Multi-column layout reconstruction
- Automatic header/footer removal
- Cross-page table merging
- 109 languages via VLM + OCR dual engine
- Pipeline backend for CPU-only operation (~4GB RAM)

The pipeline backend runs on CPU (no GPU required) with 85+ accuracy on
OmniDocBench v1.6. For higher precision, vlm-auto-engine requires GPU.

Configuration: see ../wiki_config.yaml (mineru section).

Usage:
    from _mineru_ocr import MinerUOCR

    ocr = MinerUOCR.from_config()
    markdown = ocr.ocr_pdf("document.pdf", Path("results/"))
    text = ocr.ocr_image("screenshot.png")
"""

import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"

# ── Supported formats ──────────────────────────────────────────────────────

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
ALL_SUPPORTED = PDF_EXTS | IMAGE_EXTS | OFFICE_EXTS

# MinerU output directory: <output_dir>/<stem>/<stem>.md
# e.g., mineru -p doc.pdf -o out/ → out/doc/doc.md


class MinerUOCR:
    """MinerU OCR client wrapping the CLI with subprocess."""

    def __init__(
        self,
        backend: str = "pipeline",
        lang: str = "ch",
        method: str = "auto",
        formula: bool = True,
        table: bool = True,
        start_page: int | None = None,
        end_page: int | None = None,
        timeout: int = 600,
    ):
        self.backend = backend
        self.lang = lang
        self.method = method
        self.formula = formula
        self.table = table
        self.start_page = start_page
        self.end_page = end_page
        self.timeout = timeout
        self._check_cli()

    @staticmethod
    def _check_cli() -> None:
        """Verify mineru CLI is available."""
        if not shutil.which("mineru"):
            raise RuntimeError(
                "MinerU CLI not found. Install with:\n"
                "  uv pip install -U 'mineru[all]'"
            )

    @classmethod
    def from_config(cls, path: Path | None = None) -> "MinerUOCR":
        """Create instance from YAML config (mineru section)."""
        config_path = path or CONFIG_PATH
        cfg: dict = {}
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            cfg = config.get("mineru", {})

        return cls(
            backend=cfg.get("backend", "pipeline"),
            lang=cfg.get("lang", "ch"),
            method=cfg.get("method", "auto"),
            formula=cfg.get("formula", True),
            table=cfg.get("table", True),
            start_page=cfg.get("start_page"),
            end_page=cfg.get("end_page"),
            timeout=cfg.get("timeout", 600),
        )

    # ── CLI call ──────────────────────────────────────────────────────────

    def _build_args(self, input_path: str, output_dir: Path) -> list[str]:
        """Build mineru CLI arguments."""
        args = [
            "mineru",
            "-p", input_path,
            "-o", str(output_dir),
            "-b", self.backend,
            "-m", self.method,
            "-l", self.lang,
        ]
        if not self.formula:
            args.extend(["-f", "false"])
        if not self.table:
            args.extend(["-t", "false"])
        if self.start_page is not None:
            args.extend(["-s", str(self.start_page)])
        return args

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run mineru CLI and handle errors."""
        logger.info(f"MinerU: {' '.join(shlex.quote(a) for a in args)}")
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error(f"MinerU failed (exit {result.returncode}): {stderr}")
            raise RuntimeError(f"MinerU failed: {stderr}")
        return result

    def _find_main_output(self, output_dir: Path, input_basename: str) -> Path | None:
        """Find the main markdown output from MinerU's output directory.

        MinerU output structure varies by method:
          pipeline (auto method):
            output_dir/<input_stem>/auto/<input_stem>.md
          hybrid/vlm:
            output_dir/<input_stem>/<input_stem>.md
        Also creates _model.json, _middle.json, _content_list.json, _layout.pdf, _span.pdf, images/.
        """
        stem = Path(input_basename).stem

        patterns = [
            output_dir / stem / f"{stem}.md",           # direct
            output_dir / stem / "auto" / f"{stem}.md",  # auto method
            output_dir / stem / "txt" / f"{stem}.md",    # txt method
            output_dir / stem / "ocr" / f"{stem}.md",    # ocr method
        ]
        for candidate in patterns:
            if candidate.exists():
                return candidate

        for md_file in sorted(output_dir.rglob("*.md")):
            if md_file.name != "README.md":
                return md_file

        return None

    # ── public API ─────────────────────────────────────────────────────────

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: int | None = None,
    ) -> Path:
        """OCR a PDF using MinerU pipeline backend.

        Returns path to the output markdown file.

        Args:
            pdf_path: Path to PDF file.
            output_dir: Directory for MinerU output.
            max_pages: Maximum pages (sets --end-page if provided).
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info(f"MinerU OCR: {pdf_path}")
        logger.info(f"Backend: {self.backend} | Lang: {self.lang} | Method: {self.method}")
        logger.info(f"Output: {output_dir}")
        logger.info("=" * 60)

        args = self._build_args(pdf_path, output_dir)
        if max_pages is not None:
            args.extend(["-e", str(max_pages - 1)])

        self._run(args)

        main_output = self._find_main_output(output_dir, pdf_path)
        if main_output is None:
            # MinerU may output differently. Search for markdown files.
            md_files = list(output_dir.rglob("*.md"))
            if md_files:
                main_output = md_files[0]
            else:
                raise RuntimeError(
                    f"No markdown output found in {output_dir}. "
                    f"Contents: {list(output_dir.iterdir())}"
                )

        logger.info(f"Output: {main_output} ({main_output.stat().st_size} bytes)")
        return main_output

    def ocr_image(self, filepath: str) -> str:
        """OCR a single image file. Returns markdown text.

        MinerU processes images through the same pipeline as PDF pages.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            args = self._build_args(filepath, output_dir)
            self._run(args)

            main_output = self._find_main_output(output_dir, filepath)
            if main_output and main_output.exists():
                return main_output.read_text(encoding="utf-8")
            raise RuntimeError(f"No markdown output for {filepath}")

    def ocr_document(self, filepath: str, output_dir: Path) -> Path:
        """OCR any supported document (PDF, DOCX, PPTX, XLSX, image).

        This delegates to the full MinerU pipeline which handles all formats
        natively. Returns path to output markdown.
        """
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in ALL_SUPPORTED:
            raise ValueError(
                f"Unsupported format: {ext}. "
                f"Supported: {', '.join(sorted(ALL_SUPPORTED))}"
            )
        return self.ocr_pdf(filepath, output_dir)
