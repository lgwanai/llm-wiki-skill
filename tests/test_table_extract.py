"""Tests for compiler-managed Markdown table extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import table_extract


def test_extract_tables_handles_escaped_pipes_and_ignores_code_fences():
    content = """```markdown
| Not | A table |
| --- | ------- |
| x | y |
```

| Name | Notes |
| --- | --- |
| Alice | supports a\\|b |
"""

    tables = table_extract.extract_tables(content)

    assert len(tables) == 1
    assert tables[0].headers == ["Name", "Notes"]
    assert tables[0].rows == [["Alice", "supports a|b"]]


def test_persist_page_tables_keeps_key_facts_and_replaces_other_tables(monkeypatch):
    calls: list[tuple[str, object]] = []

    def fake_create(**kwargs):
        calls.append(("create", kwargs))
        return {"success": True, "actual_name": kwargs["table_name"]}

    def fake_insert(table, data_json, batch):
        calls.append(("insert", (table, json.loads(data_json), batch)))
        return {"success": True}

    monkeypatch.setattr("ledger.cmd_delete", lambda table: {"success": True})
    monkeypatch.setattr("ledger.cmd_create", fake_create)
    monkeypatch.setattr("ledger.cmd_insert", fake_insert)
    content = """# Page

## Key Facts
| Attribute | Value |
| --- | --- |
| Retention | 7 years |

## Quarterly data
| Quarter | Revenue |
| --- | --- |
| Q1 | 10 |
| Q2 | 12 |
"""

    rendered, stored = table_extract.persist_page_tables(content, "report.md", "report")

    assert "| Attribute | Value |" in rendered
    assert "| Quarter | Revenue |" not in rendered
    assert len(stored) == 1
    assert f"[📊 Quarter, Revenue](table://{stored[0]})" in rendered
    assert calls[0][0] == "create"
    assert calls[1] == (
        "insert",
        (stored[0], [{"Quarter": "Q1", "Revenue": "10"}, {"Quarter": "Q2", "Revenue": "12"}], True),
    )


def test_persist_page_tables_leaves_content_unchanged_when_storage_fails(monkeypatch):
    monkeypatch.setattr("ledger.cmd_delete", lambda table: {"success": True})
    monkeypatch.setattr(
        "ledger.cmd_create", lambda **kwargs: {"success": False, "error": "db unavailable"}
    )
    content = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"

    rendered, stored = table_extract.persist_page_tables(content, "source.md", "page")

    assert rendered == content
    assert stored == []
