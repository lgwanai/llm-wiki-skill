#!/usr/bin/env python3
"""ocr.py — Backward-compatible shim.

OCR backends have moved to the ``ocr/`` package. This shim forwards
all CLI invocations to ``ocr.cli.main`` so existing scripts continue
to work.

Usage (unchanged):
    python scripts/ocr.py document.pdf --backend mineru
    python scripts/ocr.py document.pdf --backend api -o results/
    python scripts/ocr.py --batch screenshots/
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so the 'ocr' package is importable.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ocr.cli import main

if __name__ == "__main__":
    main()
