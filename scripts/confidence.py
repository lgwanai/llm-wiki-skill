"""Normalize confidence metadata before persistence, arithmetic, and reporting."""

from __future__ import annotations

import math


def normalize_confidence(value: object, default: float = 0.5) -> float:
    """Accept numbers and legacy labels; default invalid values and clamp to [0, 1]."""
    if isinstance(value, bool):
        return default
    if isinstance(value, str):
        value = value.strip().lower()
        value = {"high": 0.9, "medium": 0.5, "low": 0.3}.get(value, value)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return min(max(number, 0.0), 1.0)
