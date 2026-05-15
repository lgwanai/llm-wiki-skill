from __future__ import annotations
"""_deepseek_ocr.py — DeepSeek-OCR client with image extraction pipeline.

Two-pass per page:
  1. Grounding mode — detect images/charts/figures with bounding boxes
  2. Text mode — extract text content as markdown
  3. Merge — insert cropped image references at correct Y-coordinate positions

Coordinate system: 999×999 model space → pixel space.
Configuration: see ocr_config.yaml

Usage:
    from _deepseek_ocr import DeepSeekOCR

    ocr = DeepSeekOCR.from_config()
    markdown = ocr.ocr_image("screenshot.png")
    report = ocr.ocr_pdf("document.pdf", Path("results/"))
"""

import base64
import io
import logging
import os
import re
import time
from pathlib import Path

import fitz
import requests
import yaml
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MODEL_SIZE = 999
CONFIG_PATH = Path(__file__).parent / "wiki_config.yaml"

GROUNDING_PROMPT = "<|grounding|>识别图片中所有元素，标注准确位置坐标。"
OCR_PROMPT = "识别图片中的所有文字内容，数学公式用LaTeX格式输出。"

IMAGE_TYPES = {"image", "chart", "figure", "table", "diagram", "graph", "plot"}
FORMULA_TYPES = {"interline_equation", "equation", "formula", "inline_equation", "math"}


