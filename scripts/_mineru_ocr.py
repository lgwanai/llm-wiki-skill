#!/usr/bin/env python3
"""_mineru_ocr.py — MinerU OCR backend for PDF-Extract-Kit.

MinerU is a high-precision PDF parsing tool that supports:
- Formula → LaTeX conversion
- Table → HTML conversion  
- Multi-column layout detection
- Header/footer removal

Model paths are configurable via wiki_config.yaml or environment variables.

Usage:
    from _mineru_ocr import MinerUOCR
    
    ocr = MinerUOCR.from_config()
    markdown = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_MODELS_PATH = PROJECT_ROOT / "models" / "mineru" / "models"


class MinerUOCR:
    """MinerU OCR client with configurable model paths."""

    def __init__(
        self,
        models_path: Optional[str] = None,
        backend: str = "pipeline",
        lang: str = "ch",
        formula: bool = True,
        table: bool = True,
    ):
        self.models_path = Path(models_path) if models_path else DEFAULT_MODELS_PATH
        self.backend = backend
        self.lang = lang
        self.formula = formula
        self.table = table
        
        if not self.models_path.exists():
            raise FileNotFoundError(
                f"MinerU models not found at {self.models_path}. "
                f"Please download models or configure models_path in wiki_config.yaml"
            )

    @classmethod
    def from_config(cls, path: Optional[Path] = None) -> "MinerUOCR":
        """Create instance from unified OCR config."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
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
        """Extract text from an image file.
        
        Args:
            image_path: Path to image file (PNG, JPG, etc.)
            
        Returns:
            Extracted text in markdown format
        """
        try:
            result = self._run_mineru(image_path)
            return result
        except Exception as e:
            logger.error(f"MinerU OCR failed for {image_path}: {e}")
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
            max_pages: Maximum pages to process (None = all)
            
        Returns:
            Path to the output markdown file
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            result = self._run_mineru(pdf_path, output_dir, max_pages)
            return Path(result)
        except Exception as e:
            logger.error(f"MinerU OCR failed for {pdf_path}: {e}")
            raise

    def _run_mineru(
        self, 
        input_path: str, 
        output_dir: Optional[Path] = None,
        max_pages: Optional[int] = None
    ) -> str:
        """Run MinerU via subprocess or direct API call.
        
        This method tries multiple approaches:
        1. Direct API call to mineru library (if installed)
        2. Subprocess call to mineru CLI
        3. Fallback to basic PDF extraction
        """
        try:
            import magic_pdf.model as model_init
            from magic_pdf.pipe.UNIPipe import UNIPipe
            
            model_init.init(
                model_path=str(self.models_path),
                config=None,
                device="cpu"
            )
            
            with open(input_path, "rb") as f:
                pdf_bytes = f.read()
            
            pipe = UNIPipe(pdf_bytes, model_init.jso_useful_key)
            pipe.pipe_classify()
            pipe.pipe_parse()
            
            content_list = pipe.pipe_mk_mkdown()
            markdown_text = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content_list
            )
            
            if output_dir:
                output_file = output_dir / f"{Path(input_path).stem}.md"
                output_file.write_text(markdown_text, encoding="utf-8")
                return str(output_file)
            
            return markdown_text
            
        except ImportError:
            logger.warning("MinerU library not installed, trying CLI")
            return self._run_mineru_cli(input_path, output_dir, max_pages)

    def _run_mineru_cli(
        self,
        input_path: str,
        output_dir: Optional[Path] = None,
        max_pages: Optional[int] = None
    ) -> str:
        """Run MinerU via CLI subprocess."""
        cmd = [
            sys.executable, "-m", "magic_pdf.cli",
            "--path", input_path,
            "--model_path", str(self.models_path),
        ]
        
        if output_dir:
            cmd.extend(["--output_dir", str(output_dir)])
        
        env = os.environ.copy()
        env["MINERU_MODEL_PATH"] = str(self.models_path)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=300
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"MinerU CLI failed: {result.stderr}")
            
            if output_dir:
                output_file = output_dir / f"{Path(input_path).stem}.md"
                if output_file.exists():
                    return str(output_file)
            
            return result.stdout
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("MinerU CLI timeout")
        except FileNotFoundError:
            raise RuntimeError(
                "MinerU not installed. Install with: pip install mineru"
            )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MinerU OCR backend")
    parser.add_argument("file", help="Image or PDF file")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("--models-path", help="Path to MinerU models")
    args = parser.parse_args()
    
    ocr = MinerUOCR(models_path=args.models_path)
    
    if Path(args.file).suffix.lower() == ".pdf":
        output_dir = Path(args.output or f"{args.file}_ocr")
        result = ocr.ocr_pdf(args.file, output_dir)
        print(f"Output: {result}")
    else:
        text = ocr.ocr_image(args.file)
        print(text)
