#!/usr/bin/env python3
"""ocr.py — Image & PDF OCR using local PaddleOCR-VL-1.5 server.

Requirements:
  Server: python scripts/ocr_server.py  (must be running)
  Model:  ~/.models/PaddleOCR-VL-1.5/  (download via scripts/download_models.py)

Usage:
  python ocr.py image.png              # OCR single image
  python ocr.py document.pdf           # OCR PDF (all pages)
  python ocr.py image.png --ingest     # OCR + ingest into wiki
  python ocr.py --batch screenshots/   # Batch process directory
"""

import argparse
import json
import os
import sys


def ocr_file(filepath: str, server_url: str = "http://127.0.0.1:8765") -> str:
    """OCR an image or PDF using the local PaddleOCR server."""
    from _paddle_ocr import PaddleOCRLocal

    ocr = PaddleOCRLocal(server_url)
    if not ocr.ping():
        raise RuntimeError(
            f"OCR server not reachable at {server_url}.\n"
            f"Start it with: python scripts/ocr_server.py"
        )

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return ocr.pdf(filepath) or ""
    return ocr.image(filepath) or ""


def _main():
    parser = argparse.ArgumentParser(description="llm-wiki PaddleOCR-VL-1.5 OCR")
    parser.add_argument("file", nargs="?", help="Image or PDF file path")
    parser.add_argument("--server", default="http://127.0.0.1:8765",
                        help="OCR server URL")
    parser.add_argument("--ingest", action="store_true",
                        help="Ingest OCR result into wiki")
    parser.add_argument("--batch", help="Process all images/PDFs in a directory")
    args = parser.parse_args()

    if args.batch:
        if not os.path.isdir(args.batch):
            print(f"Error: not a directory: {args.batch}", file=sys.stderr)
            sys.exit(1)
        results = []
        supported = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.pdf'}
        for fname in sorted(os.listdir(args.batch)):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in supported:
                continue
            fpath = os.path.join(args.batch, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                text = ocr_file(fpath, args.server)
                results.append({"file": fname, "text_length": len(text)})
                if args.ingest:
                    from ingest import ingest_source
                    tmp = f"/tmp/llm-wiki-ocr-{fname}.md"
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(text)
                    ingest_source(tmp, source_type="doc")
                    os.remove(tmp)
            except Exception as e:
                print(f"Error processing {fname}: {e}", file=sys.stderr)
        print(json.dumps({"ocr_results": results}, indent=2, ensure_ascii=False))
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    try:
        text = ocr_file(args.file, args.server)
        print(text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
