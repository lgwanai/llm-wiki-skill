"""Normalize simple OCR HTML tables while retaining the backend's original evidence."""

from __future__ import annotations

import re
from html.parser import HTMLParser

try:
    from .native_document import markdown_table
except ImportError:
    from native_document import markdown_table


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.colspan = 1
        self.safe = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
            if attributes.get("rowspan", "1") != "1":
                self.safe = False
            span = attributes.get("colspan") or "1"
            self.colspan = int(span) if span.isdigit() and len(span) <= 2 else 0
            self.safe &= self.colspan > 0
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.row is not None and self.cell is not None:
            self.row.extend(["".join(self.cell).strip(), *([""] * (self.colspan - 1))])
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def html_table_markdown(html: str) -> str:
    """Return a safe row-wise projection; complex merged headers stay in HTML."""
    if len(re.findall(r"<table\b", html, re.I)) != 1:
        return ""
    parser = _Table()
    parser.feed(html)
    rows = parser.rows
    if (
        not parser.safe
        or len(rows) < 2
        or not rows[0]
        or any(len(row) != len(rows[0]) for row in rows)
    ):
        return ""
    # Paddle often emits an extra empty column merged into the last body cell.
    while rows[0] and all(not row[-1] for row in rows):
        for row in rows:
            row.pop()
    if not rows[0] or not all(rows[0]):
        return ""
    return markdown_table(rows)
