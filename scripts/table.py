"""CLI façade for tables extracted from compiled Markdown pages."""

from __future__ import annotations

import argparse
import json

from ledger import cmd_list, cmd_show
from table_query import ask_table, get_table_schema


def _is_extracted(table: dict) -> bool:
    return str(table.get("description", "")).startswith("Extracted from ")


def list_tables() -> dict:
    result = cmd_list()
    if not result.get("success"):
        return result
    tables = [table for table in result.get("tables", []) if _is_extracted(table)]
    return {"success": True, "count": len(tables), "tables": tables}


def _require_extracted(table: str) -> dict | None:
    shown = cmd_show(table)
    if not shown.get("success"):
        return shown
    if not _is_extracted(shown.get("table", {})):
        return {
            "success": False,
            "error": f"'{table}' is not a table extracted during compilation.",
        }
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View and query Markdown tables extracted by wiki compile"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List extracted tables")
    show_parser = subparsers.add_parser("show", help="Show an extracted table")
    show_parser.add_argument("table")
    schema_parser = subparsers.add_parser("schema", help="Show an extracted table schema")
    schema_parser.add_argument("table")
    ask_parser = subparsers.add_parser("ask", help="Ask a natural-language question about a table")
    ask_parser.add_argument("table")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--page", type=int, default=1)
    ask_parser.add_argument("--page-size", type=int, default=20)
    args = parser.parse_args()

    if args.command == "list":
        result = list_tables()
    else:
        error = _require_extracted(args.table)
        if error:
            result = error
        elif args.command == "show":
            result = cmd_show(args.table)
        elif args.command == "schema":
            result = get_table_schema(args.table)
        else:
            result = ask_table(args.table, args.question, page=args.page, page_size=args.page_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
