"""Tests for ledger.py — structured table management."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the scripts/ directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# We test ledger functions directly, not via subprocess.
# ledger.py sets LEDGER_DIR = WIKI_DIR / "ledger" at import time,
# so we must mock get_wiki_dir before importing.
WIKI_DIR = Path(__file__).resolve().parent.parent / ".wiki"


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def ledger_dir(tmp_path):
    """Create a temporary .wiki/ledger/ structure."""
    ledger = tmp_path / ".wiki" / "ledger"
    ledger.mkdir(parents=True)
    return ledger


@pytest.fixture
def ledger_module(ledger_dir, monkeypatch):
    """Patch get_wiki_dir to return a temp dir, then import ledger module.

    Each test gets a fresh DuckDB database in tmp_path.
    """
    wiki = ledger_dir.parent  # tmp_path/.wiki
    monkeypatch.setattr("config.get_wiki_dir", lambda: wiki)

    import scripts.ledger as ledger

    # Override constants to point at temp dirs
    monkeypatch.setattr(ledger, "WIKI_DIR", wiki)
    monkeypatch.setattr(ledger, "LEDGER_DIR", wiki / "ledger")
    monkeypatch.setattr(ledger, "LEDGER_DB", wiki / "ledger" / "ledger.duckdb")
    monkeypatch.setattr(ledger, "TABLES_DIR", wiki / "ledger" / "tables")
    monkeypatch.setattr(ledger, "REGISTRY_FILE", wiki / "ledger" / "registry.json")
    return ledger


# ── Helpers ─────────────────────────────────────────────────────────────


def _get_schema(led, actual_name):
    """Get schema info from DuckDB."""
    conn = led._get_conn()
    reg = conn.execute("SELECT fields_json, unique_key, auto_increment, auto_increment_field "
                       "FROM _registry WHERE actual_name = ?", [actual_name]).fetchone()
    if reg is None:
        return None
    return {
        "fields": json.loads(reg[0]),
        "unique_key": json.loads(reg[1]),
        "auto_increment": reg[2],
        "auto_increment_field": reg[3],
    }


def _get_data(led, actual_name):
    """Get all data rows from a DuckDB table."""
    conn = led._get_conn()
    try:
        rows = conn.execute(f'SELECT * FROM "{actual_name}"').fetchall()
        cols = [d[0] for d in conn.description]
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


def _table_exists(led, actual_name):
    """Check if a DuckDB table exists."""
    conn = led._get_conn()
    r = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [actual_name]
    ).fetchone()
    return r[0] > 0


def _create_table(led, display_name="测试表", **kwargs):
    """Convenience to create a table for testing."""
    fields = kwargs.pop(
        "fields",
        '[{"name":"名称","type":"string","required":true},{"name":"数量","type":"integer"}]',
    )
    unique = kwargs.pop("unique", "名称")
    auto_inc = kwargs.pop("auto_increment", True)
    desc = kwargs.pop("description", "测试用表")
    result = led.cmd_create(
        display_name=display_name,
        fields_json=fields,
        unique=unique,
        auto_increment=auto_inc,
        description=desc,
    )
    assert result["success"], f"Failed to create table: {result}"
    return result


def _insert(led, table, data, batch=False):
    """Convenience to insert data."""
    result = led.cmd_insert(table, json.dumps(data), batch=batch)
    return result


# ── Table Name Generation ───────────────────────────────────────────────


def _empty_conn(ledger_module):
    """Get a fresh DuckDB connection with empty _registry."""
    return ledger_module._get_conn()


def test_generate_table_name_chinese(ledger_module):
    """Pure Chinese display names should produce hash-based names."""
    conn = _empty_conn(ledger_module)
    name = ledger_module._generate_table_name("员工台账", conn)
    assert name.startswith("table_")
    assert len(name) == 14  # "table_" + 8 hex chars


def test_generate_table_name_english(ledger_module):
    """Latin-script display names should be slugified."""
    conn = _empty_conn(ledger_module)
    name = ledger_module._generate_table_name("Project Ledger", conn)
    assert name == "project-ledger"


def test_generate_table_name_collision(ledger_module):
    """Collisions should append _2, _3, etc."""
    conn = _empty_conn(ledger_module)
    # Pre-register names to force collision
    conn.execute("INSERT INTO _registry (actual_name, display_name) VALUES ('project-ledger', 'x')")
    conn.execute("INSERT INTO _registry (actual_name, display_name) VALUES ('project-ledger_2', 'y')")
    name = ledger_module._generate_table_name("Project Ledger", conn)
    assert name == "project-ledger_3"


def test_resolve_table_by_display_name(ledger_module):
    """Should find table by display name."""
    conn = _empty_conn(ledger_module)
    conn.execute("INSERT INTO _registry (actual_name, display_name) VALUES ('table_abc123', '员工表')")
    result = ledger_module._resolve_table("员工表", conn)
    assert result == "table_abc123"


def test_resolve_table_by_actual_name(ledger_module):
    """Should find table by actual name."""
    conn = _empty_conn(ledger_module)
    conn.execute("INSERT INTO _registry (actual_name, display_name) VALUES ('table_abc123', '员工表')")
    result = ledger_module._resolve_table("table_abc123", conn)
    assert result == "table_abc123"


def test_resolve_table_not_found(ledger_module):
    """Should return None for unknown table."""
    conn = _empty_conn(ledger_module)
    result = ledger_module._resolve_table("不存在的表", conn)
    assert result is None


# ── Registry ────────────────────────────────────────────────────────────


def test_empty_registry_list(ledger_module):
    """Listing an empty registry should return success with 0 tables."""
    result = ledger_module.cmd_list()
    assert result["success"]
    assert result["count"] == 0
    assert result["tables"] == []


# ── Create ──────────────────────────────────────────────────────────────


def test_create_simple_table(ledger_module):
    """Create a basic table with no auto-increment."""
    result = ledger_module.cmd_create(
        display_name="简单表",
        fields_json='[{"name":"标题","type":"string","required":true}]',
    )
    assert result["success"]
    assert result["display_name"] == "简单表"
    assert result["field_count"] == 1

    # Verify in DuckDB
    conn = ledger_module._get_conn()
    reg = conn.execute("SELECT * FROM _registry WHERE actual_name = ?",
                       [result["actual_name"]]).fetchone()
    assert reg is not None
    assert reg[1] == "简单表"  # display_name


def test_create_with_auto_increment(ledger_module):
    """Auto-increment should add _id field, unique_key, and sequence."""
    result = ledger_module.cmd_create(
        display_name="自动编号表",
        fields_json='[{"name":"名称","type":"string","required":true}]',
        auto_increment=True,
    )
    assert result["success"]

    conn = ledger_module._get_conn()
    reg = conn.execute(
        "SELECT auto_increment, auto_increment_field, unique_key, fields_json "
        "FROM _registry WHERE actual_name = ?", [result["actual_name"]]
    ).fetchone()
    assert reg[0] is True  # auto_increment
    assert reg[1] == "_id"
    assert json.loads(reg[2]) == ["_id"]
    fields = json.loads(reg[3])
    field_names = [f["name"] for f in fields]
    assert "_id" in field_names
    assert "名称" in field_names


def test_create_duplicate_display_name(ledger_module):
    """Creating a table with an existing display name should fail."""
    _create_table(ledger_module, "唯一表")
    result = ledger_module.cmd_create(
        display_name="唯一表",
        fields_json='[{"name":"其他","type":"string"}]',
    )
    assert not result["success"]
    assert "already exists" in result["error"]


def test_create_invalid_fields_json(ledger_module):
    """Malformed JSON should return error."""
    result = ledger_module.cmd_create(
        display_name="坏表",
        fields_json="not valid json",
    )
    assert not result["success"]
    assert "Invalid" in result["error"]


def test_create_duplicate_field_name(ledger_module):
    """Duplicate field names should be rejected."""
    result = ledger_module.cmd_create(
        display_name="重复字段表",
        fields_json='[{"name":"名称","type":"string"},{"name":"名称","type":"integer"}]',
    )
    assert not result["success"]
    assert "Duplicate" in result["error"]


def test_create_unknown_type(ledger_module):
    """Unknown field types should be rejected."""
    result = ledger_module.cmd_create(
        display_name="坏类型表",
        fields_json='[{"name":"数据","type":"unknown_type"}]',
    )
    assert not result["success"]
    assert "unknown type" in result["error"].lower()


def test_create_explicit_table_name(ledger_module):
    """User can override the auto-generated table name."""
    result = ledger_module.cmd_create(
        display_name="自定义名",
        fields_json='[{"name":"值","type":"string"}]',
        table_name="my_custom_table",
    )
    assert result["success"]
    assert result["actual_name"] == "my_custom_table"


def test_create_auto_increment_conflict(ledger_module):
    """Cannot use --auto-increment if _id is already in fields."""
    result = ledger_module.cmd_create(
        display_name="冲突表",
        fields_json='[{"name":"_id","type":"integer"},{"name":"名称","type":"string"}]',
        auto_increment=True,
    )
    assert not result["success"]
    assert "_id" in result.get("error", "")


# ── Show ────────────────────────────────────────────────────────────────


def test_show_table(ledger_module):
    """Show should return schema and data."""
    r = _create_table(ledger_module)
    result = ledger_module.cmd_show(r["actual_name"])
    assert result["success"]
    assert result["table"]["display_name"] == "测试表"
    assert result["total_rows"] == 0
    assert result["shown_rows"] == 0


def test_show_nonexistent_table(ledger_module):
    """Show on unknown table should return error."""
    result = ledger_module.cmd_show("不存在的表")
    assert not result["success"]


# ── Insert ──────────────────────────────────────────────────────────────


def test_insert_single_row(ledger_module):
    """Insert a single valid row."""
    r = _create_table(ledger_module)
    result = _insert(ledger_module, r["actual_name"], {"名称": "测试项目", "数量": 10})
    assert result["success"]
    assert result["inserted"] == 1
    assert result["total_rows"] == 1


def test_insert_duplicate_unique_key(ledger_module):
    """Inserting a duplicate unique key should fail."""
    r = _create_table(ledger_module)
    _insert(ledger_module, r["actual_name"], {"名称": "项目A", "数量": 1})
    result = _insert(ledger_module, r["actual_name"], {"名称": "项目A", "数量": 2})
    assert not result["success"]
    assert any("Duplicate" in e.get("error", "") for e in result.get("details", []))


def test_insert_missing_required_field(ledger_module):
    """Missing required field should fail."""
    r = _create_table(ledger_module)
    result = _insert(ledger_module, r["actual_name"], {"数量": 5})
    assert not result["success"]
    assert any("required" in e.get("error", "") for e in result.get("details", []))


def test_insert_type_error(ledger_module):
    """Wrong type should fail."""
    r = _create_table(ledger_module)
    result = _insert(ledger_module, r["actual_name"], {"名称": "项目", "数量": "不是数字"})
    assert not result["success"]
    assert any("integer" in e.get("error", "").lower() for e in result.get("details", []))


def test_insert_unknown_field(ledger_module):
    """Unknown fields should be rejected."""
    r = _create_table(ledger_module)
    result = _insert(ledger_module, r["actual_name"], {"名称": "项目", "不存在的字段": "值"})
    assert not result["success"]
    assert any("Unknown" in e.get("error", "") for e in result.get("details", []))


def test_insert_batch_mode(ledger_module):
    """Batch mode should insert valid rows and report failed ones."""
    r = _create_table(ledger_module)
    rows = [
        {"名称": "项目A", "数量": 1},
        {"名称": "项目B"},  # missing required "数量" won't matter since it's not required by default
        {"名称": "项目C", "数量": 3},
    ]
    result = _insert(ledger_module, r["actual_name"], rows, batch=True)
    assert result["success"]
    assert result["inserted"] == 3  # all valid: "名称" is required, "数量" is not


def test_insert_auto_increment(ledger_module):
    """Auto-increment should assign sequential _id values."""
    r = _create_table(ledger_module)
    _insert(ledger_module, r["actual_name"], {"名称": "第一条", "数量": 1})
    _insert(ledger_module, r["actual_name"], {"名称": "第二条", "数量": 2})

    show = ledger_module.cmd_show(r["actual_name"])
    ids = [row["_id"] for row in show["data"]]
    assert ids == [1, 2]


def test_insert_nonexistent_table(ledger_module):
    """Insert to unknown table should fail."""
    result = _insert(ledger_module, "unknown", {"x": 1})
    assert not result["success"]
    assert "not found" in result["error"]


# ── Type Coercion ───────────────────────────────────────────────────────


def test_coerce_integer_from_string(ledger_module):
    """String '123' should coerce to integer 123."""
    val, err = ledger_module._coerce_value("123", "integer")
    assert err is None
    assert val == 123
    assert isinstance(val, int)


def test_coerce_integer_failure(ledger_module):
    """Non-numeric string should fail integer coercion."""
    val, err = ledger_module._coerce_value("abc", "integer")
    assert err is not None


def test_coerce_number(ledger_module):
    """String '12.5' should coerce to float 12.5."""
    val, err = ledger_module._coerce_value("12.5", "number")
    assert err is None
    assert val == 12.5


def test_coerce_boolean_true(ledger_module):
    """Various truthy strings should coerce to True."""
    for v in ["true", "True", "1", "yes", "YES"]:
        val, err = ledger_module._coerce_value(v, "boolean")
        assert err is None, f"Failed for {v}"
        assert val is True, f"Expected True for {v}"


def test_coerce_boolean_false(ledger_module):
    """Various falsy strings should coerce to False."""
    for v in ["false", "False", "0", "no", ""]:
        val, err = ledger_module._coerce_value(v, "boolean")
        assert err is None, f"Failed for {v}"
        assert val is False, f"Expected False for {v}"


def test_coerce_date_valid(ledger_module):
    """Valid date format should pass."""
    val, err = ledger_module._coerce_value("2026-01-15", "date")
    assert err is None
    assert val == "2026-01-15"


def test_coerce_date_invalid(ledger_module):
    """Invalid date format should fail."""
    val, err = ledger_module._coerce_value("01/15/2026", "date")
    assert err is not None


def test_coerce_none(ledger_module):
    """None should pass through unchanged."""
    val, err = ledger_module._coerce_value(None, "string")
    assert err is None
    assert val is None


# ── Update Schema ───────────────────────────────────────────────────────


def test_update_schema_add_field(ledger_module):
    """Adding a field should update schema and add nulls to existing data."""
    r = _create_table(ledger_module)
    _insert(ledger_module, r["actual_name"], {"名称": "项目", "数量": 5})

    result = ledger_module.cmd_update_schema(
        r["actual_name"],
        add='[{"name":"备注","type":"text"}]',
    )
    assert result["success"]
    assert any("added" in c for c in result["changes"])

    # Verify via DuckDB
    conn = ledger_module._get_conn()
    cols = conn.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                        [r["actual_name"]]).fetchall()
    col_names = [c[0] for c in cols]
    assert "备注" in col_names

    data = _get_data(ledger_module, r["actual_name"])
    assert data[0]["备注"] is None


def test_update_schema_remove_field(ledger_module):
    """Removing a field should update schema and strip it from data."""
    r = _create_table(ledger_module)
    result = ledger_module.cmd_update_schema(r["actual_name"], remove="数量")
    assert result["success"]

    conn = ledger_module._get_conn()
    cols = conn.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                        [r["actual_name"]]).fetchall()
    col_names = [c[0] for c in cols]
    assert "数量" not in col_names


def test_update_schema_rename_field(ledger_module):
    """Renaming a field should update schema and migrate data."""
    r = _create_table(ledger_module)
    _insert(ledger_module, r["actual_name"], {"名称": "项目", "数量": 10})

    result = ledger_module.cmd_update_schema(r["actual_name"], rename="数量:个数")
    assert result["success"]

    conn = ledger_module._get_conn()
    cols = conn.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                        [r["actual_name"]]).fetchall()
    col_names = [c[0] for c in cols]
    assert "数量" not in col_names
    assert "个数" in col_names

    data = _get_data(ledger_module, r["actual_name"])
    assert data[0]["个数"] == 10


def test_update_schema_modify_type(ledger_module):
    """Changing a field type should coerce existing data."""
    r = _create_table(ledger_module)
    _insert(ledger_module, r["actual_name"], {"名称": "项目", "数量": 10})

    result = ledger_module.cmd_update_schema(
        r["actual_name"],
        modify='[{"name":"数量","type":"number"}]',
    )
    assert result["success"]
    data = _get_data(ledger_module, r["actual_name"])
    assert isinstance(data[0]["数量"], float)


def test_update_schema_nonexistent_table(ledger_module):
    """Updating unknown table should fail."""
    result = ledger_module.cmd_update_schema("unknown", add='[{"name":"x","type":"string"}]')
    assert not result["success"]


def test_update_schema_no_changes(ledger_module):
    """Calling update-schema with no flags should return error."""
    r = _create_table(ledger_module)
    result = ledger_module.cmd_update_schema(r["actual_name"])
    assert not result["success"]


# ── Delete ──────────────────────────────────────────────────────────────


def test_delete_table(ledger_module):
    """Deleting should remove from registry and drop DuckDB table."""
    r = _create_table(ledger_module)
    actual = r["actual_name"]

    assert _table_exists(ledger_module, actual)

    result = ledger_module.cmd_delete(actual)
    assert result["success"]

    # Registry entry removed
    conn = ledger_module._get_conn()
    reg = conn.execute("SELECT COUNT(*) FROM _registry WHERE actual_name = ?", [actual]).fetchone()[0]
    assert reg == 0

    # DuckDB table dropped
    assert not _table_exists(ledger_module, actual)


def test_delete_keep_files(ledger_module):
    """--keep-files should remove registry entry but keep DuckDB table."""
    r = _create_table(ledger_module)
    actual = r["actual_name"]

    result = ledger_module.cmd_delete(actual, keep_files=True)
    assert result["success"]

    conn = ledger_module._get_conn()
    reg = conn.execute("SELECT COUNT(*) FROM _registry WHERE actual_name = ?", [actual]).fetchone()[0]
    assert reg == 0
    # Table still exists
    assert _table_exists(ledger_module, actual)


def test_delete_nonexistent_table(ledger_module):
    """Deleting unknown table should fail."""
    result = ledger_module.cmd_delete("unknown")
    assert not result["success"]


# ── Stats ────────────────────────────────────────────────────────────────


def test_stats_all_tables(ledger_module):
    """Stats should aggregate across all tables."""
    r1 = _create_table(ledger_module, "表一")
    r2 = _create_table(ledger_module, "表二")
    _insert(ledger_module, r1["actual_name"], {"名称": "项目1", "数量": 1})
    _insert(ledger_module, r2["actual_name"], {"名称": "项目2", "数量": 2})
    _insert(ledger_module, r2["actual_name"], {"名称": "项目3", "数量": 3})

    result = ledger_module.cmd_stats()
    assert result["success"]
    assert result["table_count"] == 2
    assert result["total_rows"] == 3


def test_stats_single_table(ledger_module):
    """Stats for a single table."""
    r = _create_table(ledger_module)
    _insert(ledger_module, r["actual_name"], {"名称": "项目", "数量": 1})

    result = ledger_module.cmd_stats(r["actual_name"])
    assert result["success"]
    assert result["row_count"] == 1
    assert result["field_count"] > 0


def test_stats_nonexistent_table(ledger_module):
    """Stats on unknown table should fail."""
    result = ledger_module.cmd_stats("unknown")
    assert not result["success"]