class DeepSeekOCR:
    """DeepSeek-OCR client with image extraction and markdown generation."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        pdf_dpi: int = 150,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.pdf_dpi = pdf_dpi

    @classmethod
    def from_config(cls, path: Path | None = None) -> "DeepSeekOCR":
        """Create instance from YAML config (ocr section) or environment variables."""
        config_path = path or CONFIG_PATH
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            ocr = config.get("ocr", {})
        else:
            ocr = {}

        return cls(
            api_url=ocr.get("api_url") or os.environ.get("OCR_API_URL", ""),
            api_key=ocr.get("api_key") or os.environ.get("OCR_API_KEY", ""),
            model=ocr.get("model") or os.environ.get("OCR_MODEL", "DeepSeek-OCR-4bit"),
            pdf_dpi=ocr.get("pdf_dpi", 150),
        )

    # ── API ──────────────────────────────────────────────────────────

    def _call_api(
        self,
        img_base64: str,
        prompt: str,
        mime: str = "image/jpeg",
        max_tokens: int = 16384,
        timeout: int = 180,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "top_p": 1.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{img_base64}"},
                        },
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    # ── image helpers ────────────────────────────────────────────────

    def _pdf_page_to_pil(self, pdf_path: str, page_num: int):
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=self.pdf_dpi)
        img_bytes = pix.tobytes("jpeg")
        pil_image = Image.open(io.BytesIO(img_bytes))
        w, h = pix.width, pix.height
        doc.close()
        return pil_image, w, h

    def _pil_to_base64(self, pil_image: Image.Image, quality: int = 95) -> str:
        buf = io.BytesIO()
        pil_image.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _file_to_base64(self, filepath: str) -> str:
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    # ── coordinate mapping ───────────────────────────────────────────

    @staticmethod
    def _map_coord(coord: int, orig_size: int) -> int:
        return int(coord * orig_size / MODEL_SIZE)

    # ── grounding parsing ────────────────────────────────────────────

    def _parse_grounding(self, text: str, img_w: int, img_h: int) -> list[dict]:
        pattern = r"<\|ref\|>([^<]+)<\|/ref\|><\|det\|>\[\[([^\]]+)\]\]<\|/det\|>"
        matches = re.findall(pattern, text)
        items = []
        for elem_type, coords_str in matches:
            try:
                coords = [int(float(x)) for x in coords_str.split(",")]
                if len(coords) != 4:
                    continue
                x1 = self._map_coord(coords[0], img_w)
                y1 = self._map_coord(coords[1], img_h)
                x2 = self._map_coord(coords[2], img_w)
                y2 = self._map_coord(coords[3], img_h)
                items.append(
                    {
                        "type": elem_type.strip().lower(),
                        "model_bbox": coords,
                        "pixel_bbox": [x1, y1, x2, y2],
                        "y_center": (y1 + y2) // 2,
                        "is_image": elem_type.strip().lower() in IMAGE_TYPES,
                        "is_formula": elem_type.strip().lower() in FORMULA_TYPES,
                    }
                )
            except (ValueError, IndexError):
                continue
        return sorted(items, key=lambda x: x["y_center"])

    # ── image cropping ───────────────────────────────────────────────

    def _crop_and_save(
        self, pil_image: Image.Image, bbox: list[int], output_path: Path,
        is_formula: bool = False,
    ) -> bool:
        x1, y1, x2, y2 = bbox
        padding = 10 if is_formula else 5
        x1 = max(0, x1 - padding)
        y1 = max(0, y1 - padding)
        x2 = min(pil_image.width, x2 + padding)
        y2 = min(pil_image.height, y2 + padding)
        if x2 <= x1 or y2 <= y1:
            return False

        cropped = pil_image.crop((x1, y1, x2, y2))
        if not is_formula:
            pixels = list(cropped.getdata())
            white_count = sum(1 for p in pixels if p[0] > 240 and p[1] > 240 and p[2] > 240)
            if white_count / len(pixels) > 0.9:
                return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path, "JPEG", quality=92)
        return True

    # ── markdown merging ─────────────────────────────────────────────

    @staticmethod
    def _insert_images(
        markdown_text: str, image_items: list[dict], page_h: int, page_num: int
    ) -> str:
        if not image_items:
            return markdown_text

        paragraphs = markdown_text.split("\n\n")
        for item in image_items:
            if "crop_filename" not in item:
                continue
            relative_pos = item["y_center"] / page_h
            target = min(int(relative_pos * len(paragraphs)), len(paragraphs) - 1)
            img_ref = (
                f"\n\n![{item['type']}](page_{page_num}/{item['crop_filename']})\n\n"
            )
            paragraphs[target] += img_ref

        return "\n\n".join(paragraphs)

    # ── post-processing ──────────────────────────────────────────────

    @staticmethod
    def _clean_grounding_markers(text: str) -> str:
        """Remove grounding markers from text output."""
        if not text:
            return ""
        text = re.sub(r"<\|ref\|>[^<]*<\|/ref\|>", "", text)
        text = re.sub(r"<\|det\|>\[\[[^\]]*\]\]<\|/det\|>", "", text)
        text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
        return text.strip()

    @staticmethod
    def _convert_latex_format(text: str) -> str:
        """Convert LaTeX formula delimiters to Markdown math format."""
        if not text:
            return ""
        text = re.sub(r"\\\[\s*", "$$", text)
        text = re.sub(r"\s*\\\]", "$$", text)
        text = re.sub(r"\\\(\s*", "$", text)
        text = re.sub(r"\s*\\\)", "$", text)
        return text

    # ── single-page pipeline ─────────────────────────────────────────

    def _process_page(self, pdf_path: str, page_num: int, output_dir: Path) -> dict:
        pil_image, img_w, img_h = self._pdf_page_to_pil(pdf_path, page_num)
        img_base64 = self._pil_to_base64(pil_image)

        grounding_text = self._call_api(img_base64, GROUNDING_PROMPT)
        items = self._parse_grounding(grounding_text, img_w, img_h)
        image_items = [i for i in items if i["is_image"]]
        formula_items = [i for i in items if i["is_formula"]]

        page_dir = output_dir / f"page_{page_num + 1}"
        for idx, item in enumerate(items, 1):
            if item["is_formula"]:
                filename = f"formula_{idx:03d}.jpg"
            elif item["is_image"]:
                filename = f"img_{idx:03d}_{item['type']}.jpg"
            else:
                continue
            if self._crop_and_save(pil_image, item["pixel_bbox"], page_dir / filename, item["is_formula"]):
                item["crop_filename"] = filename

        markdown_text = self._call_api(img_base64, OCR_PROMPT)
        markdown_text = self._clean_grounding_markers(markdown_text)
        markdown_text = self._convert_latex_format(markdown_text)

        # Insert image references; formulas are already in the text via OCR
        elements_to_insert = [i for i in items if "crop_filename" in i and not i["is_formula"]]
        if elements_to_insert:
            markdown_text = self._insert_images(
                markdown_text, elements_to_insert, img_h, page_num + 1
            )

        return {
            "page": page_num + 1,
            "markdown": markdown_text,
            "image_items": image_items,
            "formula_items": formula_items,
            "total_items": len(items),
        }

    # ── public API ───────────────────────────────────────────────────

    def ocr_pdf(self, pdf_path: str, output_dir: Path, max_pages: int | None = None) -> Path:
        """OCR a PDF with full pipeline: grounding + text + image extraction → markdown.

        Returns path to output.md.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        total_pages = min(len(doc), max_pages) if max_pages else len(doc)

        logger.info("=" * 60)
        logger.info(f"DeepSeek-OCR: {pdf_path}")
        logger.info(f"总页数: {doc.page_count}, 处理: {total_pages}")
        logger.info(f"输出: {output_dir}/")
        logger.info("=" * 60)

        results = []
        start_time = time.time()

        for page_num in range(total_pages):
            try:
                logger.info(f"\n处理第 {page_num + 1}/{total_pages} 页...")
                result = self._process_page(pdf_path, page_num, output_dir)
                results.append(result)
                logger.info(
                    f"  元素: {result['total_items']} "
                    f"(图片: {len(result['image_items'])}, "
                    f"公式: {len(result.get('formula_items', []))}), "
                    f"文本: {len(result['markdown'])} 字符"
                )
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"处理第 {page_num + 1} 页失败: {e}")

        md = "".join(r["markdown"] + "\n\n" for r in results)
        report_path = output_dir / "output.md"
        report_path.write_text(md, encoding="utf-8")

        elapsed = time.time() - start_time
        total_images = sum(len(r["image_items"]) for r in results)
        total_text = sum(len(r["markdown"]) for r in results)

        logger.info("\n" + "=" * 60)
        logger.info("完成！")
        logger.info(f"页数: {len(results)} | 图片: {total_images} | 文本: {total_text} 字符 | 耗时: {elapsed:.1f}s")
        logger.info(f"输出: {report_path}")
        logger.info("=" * 60)

        return report_path

    def ocr_image(self, filepath: str) -> str:
        """OCR a single image file. Returns markdown text."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        img_base64 = self._file_to_base64(filepath)
        return self._call_api(img_base64, OCR_PROMPT)

    def _ocr_pdf_text(self, pdf_path: str, max_pages: int | None = None) -> str:
        """OCR PDF pages as plain text (no image extraction). Internal use."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        doc = fitz.open(pdf_path)
        total_pages = min(len(doc), max_pages) if max_pages else len(doc)
        pages_text = []
        for page_num in range(total_pages):
            pil_image, _, _ = self._pdf_page_to_pil(pdf_path, page_num)
            img_base64 = self._pil_to_base64(pil_image)
            try:
                text = self._call_api(img_base64, OCR_PROMPT)
                pages_text.append(f"## Page {page_num + 1}\n\n{text}")
            except Exception as e:
                pages_text.append(f"## Page {page_num + 1}\n\n[Error: {e}]")
        return "\n\n".join(pages_text)
