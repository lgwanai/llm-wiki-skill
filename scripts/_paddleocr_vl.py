#!/usr/bin/env python3
"""Backward-compatible shim for the PaddleOCR-VL-1.6 backend."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ocr._paddleocr_vl import *  # noqa: F401, F403, E402
