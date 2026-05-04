#!/usr/bin/env python3
"""ocr.py — Image OCR for llm-wiki.

Extracts text from images using Tesseract OCR and optionally ingests into wiki.

Requirements:
  System:  brew install tesseract tesseract-lang (macOS)
           apt install tesseract-ocr (Linux)
  Python:  pip install pytesseract Pillow

Usage:
  python ocr.py image.png              # Extract text only
  python ocr.py image.png --ingest     # Extract + ingest into wiki
  python ocr.py image.png --lang chi_sim   # Chinese OCR
  python ocr.py --batch screenshots/   # Batch process directory
"""

import argparse
import json
import os
import sys


def ocr_image(filepath: str, lang: str = "eng") -> str:
    """Extract text from a single image using Tesseract."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Image not found: {filepath}")

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "pytesseract or Pillow not installed.\n"
            "Run: pip install pytesseract Pillow"
        )

    try:
        img = Image.open(filepath)
    except Exception as e:
        raise RuntimeError(f"Cannot open image {filepath}: {e}")

    text = pytesseract.image_to_string(img, lang=lang)
    return text.strip()


def _main():
    parser = argparse.ArgumentParser(description="llm-wiki Image OCR")
    parser.add_argument("image", nargs="?", help="Image file path")
    parser.add_argument("--lang", default="eng", help="Tesseract language code (default: eng)")
    parser.add_argument("--ingest", action="store_true", help="Ingest OCR result into wiki")
    parser.add_argument("--batch", help="Process all images in a directory")
    args = parser.parse_args()

    if args.batch:
        if not os.path.isdir(args.batch):
            print(f"Error: not a directory: {args.batch}", file=sys.stderr)
            sys.exit(1)
        results = []
        for fname in sorted(os.listdir(args.batch)):
            fpath = os.path.join(args.batch, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp'}:
                continue
            if not os.path.isfile(fpath):
                continue
            try:
                text = ocr_image(fpath, args.lang)
                results.append({"file": fname, "text_length": len(text)})
                if args.ingest:
                    from ingest import ingest_source
                    tmp = f"/tmp/llm-wiki-ocr-{fname}.txt"
                    with open(tmp, 'w') as f:
                        f.write(text)
                    ingest_source(tmp, source_type="doc")
                    os.remove(tmp)
            except Exception as e:
                print(f"Error processing {fname}: {e}", file=sys.stderr)
        print(json.dumps({"ocr_results": results}, indent=2, ensure_ascii=False))
        return

    if not args.image:
        parser.print_help()
        sys.exit(1)

    try:
        text = ocr_image(args.image, args.lang)
        print(text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
