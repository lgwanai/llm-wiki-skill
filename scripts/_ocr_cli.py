#!/usr/bin/env python3
"""ocr.py — Backward-compatible shim.

OCR backends have moved to the ``ocr/`` package. This shim forwards
all CLI invocations to ``ocr.cli.main`` so existing scripts continue
to work.

Usage (unchanged):
    python scripts/ocr.py document.pdf --backend ovis
    python scripts/ocr.py document.pdf --backend api -o results/
    python scripts/ocr.py --batch screenshots/
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so the 'ocr' package is importable.
_project_root = Path(__file__).resolve().parent.parent
_project_root_text = str(_project_root)
while _project_root_text in sys.path:
    sys.path.remove(_project_root_text)
sys.path.insert(0, _project_root_text)

from ocr.cli import main

if __name__ == "__main__":
    main()
