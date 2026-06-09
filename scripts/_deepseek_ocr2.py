#!/usr/bin/env python3
"""Backward-compatible shim — see ocr/ package for the implementation."""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ocr._deepseek_ocr2 import *  # noqa: F401, F403, E402
