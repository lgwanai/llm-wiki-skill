#!/usr/bin/env python3
"""ocr.py — Image & PDF OCR with pluggable backends.

Backends:
    mineru  (default): MinerU — high-precision parsing, formula→LaTeX, table→HTML, CPU OK.
    deepseek:          DeepSeek-OCR-2 — Vision-Language OCR, GPU/MPS/CPU.
    logics:            Logics-Parsing-v2 — Qwen3VL-based OCR, GPU/MPS/CPU.
    paddle:            PaddleOCR — PP-OCRv5, 109 languages, doc unwarping.
    api:               Generic API — OpenAI-compatible vision API (GPT-4o, DeepSeek-VL2, etc.)

Usage:
    python ocr.py document.pdf                        # Default: MinerU (local)
    python ocr.py document.pdf --backend deepseek     # DeepSeek-OCR-2
    python ocr.py document.pdf --backend api          # Vision API
    python ocr.py document.pdf -o results/            # Output directory
    python ocr.py --batch screenshots/                # Batch process
"""

import argparse
import json
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))
_scripts_dir = _project_root / "scripts"
sys.path.insert(0, str(_scripts_dir))
from config import get_ocr_config


_SOURCE_LIKE_SUFFIXES = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp",
}


def _get_default_backend() -> str:
    """Read OCR config and return backend name (or 'api' for API mode)."""
    ocr_config = get_ocr_config()
    mode = ocr_config.get("mode", "local")
    if mode == "api":
        return "api"
    return ocr_config.get("backend", "mineru")


def resolve_output_dir(input_path: str | Path, requested: str | None, default: str | Path) -> Path:
    """Resolve and validate an OCR output directory without touching the input."""
    source = Path(input_path).expanduser()
    output_dir = Path(requested).expanduser() if requested else Path(default)

    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"OCR output must be a directory, not a file: {output_dir}")

    if requested and output_dir.suffix.lower() in _SOURCE_LIKE_SUFFIXES:
        raise ValueError(
            f"OCR output must be a directory, not a source-like file path: {output_dir}"
        )

    try:
        if output_dir.resolve() == source.resolve():
            raise ValueError("OCR output directory cannot be the source file path.")
    except FileNotFoundError:
        pass

    return output_dir


def validate_output_file(input_path: str | Path, output_path: str | Path) -> Path:
    """Validate a text output file path for single-image OCR."""
    source = Path(input_path).expanduser()
    output = Path(output_path).expanduser()
    if output.exists() and output.is_dir():
        raise ValueError(f"OCR text output must be a file, not a directory: {output}")
    try:
        if output.resolve() == source.resolve():
            raise ValueError("OCR text output cannot be the source file path.")
    except FileNotFoundError:
        pass
    return output


def main():
    default_backend = _get_default_backend()
    parser = argparse.ArgumentParser(description="Multi-backend OCR — Image & PDF OCR")
    parser.add_argument("file", nargs="?", help="Image or PDF file path")
    parser.add_argument("--backend", choices=["mineru", "deepseek", "logics", "paddle", "api"],
                        default=default_backend,
                        help=f"OCR backend (default: {default_backend})")
    parser.add_argument("--batch", help="Process all images/PDFs in a directory")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("-n", "--max-pages", type=int, help="Maximum pages to process")
    args = parser.parse_args()

    # Lazy import based on backend
    if args.backend == "api":
        from ocr._ocr_api import OCRApiBackend
        ocr = OCRApiBackend.from_config()
    elif args.backend == "mineru":
        from ocr._mineru_ocr import MinerUOCR
        ocr = MinerUOCR.from_config()
    elif args.backend == "deepseek":
        from ocr._deepseek_ocr2 import DeepSeekOCR2
        ocr = DeepSeekOCR2.from_config()
    elif args.backend == "logics":
        from ocr._logics_parsing import LogicsParsingOCR
        ocr = LogicsParsingOCR.from_config()
    else:  # paddle
        from ocr._paddle_ocr import PaddleOCRWrapper
        ocr = PaddleOCRWrapper.from_config()

    if args.batch:
        if not os.path.isdir(args.batch):
            print(f"Error: not a directory: {args.batch}", file=sys.stderr)
            sys.exit(1)
        supported = {
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".pdf",
        }
        results = []
        for fname in sorted(os.listdir(args.batch)):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in supported:
                continue
            fpath = os.path.join(args.batch, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                if ext == ".pdf":
                    out_dir = resolve_output_dir(fpath, args.output, fname.replace(".pdf", "_ocr"))
                    report = ocr.ocr_pdf(fpath, out_dir, max_pages=args.max_pages)
                    results.append({"file": fname, "output": str(report)})
                else:
                    text = ocr.ocr_image(fpath)
                    results.append({"file": fname, "text_length": len(text)})
            except Exception as e:
                print(f"Error processing {fname}: {e}", file=sys.stderr)

        print(json.dumps({"ocr_results": results}, indent=2, ensure_ascii=False))
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    ext = os.path.splitext(args.file)[1].lower()
    try:
        if ext == ".pdf":
            out_dir = resolve_output_dir(args.file, args.output, Path(args.file).stem + "_ocr")
            report = ocr.ocr_pdf(args.file, out_dir, max_pages=args.max_pages)
            print(f"Output: {report}")
        else:
            text = ocr.ocr_image(args.file)
            if args.output:
                output = validate_output_file(args.file, args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(text, encoding="utf-8")
                print(f"Output: {output}")
            else:
                print(text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
