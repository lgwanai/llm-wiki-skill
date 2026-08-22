#!/usr/bin/env python3
"""_logics_parsing.py — Logics-Parsing-v2 backend for OCR.

Logics-Parsing-v2 is based on Qwen3VL and supports:
- PDF to HTML/Markdown conversion
- Multi-modal document understanding
- Table recognition
- Formula parsing

Model path configurable via wiki_config.yaml.

Usage:
    from _logics_parsing import LogicsParsingOCR
    
    ocr = LogicsParsingOCR.from_config()
    markdown = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "logics-parsing-v2" / "model"


class LogicsParsingOCR:
    """Logics-Parsing-v2 client with configurable model path."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "auto",
        prompt_mode: str = "markdown",
    ):
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self.device = self._detect_device() if device == "auto" else device
        self.prompt_mode = prompt_mode
        
        self._model = None
        self._processor = None

    def _detect_device(self) -> str:
        """Detect best available device."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda:0"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    @classmethod
    def from_config(cls, path: Optional[Path] = None) -> "LogicsParsingOCR":
        """Create instance from standalone OCR config."""
        from ocr.config import get_model_config

        logics_config = get_model_config("logics", path).get("options", {})
        
        model_path = (
            logics_config.get("model_path")
            or os.environ.get("LOGICS_PARSING_MODEL_PATH")
            or str(DEFAULT_MODEL_PATH)
        )
        
        return cls(
            model_path=model_path,
            device=logics_config.get("device", "auto"),
            prompt_mode=logics_config.get("prompt_mode", "markdown"),
        )

    def _init_model(self):
        """Lazy initialization of model."""
        if self._model is not None:
            return
        
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Logics-Parsing-v2 model not found at {self.model_path}. "
                f"Please download model or configure model_path in wiki_config.yaml"
            )
        
        try:
            import torch
            from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
            
            attn_impl = "eager"
            if self.device == "cuda:0":
                try:
                    import flash_attn
                    attn_impl = "flash_attention_2"
                except ImportError:
                    pass
            
            logger.info(f"Loading Logics-Parsing-v2 model (device={self.device})")
            
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                str(self.model_path),
                torch_dtype="auto",
                attn_implementation=attn_impl,
                device_map=self.device,
            )
            
            self._processor = AutoProcessor.from_pretrained(
                str(self.model_path),
                trust_remote_code=True
            )
            
            logger.info("Logics-Parsing-v2 model loaded")
            
        except ImportError as e:
            raise RuntimeError(
                f"Required packages not installed: {e}. "
                f"Install with: pip install torch transformers"
            )

    def ocr_image(self, image_path: str) -> str:
        """Extract text from an image file.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Extracted text in markdown format
        """
        self._init_model()
        
        try:
            prompts = {
                "markdown": "Convert this document to clean markdown format.",
                "html": "Convert this document to HTML format.",
                "text": "Extract all text from this document.",
            }
            
            prompt = prompts.get(self.prompt_mode, prompts["markdown"])
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_path},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            
            inputs = self._processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs = inputs.to(self._model.device)
            
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=16384,
                temperature=0.1,
                top_p=0.5,
                repetition_penalty=1.05
            )
            
            generated_ids_trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            
            output_text = self._processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )
            
            return output_text[0].strip()
            
        except Exception as e:
            logger.error(f"Logics-Parsing failed for {image_path}: {e}")
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
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            import fitz
            
            doc = fitz.open(pdf_path)
            pages_to_process = range(min(len(doc), max_pages or len(doc)))
            
            all_text = []
            
            for page_num in pages_to_process:
                page = doc[page_num]
                
                # Render page as image
                mat = fitz.Matrix(200 / 72, 200 / 72)
                pix = page.get_pixmap(matrix=mat)
                
                temp_img = output_dir / f"page_{page_num}.png"
                pix.save(str(temp_img))
                
                # OCR the page
                text = self.ocr_image(str(temp_img))
                all_text.append(f"## Page {page_num + 1}\n\n{text}")
                
                # Clean up temp file
                temp_img.unlink()
            
            doc.close()
            
            output_file = output_dir / f"{Path(pdf_path).stem}.md"
            output_file.write_text("\n\n".join(all_text), encoding="utf-8")
            
            return output_file
            
        except ImportError:
            raise RuntimeError(
                "PyMuPDF not installed. Install with: pip install pymupdf"
            )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Logics-Parsing-v2 backend")
    parser.add_argument("file", help="Image or PDF file")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("--model-path", help="Path to Logics-Parsing-v2 model")
    parser.add_argument("--device", default="auto", help="Device (mps/cuda/cpu/auto)")
    args = parser.parse_args()
    
    ocr = LogicsParsingOCR(model_path=args.model_path, device=args.device)
    
    if Path(args.file).suffix.lower() == ".pdf":
        output_dir = Path(args.output or f"{args.file}_ocr")
        result = ocr.ocr_pdf(args.file, output_dir)
        print(f"Output: {result}")
    else:
        text = ocr.ocr_image(args.file)
        print(text)
