from pathlib import Path

import okf
import search


def _bundle(root: Path) -> Path:
    bundle = root / "bundle"
    (bundle / "tables").mkdir(parents=True)
    (bundle / "tables" / "orders.md").write_text(
        """---
type: BigQuery Table
title: Customer Orders
description: One row per order.
resource: https://example.com/orders
tags: [sales, orders]
custom_field: preserved
---
# Schema

See [customers](/tables/customers.md).
""",
        encoding="utf-8",
    )
    (bundle / "index.md").write_text("# Bundle\n", encoding="utf-8")
    return bundle


def test_validate_okf_bundle(tmp_path):
    result = okf.validate_bundle(_bundle(tmp_path))
    assert result["valid"] is True
    assert result["concepts"] == 1


def test_validate_requires_type(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bad.md").write_text("---\ntitle: Missing Type\n---\nBody\n")
    result = okf.validate_bundle(bundle)
    assert result["valid"] is False
    assert "type" in result["errors"][0]["message"]


def test_import_preserves_extensions_and_is_searchable(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    monkeypatch.setattr(okf, "get_wiki_dir", lambda: wiki)
    result = okf.import_bundle(_bundle(tmp_path))
    imported = wiki / "pages" / "tables" / "orders.md"
    metadata, _, error = okf.read_markdown(imported)
    assert result["imported"] == 1
    assert error is None
    assert metadata["custom_field"] == "preserved"
    assert okf.concept_id(imported, wiki / "pages") == "tables/orders"
    assert imported in search._known_page_paths(wiki / "pages")


def test_export_produces_conformant_bundle(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    page = wiki / "pages" / "concepts" / "revenue.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        """---
type: Metric
title: Revenue
description: Recognized revenue.
tags: [finance]
resource: https://example.com/revenue
timestamp: 2026-07-11T00:00:00Z
---
# Revenue

Revenue definition.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(okf, "get_wiki_dir", lambda: wiki)
    result = okf.export_bundle(tmp_path / "export")
    metadata, _, error = okf.read_markdown(tmp_path / "export" / "concepts" / "revenue.md")
    assert result["valid"] is True
    assert result["exported"] == 1
    assert error is None
    assert metadata["title"] == "Revenue"
    assert metadata["tags"] == ["finance"]


def test_migrate_legacy_page_to_native_okf(tmp_path):
    pages = tmp_path / "pages"
    page = pages / "concepts" / "legacy.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\nid: legacy\ntype: concept\nname: Legacy\n"
        "summary: Old metadata\nkeywords: [old]\ncreated_at: 2024-01-01\n---\nBody\n"
    )
    result = okf.migrate_native_bundle(pages)
    metadata, _, _ = okf.read_markdown(page)
    assert result["valid"] is True
    assert result["migrated"] == 1
    assert metadata["title"] == "Legacy"
    assert "id" not in metadata
