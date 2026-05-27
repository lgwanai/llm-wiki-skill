#!/usr/bin/env python3
"""_deepseek_ocr2.py — DeepSeek-OCR-2 backend for vision-language OCR.

DeepSeek-OCR-2 is a vision-language model that supports:
- Document OCR with grounding
- Markdown conversion
- Formula recognition
- Multi-modal understanding

Model path configurable via wiki_config.yaml.

Usage:
    from _deepseek_ocr2 import DeepSeekOCR2
    
    ocr = DeepSeekOCR2.from_config()
    markdown = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "deepseek-ocr-v2" / "model"


class DeepSeekOCR2:
    """DeepSeek-OCR-2 client with configurable model path."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "auto",
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self.device = self._detect_device() if device == "auto" else device
        self.api_url = api_url
        self.api_key = api_key
        
        self._model = None
        self._tokenizer = None

    def _detect_device(self) -> str:
        """Detect best available device."""
        try:
            import torch
            if torch.backends.mps.is_available():
                return "mps"
            elif torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    @classmethod
    def from_config(cls, path: Optional[Path] = None) -> "DeepSeekOCR2":
        """Create instance from YAML config (deepseek_ocr section)."""
        config_path = path or CONFIG_PATH
        config = {}
        
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        deepseek_config = config.get("deepseek_ocr", {})
        
        model_path = (
            deepseek_config.get("model_path")
            or os.environ.get("DEEPSEEK_OCR_MODEL_PATH")
            or str(DEFAULT_MODEL_PATH)
        )
        
        return cls(
            model_path=model_path,
            device=deepseek_config.get("device", "auto"),
            api_url=deepseek_config.get("api_url"),
            api_key=deepseek_config.get("api_key"),
        )

    def _init_model(self):
        """Lazy initialization of model."""
        if self._model is not None:
            return
        
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"DeepSeek-OCR-2 model not found at {self.model_path}. "
                f"Please download model or configure model_path in wiki_config.yaml"
            )
        
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
            
            dtype = torch.float16 if self.device == "mps" else torch.bfloat16 if self.device == "cuda" else torch.float32
            attn = "sdpa" if self.device == "mps" else "flash_attention_2"
            
            logger.info(f"Loading DeepSeek-OCR-2 model (device={self.device}, dtype={dtype})")
            
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_path),
                trust_remote_code=True
            )
            self._model = AutoModel.from_pretrained(
                str(self.model_path),
                _attn_implementation=attn,
                trust_remote_code=True,
                use_safetensors=True,
                torch_dtype=dtype
            ).eval()
            
            if self.device == "mps":
                self._model = self._model.to("mps")
            elif self.device == "cuda":
                self._model = self._model.cuda()
            
            logger.info("DeepSeek-OCR-2 model loaded")
            
        except ImportError as e:
            raise RuntimeError(
                f"Required packages not installed: {e}. "
                f"Install with: pip install torch transformers"
            )

    def ocr_image(self, image_path: str, prompt_type: str = "document") -> str:
        """Extract text from an image file.
        
        Args:
            image_path: Path to image file
            prompt_type: 'document' or 'free'
            
        Returns:
            Extracted text in markdown format
        """
        if self.api_url:
            return self._ocr_via_api(image_path)
        
        self._init_model()
        
        try:
            prompt = (
                "<image>\n<|grounding|>Convert the document to markdown."
                if prompt_type == 'document'
                else "<image>\nFree OCR."
            )
            
            result = self._model.infer(
                self._tokenizer,
                prompt=prompt,
                image_file=str(image_path),
                base_size=1024,
                image_size=768,
                crop_mode=True,
                save_results=False
            )
            
            # Clean up result
            result = re.sub(
                r'(<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>)',
                '',
                result.replace('<｜end▁of▁sentence｜>', '')
            ).strip()
            
            return result
            
        except Exception as e:
            logger.error(f"DeepSeek-OCR-2 failed for {image_path}: {e}")
            raise

    def _ocr_via_api(self, image_path: str) -> str:
        """Use API instead of local model."""
        import base64
        import requests
        
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-ocr-2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                        {"type": "text", "text": "Convert the document to markdown."}
                    ]
                }
            ]
        }
        
        response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        return response.json()["choices"][0]["message"]["content"]

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
            import fitz as pymupdf
            
            doc = pymupdf.open(pdf_path)
            pages_to_process = range(min(len(doc), max_pages or len(doc)))
            
            all_text = []
            
            for page_num in pages_to_process:
                page = doc[page_num]
                
                # Render page as image
                pix = page.get_pixmap(dpi=150)
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
    
    parser = argparse.ArgumentParser(description="DeepSeek-OCR-2 backend")
    parser.add_argument("file", help="Image or PDF file")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("--model-path", help="Path to DeepSeek-OCR-2 model")
    parser.add_argument("--device", default="auto", help="Device (mps/cuda/cpu/auto)")
    args = parser.parse_args()
    
    ocr = DeepSeekOCR2(model_path=args.model_path, device=args.device)
    
    if Path(args.file).suffix.lower() == ".pdf":
        output_dir = Path(args.output or f"{args.file}_ocr")
        result = ocr.ocr_pdf(args.file, output_dir)
        print(f"Output: {result}")
    else:
        text = ocr.ocr_image(args.file)
        print(text)