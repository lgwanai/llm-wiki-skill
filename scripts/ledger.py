#!/usr/bin/env python3
"""ledger.py — Structured table (台账) management for LLM Wiki v2.

Tabular data gets special treatment: typed columns, field definitions,
import timestamps, and structured search — maximizing data integrity
that unstructured markdown cannot preserve.

Storage: .wiki/ledger/<table-id>/{schema.json, data.json}
Index:   .wiki/ledger/index.json

Usage:
    python3 scripts/ledger.py import data.csv
    python3 scripts/ledger.py list
    python3 scripts/ledger.py show <table-id>
    python3 scripts/ledger.py search <query>
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
WIKI_DIR = Path(os.environ.get("LLM_WIKI_DIR", str(ROOT / ".wiki")))
LEDGER_DIR = WIKI_DIR / "ledger"
INDEX_FILE = LEDGER_DIR / "index.json"

TYPE_HINTS = {
    "int": r'^\s*-?\d+\s*$',
    "float": r'^\s*-?\d+\.?\d*\s*$',
    "percentage": r'^\s*-?\d+\.?\d*\s*%\s*$',
    "date": r'^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*$',
    "url": r'^\s*https?://',
    "email": r'^\s*\S+@\S+\.\S+\s*$',
    "boolean": r'^\s*(true|false|yes|no|是|否|0|1)\s*$',
    "number_range": r'^\s*\d+\.?\d*\s*[-~]\s*\d+\.?\d*\s*$',
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-').replace('_', '-'))


def _infer_type(values: list[str]) -> str:
    """Infer column type from sample values."""
    if not values:
        return "text"
    non_empty = [v.strip() for v in values if v.strip()]
    if not non_empty:
        return "text"

    # Check each type pattern
    for tname, pattern in TYPE_HINTS.items():
        if all(re.match(pattern, v) for v in non_empty):
            return tname

    # Nested check: if most look like ints, call it int
    int_count = sum(1 for v in non_empty if re.match(TYPE_HINTS["int"], v))
    if int_count / len(non_empty) > 0.8:
        return "int"

    return "text"


def _suggest_field_name(header: str) -> str:
    """Convert Chinese/English header to a lowercase-hyphenated slug."""
    name = header.strip().lower().replace(' ', '-').replace('_', '-')
    return re.sub(r'[^a-z0-9-]', '', name) or "field"


def import_table(filepath: str, table_name: Optional[str] = None) -> dict:
    """Import CSV/Excel file as a structured ledger table."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    source_name = os.path.basename(filepath)

    # Parse rows
    if ext == ".csv":
        with open(filepath, encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            raw_rows = list(reader)
    elif ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True)
            ws = wb.active
            raw_rows = [[str(c.value or '') for c in row] for row in ws.iter_rows()]
            wb.close()
        except ImportError:
            raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")
    else:
        # Try CSV as fallback
        with open(filepath, encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            raw_rows = list(reader)

    if not raw_rows or len(raw_rows) < 2:
        raise ValueError("Table must have at least 1 header row and 1 data row")

    # First row = headers
    headers = [h.strip() for h in raw_rows[0] if h.strip()]
    if not headers:
        raise ValueError("No headers found in first row")

    data_rows = raw_rows[1:]

    # Infer column types from first 100 data rows
    sample_rows = data_rows[:100]
    field_defs = []
    for i, header in enumerate(headers):
        values = [row[i].strip() for row in sample_rows if i < len(row)]
        ftype = _infer_type(values)
        field_defs.append({
            "name": _suggest_field_name(header),
            "display_name": header,
            "type": ftype,
            "index": i,
        })

    # Auto-generate table ID
    table_id = _slugify(table_name or source_name) or "table"
    # Ensure uniqueness
    base_id = table_id
    counter = 1
    while (LEDGER_DIR / table_id).exists():
        table_id = f"{base_id}-{counter}"
        counter += 1

    table_dir = LEDGER_DIR / table_id
    table_dir.mkdir(parents=True, exist_ok=True)

    # Build structured rows
    rows = []
    for raw_row in data_rows:
        row = {}
        for field in field_defs:
            idx = field["index"]
            value = raw_row[idx].strip() if idx < len(raw_row) else ""
            # Type-aware value conversion
            ft = field["type"]
            if ft == "int":
                try:
                    row[field["name"]] = int(value.replace(",", ""))
                except ValueError:
                    row[field["name"]] = value
            elif ft == "float" or ft == "percentage":
                try:
                    row[field["name"]] = float(value.replace(",", "").replace("%", ""))
                except ValueError:
                    row[field["name"]] = value
            elif ft == "boolean":
                row[field["name"]] = value.lower() in ("true", "yes", "是", "1")
            else:
                row[field["name"]] = value
        rows.append(row)

    # Schema
    table_desc = table_name or source_name.replace("_", " ").replace("-", " ").rsplit(".", 1)[0]
    schema = {
        "id": table_id,
        "name": table_desc,
        "source": source_name,
        "description": f"Table imported from {source_name}",
        "import_time": _now(),
        "import_method": f"ledger.import_table({ext})",
        "fields": field_defs,
        "row_count": len(rows),
        "field_count": len(field_defs),
    }
    (table_dir / "schema.json").write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")

    # Data
    (table_dir / "data.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # Update index
    _update_index(schema)

    print(f"  Imported: {table_id} ({len(rows)} rows, {len(field_defs)} fields)", file=sys.stderr)
    return schema


def _update_index(schema: dict):
    """Add or update a table entry in the ledger index."""
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)

    index = []
    if INDEX_FILE.exists():
        try:
            index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index = []

    entry = {
        "id": schema["id"],
        "name": schema["name"],
        "description": schema["description"],
        "fields_count": schema["field_count"],
        "rows_count": schema["row_count"],
        "field_names": [f["display_name"] for f in schema["fields"]],
        "field_types": {f["display_name"]: f["type"] for f in schema["fields"]},
        "import_time": schema["import_time"],
        "source": schema["source"],
    }

    # Replace or append
    replaced = False
    for i, item in enumerate(index):
        if item["id"] == schema["id"]:
            index[i] = entry
            replaced = True
            break
    if not replaced:
        index.append(entry)

    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def list_ledgers() -> list[dict]:
    """List all imported ledger tables."""
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def show_ledger(table_id: str, limit: int = 20) -> dict:
    """Show ledger schema and preview data."""
    table_dir = LEDGER_DIR / table_id
    if not table_dir.exists():
        raise FileNotFoundError(f"Ledger not found: {table_id}")

    schema = json.loads((table_dir / "schema.json").read_text(encoding="utf-8"))
    data = json.loads((table_dir / "data.json").read_text(encoding="utf-8"))

    return {
        "schema": schema,
        "preview": data[:limit],
        "total_rows": len(data),
    }


def search_ledgers(query: str, limit: int = 10) -> list[dict]:
    """Search across all ledgers by name, field name, or content."""
    query_lower = query.lower()
    results = []

    for entry in list_ledgers():
        score = 0
        # Match table name
        if query_lower in entry.get("name", "").lower():
            score += 10
        # Match field names
        matched_fields = []
        for fname, ftype in entry.get("field_types", {}).items():
            if query_lower in fname.lower():
                score += 3
                matched_fields.append(f"{fname} ({ftype})")

        if score > 0:
            table_dir = LEDGER_DIR / entry["id"]
            try:
                data = json.loads((table_dir / "data.json").read_text(encoding="utf-8"))
                # Search in data too
                data_matches = []
                for row in data[:50]:
                    for k, v in row.items():
                        if query_lower in str(v).lower():
                            data_matches.append({k: v})
                            break
                preview = data_matches[:3] if data_matches else data[:3]
            except Exception:
                preview = []

            results.append({
                "id": entry["id"],
                "name": entry["name"],
                "type": "ledger",
                "score": score,
                "fields": entry.get("field_names", []),
                "field_types": entry.get("field_types", {}),
                "rows_count": entry.get("rows_count", 0),
                "matched_fields": matched_fields,
                "preview": preview[:3],
                "import_time": entry.get("import_time", ""),
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


def delete_ledger(table_id: str) -> bool:
    """Delete a ledger table."""
    table_dir = LEDGER_DIR / table_id
    if not table_dir.exists():
        return False

    import shutil
    shutil.rmtree(table_dir)

    index = [e for e in list_ledgers() if e["id"] != table_id]
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def export_ledger(table_id: str, output_path: Optional[str] = None) -> str:
    """Export ledger as CSV."""
    table_dir = LEDGER_DIR / table_id
    if not table_dir.exists():
        raise FileNotFoundError(f"Ledger not found: {table_id}")

    schema = json.loads((table_dir / "schema.json").read_text(encoding="utf-8"))
    data = json.loads((table_dir / "data.json").read_text(encoding="utf-8"))
    fields = schema["fields"]

    out = output_path or f"{table_id}.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([f["display_name"] for f in fields])
        for row in data:
            writer.writerow([row.get(f["name"], "") for f in fields])
    return out


def main():
    parser = argparse.ArgumentParser(description="LLM Wiki Ledger — structured table management")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="Import CSV/Excel as ledger")
    imp.add_argument("file", help="CSV or XLSX file path")
    imp.add_argument("--name", help="Table display name")

    sub.add_parser("list", help="List all ledgers")

    show = sub.add_parser("show", help="Show ledger schema + preview")
    show.add_argument("id", help="Ledger table ID")
    show.add_argument("-n", "--limit", type=int, default=20, help="Preview rows")

    search = sub.add_parser("search", help="Search across ledgers")
    search.add_argument("query", help="Search query")
    search.add_argument("-n", "--limit", type=int, default=10, help="Max results")

    delete = sub.add_parser("delete", help="Delete a ledger")
    delete.add_argument("id", help="Ledger table ID")

    export = sub.add_parser("export", help="Export ledger as CSV")
    export.add_argument("id", help="Ledger table ID")
    export.add_argument("-o", "--output", help="Output CSV path")

    args = parser.parse_args()

    if args.command == "import":
        result = import_table(args.file, table_name=args.name)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "list":
        ledgers = list_ledgers()
        print(json.dumps(ledgers, indent=2, ensure_ascii=False))

    elif args.command == "show":
        result = show_ledger(args.id, limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "search":
        results = search_ledgers(args.query, limit=args.limit)
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))

    elif args.command == "delete":
        ok = delete_ledger(args.id)
        print(json.dumps({"deleted": ok, "id": args.id}))

    elif args.command == "export":
        out = export_ledger(args.id, output_path=args.output)
        print(f"Exported: {out}")


if __name__ == "__main__":
    main()
