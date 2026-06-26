"""Extract Markdown tables during compilation and store them in the ledger.

The compiler keeps the page's Key Facts table in Markdown because the retrieval
pipeline reads it directly. Other GitHub-flavored Markdown tables are persisted
to DuckDB and replaced with a navigable ``[[table:<name>|...]]`` link.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownTable:
    """A GitHub-flavored Markdown table and the source span it occupies."""

    headers: list[str]
    rows: list[list[str]]
    raw: str
    start: int
    end: int


_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
_KEY_FACTS_HEADING = re.compile(r"^#{2,}\s*(?:key\s+facts|关键事实)\s*$", re.IGNORECASE)


def _split_row(line: str) -> list[str]:
    """Split a Markdown pipe row, preserving escaped pipes in cells."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _is_separator(line: str, expected_columns: int) -> bool:
    cells = _split_row(line)
    return len(cells) == expected_columns and all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def extract_tables(content: str) -> list[MarkdownTable]:
    """Return valid Markdown tables, ignoring code fences and malformed rows."""
    lines = content.splitlines(keepends=True)
    tables: list[MarkdownTable] = []
    offset = 0
    index = 0
    in_fence = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            offset += len(line)
            index += 1
            continue
        if in_fence or "|" not in line or index + 1 >= len(lines):
            offset += len(line)
            index += 1
            continue

        headers = _split_row(line)
        if not headers or not _is_separator(lines[index + 1], len(headers)):
            offset += len(line)
            index += 1
            continue

        start = offset
        end_index = index + 2
        rows: list[list[str]] = []
        while end_index < len(lines):
            candidate = lines[end_index]
            if not candidate.strip() or "|" not in candidate:
                break
            row = _split_row(candidate)
            if len(row) > len(headers):
                row = row[: len(headers)]
            row.extend([""] * (len(headers) - len(row)))
            rows.append(row)
            end_index += 1

        raw = "".join(lines[index:end_index]).rstrip("\n")
        end = start + len(raw)
        tables.append(MarkdownTable(headers, rows, raw, start, end))
        consumed = "".join(lines[index:end_index])
        offset += len(consumed)
        index = end_index

    return tables


def _has_key_facts_heading_before(content: str, position: int) -> bool:
    """Whether the closest preceding level-two heading marks a Key Facts table."""
    headings = re.findall(r"^##(?!#)[^\n]*$", content[:position], flags=re.MULTILINE)
    return bool(headings and _KEY_FACTS_HEADING.fullmatch(headings[-1].strip()))


def _unique_headers(headers: list[str]) -> list[str]:
    """Ledger columns must be non-empty and unique; retain original meaning."""
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, header in enumerate(headers, start=1):
        base = header or f"column_{index}"
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def _table_name(source_name: str, page_id: str, index: int) -> str:
    digest = hashlib.sha256(f"{source_name}:{page_id}:{index}".encode()).hexdigest()[:12]
    return f"extracted_{digest}"


def table_link(name: str, headers: list[str]) -> str:
    label = ", ".join(headers[:3]) or name
    if len(headers) > 3:
        label += ", ..."
    return f"[[table:{name}|📊 {label}]]"


def persist_page_tables(content: str, source_name: str, page_id: str) -> tuple[str, list[str]]:
    """Store non-Key-Facts tables and replace them with navigable wiki links.

    Storage failures do not alter the page: compilation should not lose source
    content merely because its optional structured-table index is unavailable.
    """
    from ledger import cmd_create, cmd_delete, cmd_insert

    replacements: list[tuple[int, int, str]] = []
    stored: list[str] = []
    for ordinal, table in enumerate(extract_tables(content), start=1):
        if not table.rows or _has_key_facts_heading_before(content, table.start):
            continue
        headers = _unique_headers(table.headers)
        name = _table_name(source_name, page_id, ordinal)
        display_name = f"Extracted table: {page_id} #{ordinal}"
        fields = json.dumps(
            [{"name": header, "type": "string"} for header in headers], ensure_ascii=False
        )
        records = [dict(zip(headers, row)) for row in table.rows]

        cmd_delete(name)
        created = cmd_create(
            display_name=display_name,
            fields_json=fields,
            table_name=name,
            description=f"Extracted from {source_name}, page {page_id}, table {ordinal}",
        )
        if not created.get("success"):
            continue
        inserted = cmd_insert(name, json.dumps(records, ensure_ascii=False), batch=True)
        if not inserted.get("success"):
            cmd_delete(name)
            continue
        replacements.append((table.start, table.end, table_link(name, headers)))
        stored.append(name)

    for start, end, replacement in reversed(replacements):
        content = content[:start] + replacement + content[end:]
    return content, stored
