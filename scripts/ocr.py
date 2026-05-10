#!/usr/bin/env python3
"""ocr.py — Image & PDF OCR using DeepSeek-OCR.

Usage:
    python ocr.py image.png                     # OCR single image → stdout
    python ocr.py document.pdf                  # Full pipeline: grounding + text + image extraction → output.md
    python ocr.py document.pdf -o results/      # Specify output directory
    python ocr.py document.pdf -n 10            # Process first 10 pages only
    python ocr.py --batch screenshots/          # Batch process directory
"""

import argparse
import json
import os
import sys
from pathlib import Path

from _deepseek_ocr import DeepSeekOCR


def main():
    parser = argparse.ArgumentParser(description="DeepSeek-OCR — Image & PDF OCR")
    parser.add_argument("file", nargs="?", help="Image or PDF file path")
    parser.add_argument("--batch", help="Process all images/PDFs in a directory")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    parser.add_argument("-n", "--max-pages", type=int, help="Maximum pages to process")
    args = parser.parse_args()

    ocr = DeepSeekOCR.from_config()

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
                    out_dir = Path(args.output or fname.replace(".pdf", "_ocr"))
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
            out_dir = Path(args.output or Path(args.file).stem + "_ocr")
            report = ocr.ocr_pdf(args.file, out_dir, max_pages=args.max_pages)
            print(f"Output: {report}")
        else:
            text = ocr.ocr_image(args.file)
            print(text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
