#!/usr/bin/env python3
"""_ocr_api.py — Generic API OCR backend using OpenAI-compatible vision API.

Sends base64-encoded images to any OpenAI-compatible /v1/chat/completions
endpoint with image_url content type. Supports any vision-language model
that implements the standard format (GPT-4o, DeepSeek-VL2, Qwen-VL, etc.).

Usage:
    from _ocr_api import OCRApiBackend

    ocr = OCRApiBackend.from_config()
    markdown = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

from __future__ import annotations

import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# MIME type mapping for common image formats
_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".svg": "image/svg+xml",
}

DEFAULT_PROMPT = "Convert the document to clean markdown format."
DEFAULT_DPI = 150

# Provider presets — auto-resolve api_url, model, and prompt
_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "siliconflow": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "default_model": "deepseek-ai/DeepSeek-OCR",
        "default_prompt": "<image>\n<|grounding|>OCR this image.",
    },
    "deepseek": {
        "api_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-ocr-2",
        "default_prompt": "<image>\nConvert the document to markdown.",
    },
    "paddleocr-vl": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "default_model": "PaddlePaddle/PaddleOCR-VL-1.5",
        "default_prompt": "<image>\nOCR this image.",
    },
    "openai": {
        "api_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o",
        "default_prompt": "Convert the document to clean markdown format.",
    },
}


def create_vision_backend(settings: dict, default_prompt: str = DEFAULT_PROMPT) -> "OCRApiBackend":
    """Create an OpenAI-compatible vision backend from compact settings."""
    provider = settings.get("api_provider", "") or settings.get("provider", "")
    preset: dict[str, str] = {}
    if provider and provider in _PROVIDER_PRESETS:
        preset = _PROVIDER_PRESETS[provider]

    api_url = settings.get("api_url", "") or preset.get("api_url", "")
    if not api_url:
        raise RuntimeError(
            "Vision API requires api_url or api_provider in wiki_config.yaml."
        )

    api_key = settings.get("api_key", "")
    if not api_key:
        api_key = os.environ.get("OCR_API_KEY", "")
    if not api_key:
        api_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    api_model = (
        settings.get("api_model", "")
        or settings.get("model", "")
        or preset.get("default_model", "")
    )

    api_prompt = settings.get("api_prompt", "") or settings.get("prompt", "")
    if not api_prompt:
        api_prompt = preset.get("default_prompt", default_prompt)

    return OCRApiBackend(
        api_url=api_url,
        api_key=api_key,
        model=api_model,
        prompt=api_prompt,
        pdf_dpi=settings.get("pdf_dpi", DEFAULT_DPI),
    )


def _expand_env(value: str) -> str:
    """Expand ${VAR} environment variables in a string."""
    import re

    pattern = re.compile(r"\$\{(\w+)\}")

    def _replace(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return pattern.sub(_replace, value)


class OCRApiBackend:
    """Generic API OCR backend using OpenAI-compatible vision API."""

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        model: str = "",
        prompt: str = "",
        pdf_dpi: int = DEFAULT_DPI,
    ):
        if not api_url:
            raise ValueError("api_url is required for OCR API backend")

        self.api_url = api_url.rstrip("/")
        self.api_key = _expand_env(api_key) if api_key else api_key
        self.model = model or "gpt-4o"
        self.prompt = prompt or DEFAULT_PROMPT
        self.pdf_dpi = pdf_dpi

    @classmethod
    def from_config(cls, config_path: Optional[Path] = None) -> "OCRApiBackend":
        """Create instance from wiki_config.yaml.

        Reads the unified 'ocr' config section for API settings.

        Args:
            config_path: Optional path to config file.

        Returns:
            Configured OCRApiBackend instance.

        Raises:
            RuntimeError: If mode is 'api' but api_url is not configured.
        """
        from scripts.config import get_ocr_config

        ocr_config = get_ocr_config()

        try:
            return create_vision_backend(ocr_config, DEFAULT_PROMPT)
        except RuntimeError as e:
            raise RuntimeError(
                "OCR API mode requires api_url or api_provider to be configured in wiki_config.yaml.\n"
                "Example:\n"
                "  ocr:\n"
                "    mode: api\n"
                '    api_provider: siliconflow\n'
                '    api_key: "${SILICONFLOW_API_KEY}"\n'
            ) from e

    def ocr_image(self, image_path: str) -> str:
        """OCR a single image via the vision API.

        Args:
            image_path: Path to image file (.png, .jpg, etc.)

        Returns:
            Extracted text in markdown format.
        """
        import requests

        image_path_obj = Path(image_path)
        if not image_path_obj.is_file():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Detect MIME type from extension
        ext = image_path_obj.suffix.lower()
        mime = _MIME_TYPES.get(ext, "image/png")

        # Base64 encode
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("ascii")

        headers = {
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Content-Type": "application/json",
        }
        if not self.api_key:
            del headers["Authorization"]

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_data}",
                            },
                        },
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ],
            "max_tokens": 16384,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()

            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError(f"OCR API returned no choices: {data}")

            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise RuntimeError("OCR API returned empty content")

            return content.strip()

        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"OCR API timed out for {image_path} (180s). "
                "Try a smaller image or check the API server."
            )
        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                pass
            raise RuntimeError(
                f"OCR API HTTP {e.response.status_code if e.response else '?'}: {error_body}"
            )
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"OCR API connection failed: {e}\n"
                f"Check api_url: {self.api_url}"
            )
        except Exception as e:
            if "OCR API" in str(e):
                raise
            raise RuntimeError(f"OCR API error: {e}")

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: Optional[int] = None,
    ) -> Path:
        """Extract text from a PDF file via the vision API.

        Renders each page as a PNG image, sends to the API, and combines
        results into a markdown file.

        Args:
            pdf_path: Path to PDF file.
            output_dir: Directory to save results (and temp page images).
            max_pages: Maximum pages to process.

        Returns:
            Path to the generated markdown file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            import fitz as pymupdf  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "PyMuPDF is required for PDF OCR. Install with: pip install pymupdf"
            )

        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        pages_to_process = range(min(total_pages, max_pages or total_pages))

        if max_pages and max_pages < total_pages:
            print(
                f"Processing {max_pages} of {total_pages} pages...",
                file=sys.stderr,
            )
        else:
            print(f"Processing {total_pages} pages...", file=sys.stderr)

        all_text: list[str] = []

        for page_num in pages_to_process:
            page = doc[page_num]

            # Render page as image
            pix = page.get_pixmap(dpi=self.pdf_dpi)
            temp_img = output_dir / f"_page_{page_num:04d}.png"
            pix.save(str(temp_img))

            print(
                f"  Page {page_num + 1}/{total_pages} → OCR via API...",
                file=sys.stderr,
            )

            # OCR the page image
            text = self.ocr_image(str(temp_img))
            all_text.append(f"## Page {page_num + 1}\n\n{text}")

            # Clean up temp image
            temp_img.unlink()

            # Rate limit: small delay between pages to avoid API throttling
            if page_num < pages_to_process[-1]:
                time.sleep(0.3)

        doc.close()

        # Write combined markdown
        output_file = output_dir / f"{Path(pdf_path).stem}.md"
        output_file.write_text("\n\n".join(all_text), encoding="utf-8")

        print(f"✓ Output: {output_file}", file=sys.stderr)
        return output_file


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="OCR via OpenAI-compatible vision API"
    )
    parser.add_argument("file", help="Image or PDF file")
    parser.add_argument(
        "-o", "--output", help="Output directory for PDF results"
    )
    parser.add_argument(
        "--api-url",
        help="API endpoint URL (or set in wiki_config.yaml)",
    )
    parser.add_argument(
        "--api-key",
        help="API key (or set in wiki_config.yaml)",
    )
    parser.add_argument(
        "--model",
        help="Model name (or set in wiki_config.yaml)",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="OCR prompt for the vision model",
    )
    args = parser.parse_args()

    if args.api_url:
        ocr = OCRApiBackend(
            api_url=args.api_url,
            api_key=args.api_key or "",
            model=args.model or "",
            prompt=args.prompt,
        )
    else:
        ocr = OCRApiBackend.from_config()

    file_path = Path(args.file)
    if file_path.suffix.lower() == ".pdf":
        output_dir = Path(args.output) if args.output else Path("ocr_output")
        ocr.ocr_pdf(str(file_path), output_dir)
    else:
        result = ocr.ocr_image(str(file_path))
        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"✓ Output: {args.output}", file=sys.stderr)
        else:
            print(result)
