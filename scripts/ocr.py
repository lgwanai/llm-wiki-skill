#!/usr/bin/env python3
"""Backward-compatible wrapper for the canonical ``wiki ocr`` command."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_project_root_text = str(_project_root)
while _project_root_text in sys.path:
    sys.path.remove(_project_root_text)
sys.path.insert(0, _project_root_text)

from ocr.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
