#!/usr/bin/env python3
"""Backward-compatible wrapper for the canonical ``wiki ocr`` command."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ocr.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
