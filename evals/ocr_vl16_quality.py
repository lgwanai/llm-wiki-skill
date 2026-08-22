#!/usr/bin/env python3
"""Deterministic substring quality gate for PaddleOCR-VL page Markdown."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _normalise(text: str) -> str:
    """Normalise whitespace without hiding character recognition errors."""
    return re.sub(r"\s+", "", text)


def _pages(markdown: str) -> dict[int, str]:
    """Split canonical OCR Markdown into one string per page."""
    matches = list(re.finditer(r"(?m)^##\s+Page\s+(\d+)\s*$", markdown))
    pages: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        pages[int(match.group(1))] = markdown[match.end() : end]
    return pages


def evaluate(markdown: str, spec: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate required tokens page by page and return a JSON-ready report."""
    pages = _pages(markdown)
    cases: list[dict[str, Any]] = []
    for item in spec:
        page = int(item["page"])
        content = _normalise(pages.get(page, ""))
        required = [str(token) for token in item.get("must_contain", [])]
        missing = [token for token in required if _normalise(token) not in content]
        cases.append(
            {
                "name": str(item.get("name", f"page-{page}")),
                "page": page,
                "required": len(required),
                "missing": missing,
                "passed": bool(required) and not missing,
            }
        )
    return {
        "passed": bool(cases) and all(case["passed"] for case in cases),
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case["passed"]),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the quality gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args(argv)
    markdown = args.markdown.read_text(encoding="utf-8")
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    if not isinstance(spec, list):
        raise ValueError("quality spec must be a JSON list")
    report = evaluate(markdown, spec)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
