#!/usr/bin/env python3
"""wiki.py — Unified CLI for LLM Wiki v2.

Commands:
    wiki init              Initialize wiki structure
    wiki compile <source>  Compile source file/directory → build wiki pages
    wiki query <question>  Search wiki → answer questions
    wiki lint              Health check → auto-heal
    wiki status            Show wiki statistics
    wiki config            Show current configuration
    wiki config --init     Create default config file
    wiki bulk <cmd>        Bulk operations (stats/clean/merge/export/delete)
    wiki consolidate       Memory tier consolidation
    wiki update            Update skill from GitHub (git pull + backup)

Usage:
    wiki compile source.md
    wiki query "What is X?"
    wiki lint --auto-heal
    wiki config
    wiki init
    
Environment Variables:
    LLM_WIKI_DIR     Override wiki directory path
    LLM_WIKI_CONFIG  Override config file path
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    CONFIG_FILENAME,
    create_default_config,
    get_api_url,
    get_config,
    get_wiki_dir,
    print_config,
    reset_config,
    validate_config,
)


def run_script(script_name: str, args: list[str]) -> tuple[int, str]:
    script_dir = Path(__file__).parent
    script_path = script_dir / script_name
    result = subprocess.run(
        [sys.executable, str(script_path)] + args,
        capture_output=True,
        text=True
    )
    output = result.stdout
    if result.stderr:
        output = output + result.stderr
    return result.returncode, output


def cmd_compile(
    source: str,
    source_type: str = "doc",
    force: bool = False,
    depth: int | None = None,
    dry_run: bool = False,
) -> dict:
    args = [source, "--type", source_type]
    if force:
        args.append("--force")
    if depth is not None:
        args.extend(["--depth", str(depth)])
    if dry_run:
        args.append("--dry-run")

    code, output = run_script("compile_v2.py", args)

    if code == 0:
        return {"success": True, "message": output.strip()}
    else:
        return {"success": False, "error": output}


def cmd_query(question: str, file_back: bool = False, fmt: str = "markdown",
              synthesis: bool = True, debug_search: bool = False) -> dict:
    # Direct import for speed — avoids subprocess overhead (~0.3s)
    try:
        import query as qm
        result = qm.query_wiki(question, file_back=file_back, fmt=fmt,
                               synthesis=synthesis,
                               debug_search=debug_search)
        answer = result.get("answer", "")
        if debug_search:
            answer += "\n\n--- SEARCH DEBUG ---\n"
            answer += json.dumps(result.get("debug_search", {}), indent=2, ensure_ascii=False, default=str)
        return {"success": True, "answer": answer}
    except Exception:
        # Fallback to subprocess on import failure
        args = [question]
        if file_back:
            args.append("--file-back")
        if fmt != "markdown":
            args.extend(["--format", fmt])
        if not synthesis:
            args.append("--no-synthesis")
        if debug_search:
            args.append("--debug-search")
        code, output = run_script("query.py", args)
        if code == 0:
            return {"success": True, "answer": output}
        else:
            return {"success": False, "error": output}


def cmd_lint(auto_heal: bool = False) -> dict:
    args = []
    if auto_heal:
        args.append("--auto-heal")

    code, output = run_script("lint.py", args)

    return {
        "success": code == 0,
        "output": output
    }

def cmd_consolidate(tiers: str = "working,episodic,semantic", decay_only: bool = False) -> dict:
    args = []
    if tiers != "working,episodic,semantic":
        args.extend(["--tiers", tiers])
    if decay_only:
        args.append("--decay-only")

    code, output = run_script("consolidate.py", args)

    return {
        "success": code == 0,
        "output": output
    }


def cmd_status() -> dict:
    wiki_dir = get_wiki_dir()
    pages_dir = wiki_dir / "pages"
    graph_dir = wiki_dir / "graph"
    concepts = list((pages_dir / "concepts").glob("*.md")) if (pages_dir / "concepts").exists() else []
    entities = list((pages_dir / "entities").glob("*.md")) if (pages_dir / "entities").exists() else []

    graph_file = graph_dir / "entities.json"
    entities_count = 0
    edges_count = 0

    if graph_file.exists():
        data = json.loads(graph_file.read_text())
        entities_count = len(data)

    edges_file = graph_dir / "edges.json"
    if edges_file.exists():
        edges_data = json.loads(edges_file.read_text())
        edges = edges_data.get("edges", edges_data) if isinstance(edges_data, dict) else edges_data
        edges_count = len(edges)

    return {
        "pages": {
            "concepts": len(concepts),
            "entities": len(entities),
            "total": len(concepts) + len(entities),
        },
        "graph": {
            "entities": entities_count,
            "edges": edges_count,
        },
        "files": {
            "index": (pages_dir / "index.md").exists(),
            "log": (wiki_dir / "log.md").exists(),
            "audit": (wiki_dir / "audit.json").exists(),
        }
    }


def cmd_init() -> dict:
    reset_config()
    wiki_dir = get_wiki_dir()
    pages_dir = wiki_dir / "pages"
    graph_dir = wiki_dir / "graph"
    dirs = [
        wiki_dir / "source" / "articles",
        wiki_dir / "source" / "documents",
        wiki_dir / "source" / "code",
        wiki_dir / "source" / "misc",
        pages_dir / "concepts",
        pages_dir / "entities",
        pages_dir / "sessions",
        graph_dir,
        wiki_dir / "ledger",
        wiki_dir / "memory",
        wiki_dir / "audit",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    index_file = pages_dir / "index.md"
    if not index_file.exists():
        index_file.write_text("# Wiki Index\n\nWelcome to your knowledge base.\n")

    schema_src = Path(__file__).parent.parent / "templates" / "schema.md"
    schema_dest = wiki_dir / "schema.md"
    if schema_src.exists() and not schema_dest.exists():
        import shutil
        shutil.copy2(schema_src, schema_dest)

    log_file = wiki_dir / "log.md"
    if not log_file.exists():
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        log_file.write_text(f"# Wiki Log\n\nChronological record of all wiki operations.\n\n## [{now}] init | wiki initialized\n")

    return {"success": True, "created": len(dirs), "wiki_dir": str(wiki_dir)}


def cmd_config(init: bool = False, show: bool = True, check: bool = False) -> dict:
    if init:
        dest = Path.cwd() / CONFIG_FILENAME
        if dest.exists():
            return {"success": False, "error": f"Config file already exists: {dest}"}
        try:
            create_default_config(dest)
            return {"success": True, "created": str(dest)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    if check:
        config = get_config()
        issues = validate_config(config)
        return {
            "success": len(issues) == 0,
            "valid": len(issues) == 0,
            "issues": issues,
            "checked": len(config),
        }

    if show:
        config = get_config()
        issues = validate_config(config)
        return {
            "success": True,
            "config": config,
            "wiki_dir": str(get_wiki_dir()),
            "api_url": get_api_url(),
            "issues": issues,
        }

    return {"success": True}


def main():
    parser = argparse.ArgumentParser(
        description="LLM Wiki v2 CLI — Personal knowledge base powered by LLMs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  wiki init                    Initialize wiki structure
  wiki config --init           Create default config file
  wiki config                  Show current configuration
  wiki compile paper.md        Compile document to wiki pages
    wiki query "What is X?"      Query wiki and get answer
    wiki search doctor           Diagnose retrieval indexes
  wiki lint --auto-heal        Health check with auto-repair

Environment:
  LLM_WIKI_DIR     Wiki directory path (default: .wiki)
  LLM_WIKI_CONFIG  Config file path (default: wiki_config.yaml)
        """
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize wiki structure")

    config_parser = subparsers.add_parser("config", help="Show or create configuration")
    config_parser.add_argument("--init", action="store_true", help="Create default config file")
    config_parser.add_argument("--check", action="store_true", help="Validate configuration and exit")

    compile_parser = subparsers.add_parser("compile", help="Compile source file/directory to wiki")
    compile_parser.add_argument("source", help="Source file or directory to compile")
    compile_parser.add_argument("--type", dest="source_type", default="doc",
                                choices=["doc", "article", "code", "conversation"],
                                help="Source type (controls entity focus)")
    compile_parser.add_argument("--force", action="store_true", help="Force re-compile")
    compile_parser.add_argument("--depth", type=int, default=None,
                                help="Directory recursion depth: 0 = direct files only, omit = all subdirectories")

    query_parser = subparsers.add_parser("query", help="Query wiki")
    query_parser.add_argument("question", help="Question to answer")
    query_parser.add_argument("--file-back", action="store_true", help="File answer to wiki")
    query_parser.add_argument("--format", choices=["markdown","table","timeline","slides","json","graph"],
                               default="markdown", help="Output format")
    query_parser.add_argument("--no-synthesis", action="store_true",
                               help="Skip LLM — return raw search results (fast)")
    query_parser.add_argument("--debug-search", action="store_true",
                               help="Print search trace for retrieval debugging")

    search_parser = subparsers.add_parser("search", help="Search diagnostics and evaluation")
    search_sub = search_parser.add_subparsers(dest="search_cmd", required=True)
    search_sub.add_parser("doctor", help="Diagnose retrieval index health")
    search_eval = search_sub.add_parser("eval", help="Evaluate retrieval from a jsonl file")
    search_eval.add_argument("file", help="Retrieval eval jsonl file")
    search_eval.add_argument("--limit", type=int, default=5, help="Top-k results to evaluate")

    benchmark_parser = subparsers.add_parser("benchmark", help="Run RAG benchmark")
    benchmark_parser.add_argument("file", help="Benchmark eval jsonl file")
    benchmark_parser.add_argument("--method", choices=["retrieval", "ragas-lite", "both"],
                                  default="both", help="Benchmark method")
    benchmark_parser.add_argument("-k", "--top-k", type=int, default=5, help="Top-k retrieval cutoff")
    benchmark_parser.add_argument("-o", "--output", help="Write result JSON")

    lint_parser = subparsers.add_parser("lint", help="Health check wiki")
    lint_parser.add_argument("--auto-heal", action="store_true", help="Auto-fix issues")

    bulk_parser = subparsers.add_parser("bulk", help="Bulk operations")
    bulk_sub = bulk_parser.add_subparsers(dest="bulk_cmd", required=True)
    bulk_sub.add_parser("stats", help="Detailed wiki statistics")
    clean_sub = bulk_sub.add_parser("clean", help="Clean orphan pages")
    clean_sub.add_argument("--dry-run", action="store_true", help="Preview only")
    merge_sub = bulk_sub.add_parser("merge", help="Merge duplicate entities")
    merge_sub.add_argument("--dry-run", action="store_true", help="Preview only")
    export_sub = bulk_sub.add_parser("export", help="Export wiki subset")
    export_sub.add_argument("--type", help="Entity type to export")
    del_sub = bulk_sub.add_parser("delete", help="Bulk delete pages")
    del_sub.add_argument("--stale", action="store_true", help="Delete stale pages")
    del_sub.add_argument("--confidence", type=float, help="Delete below confidence threshold")
    del_sub.add_argument("--dry-run", action="store_true", help="Preview only")

    # ── Ledger / 台账 ──────────────────────────────────────────────
    ledger_parser = subparsers.add_parser("ledger", help="Ledger/台账 management")
    ledger_sub = ledger_parser.add_subparsers(dest="ledger_cmd", required=True)

    ledger_sub.add_parser("list", help="List all tables")

    show_lp = ledger_sub.add_parser("show", help="Show table schema and data")
    show_lp.add_argument("table", help="Table name (display or actual)")

    create_lp = ledger_sub.add_parser("create", help="Create a new table")
    create_lp.add_argument("display_name", help="Display name for the table")
    create_lp.add_argument("--fields", required=True, help='Field definitions JSON')
    create_lp.add_argument("--unique", default=None, help="Unique key field(s)")
    create_lp.add_argument("--auto-increment", action="store_true", help="Add auto-increment _id field")
    create_lp.add_argument("--table-name", default=None, help="Override safe table name")
    create_lp.add_argument("--description", default="", help="Table description")

    insert_lp = ledger_sub.add_parser("insert", help="Insert data into a table")
    insert_lp.add_argument("table", help="Table name")
    insert_lp.add_argument("--data", required=True, help="JSON data (object or array)")
    insert_lp.add_argument("--batch", action="store_true", help="Continue on partial errors")

    update_lp = ledger_sub.add_parser("update-schema", help="Modify table schema")
    update_lp.add_argument("table", help="Table name")
    update_lp.add_argument("--add", default=None, help="Add fields JSON")
    update_lp.add_argument("--remove", default=None, help="Remove fields: name1,name2")
    update_lp.add_argument("--rename", default=None, help="Rename field: old:new")
    update_lp.add_argument("--modify", default=None, help="Change field type JSON")

    del_lp = ledger_sub.add_parser("delete", help="Delete a table")
    del_lp.add_argument("table", help="Table name")
    del_lp.add_argument("--keep-files", action="store_true", help="Keep files on disk")

    stats_lp = ledger_sub.add_parser("stats", help="Show table statistics")
    stats_lp.add_argument("table", nargs="?", default=None, help="Table name (omit for all)")

    schema_lp = ledger_sub.add_parser("schema", help="Show table schema for SQL generation")
    schema_lp.add_argument("table", help="Table name")

    sql_lp = ledger_sub.add_parser("sql", help="Execute raw SQL (read-only)")
    sql_lp.add_argument("sql_text", help="SQL SELECT statement")

    query_lp = ledger_sub.add_parser("query", help="Paginated SQL query on a table")
    query_lp.add_argument("table", help="Table name")
    query_lp.add_argument("--sql", required=True, help="SQL SELECT statement")
    query_lp.add_argument("--page", type=int, default=1, help="Page number")
    query_lp.add_argument("--page-size", type=int, default=20, help="Rows per page")

    traverse_lp = ledger_sub.add_parser("traverse", help="Batch traversal through table rows")
    traverse_lp.add_argument("table", help="Table name")
    traverse_lp.add_argument("--batch-size", type=int, default=100, help="Rows per batch")
    traverse_lp.add_argument("--offset", type=int, default=0, help="Starting offset")

    ask_lp = ledger_sub.add_parser("ask", help="Natural language question → SQL → results")
    ask_lp.add_argument("table", help="Table name")
    ask_lp.add_argument("question", help="Natural language question")
    ask_lp.add_argument("--page", type=int, default=1, help="Page number")
    ask_lp.add_argument("--page-size", type=int, default=20, help="Rows per page")

    ctx_lp = ledger_sub.add_parser("context", help="Prepare schema + function context for SQL generation")

    # Ledger import/export
    li = ledger_sub.add_parser("import", help="Import CSV/Excel file as ledger table")
    li.add_argument("file", help="CSV or XLSX file path")
    li.add_argument("--name", help="Table display name")
    lsk = ledger_sub.add_parser("search", help="Search across ledger tables (name/field/content)")
    lsk.add_argument("query", help="Search query")
    le = ledger_sub.add_parser("export", help="Export ledger table as CSV")
    le.add_argument("table", help="Table name to export")
    le.add_argument("-o", "--output", help="Output CSV path")
    ctx_lp.add_argument("table", help="Table name")
    ctx_lp.add_argument("question", help="Natural language question")

    cons_parser = subparsers.add_parser("consolidate", help="Consolidate memory tiers and apply decay")
    cons_parser.add_argument("--tiers", default="working,episodic,semantic", help="Tiers to consolidate")
    cons_parser.add_argument("--decay-only", action="store_true", help="Only apply retention decay")

    subparsers.add_parser("status", help="Show wiki statistics")
    subparsers.add_parser("update", help="Update skill from GitHub (git pull + backup)")

    args = parser.parse_args()

    if args.command == "init":
        result = cmd_init()
        print(f"Wiki initialized: {result['created']} directories created")
        print(f"Wiki directory: {result['wiki_dir']}")

    elif args.command == "config":
        result = cmd_config(init=args.init, check=getattr(args, 'check', False))
        if args.init:
            if result.get("success"):
                print(f"Config file created: {result['created']}")
                print("Edit the file to set your API key and preferences.")
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")
        else:
            print_config()

    elif args.command == "compile":
        result = cmd_compile(
            args.source,
            source_type=args.source_type,
            force=args.force,
            depth=args.depth,
        )
        if result.get("success"):
            print(result.get("message", "Done"))
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")

    elif args.command == "query":
        result = cmd_query(args.question, file_back=args.file_back, fmt=args.format,
                           synthesis=not args.no_synthesis,
                           debug_search=args.debug_search)
        if result.get("success"):
            print(result["answer"])
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")

    elif args.command == "search":
        search_args = ["--doctor"] if args.search_cmd == "doctor" else ["--eval", args.file, "--limit", str(args.limit)]
        code, output = run_script("search.py", search_args)
        print(output)
        if code != 0:
            sys.exit(code)

    elif args.command == "benchmark":
        benchmark_args = [args.file, "--method", args.method, "--top-k", str(args.top_k)]
        if args.output:
            benchmark_args.extend(["--output", args.output])
        code, output = run_script("benchmark.py", benchmark_args)
        print(output)
        if code != 0:
            sys.exit(code)

    elif args.command == "lint":
        result = cmd_lint(auto_heal=args.auto_heal)
        print(result["output"])

    elif args.command == "consolidate":
        result = cmd_consolidate(tiers=args.tiers, decay_only=args.decay_only)
        print(result["output"])

    elif args.command == "bulk":
        bulk_args = [args.bulk_cmd]
        if hasattr(args, 'dry_run') and args.dry_run:
            bulk_args.append("--dry-run")
        if hasattr(args, 'stale') and args.stale:
            bulk_args.append("--stale")
        if hasattr(args, 'confidence') and args.confidence is not None:
            bulk_args.extend(["--confidence", str(args.confidence)])
        if hasattr(args, 'type') and args.type:
            bulk_args.extend(["--type", args.type])
        code, output = run_script("bulk.py", bulk_args)
        print(output)

    elif args.command == "ledger":
        ledger_args = [args.ledger_cmd]
        if args.ledger_cmd == "show":
            ledger_args.append(args.table)
        elif args.ledger_cmd == "create":
            ledger_args.append(args.display_name)
            ledger_args.extend(["--fields", args.fields])
            if args.unique:
                ledger_args.extend(["--unique", args.unique])
            if args.auto_increment:
                ledger_args.append("--auto-increment")
            if args.table_name:
                ledger_args.extend(["--table-name", args.table_name])
            if args.description:
                ledger_args.extend(["--description", args.description])
        elif args.ledger_cmd == "insert":
            ledger_args.append(args.table)
            ledger_args.extend(["--data", args.data])
            if args.batch:
                ledger_args.append("--batch")
        elif args.ledger_cmd == "update-schema":
            ledger_args.append(args.table)
            if args.add:
                ledger_args.extend(["--add", args.add])
            if args.remove:
                ledger_args.extend(["--remove", args.remove])
            if args.rename:
                ledger_args.extend(["--rename", args.rename])
            if args.modify:
                ledger_args.extend(["--modify", args.modify])
        elif args.ledger_cmd == "delete":
            ledger_args.append(args.table)
            if args.keep_files:
                ledger_args.append("--keep-files")
        elif args.ledger_cmd == "stats":
            if args.table:
                ledger_args.append(args.table)
        elif args.ledger_cmd == "import":
            ledger_args.append(args.file)
            if args.name:
                ledger_args.extend(["--name", args.name])
        elif args.ledger_cmd == "search":
            ledger_args.append(args.query)
        elif args.ledger_cmd == "export":
            ledger_args.append(args.table)
            if args.output:
                ledger_args.extend(["-o", args.output])

        # Dispatch: table_query.py handles schema/sql/query/traverse/ask/context;
        # everything else goes to ledger.py
        if args.ledger_cmd in ("schema", "sql", "query", "traverse", "ask", "context"):
            tq_args = [args.ledger_cmd]
            if args.ledger_cmd == "schema":
                tq_args.append(args.table)
            elif args.ledger_cmd == "sql":
                tq_args.append(args.sql_text)
            elif args.ledger_cmd == "ask":
                tq_args.append(args.table)
                tq_args.append(args.question)
                tq_args.extend(["--page", str(args.page)])
                tq_args.extend(["--page-size", str(args.page_size)])
            elif args.ledger_cmd == "context":
                tq_args.append(args.table)
                tq_args.append(args.question)
            elif args.ledger_cmd == "query":
                tq_args.append(args.table)
                tq_args.extend(["--sql", args.sql])
                tq_args.extend(["--page", str(args.page)])
                tq_args.extend(["--page-size", str(args.page_size)])
            elif args.ledger_cmd == "traverse":
                tq_args.append(args.table)
                tq_args.extend(["--batch-size", str(args.batch_size)])
                tq_args.extend(["--offset", str(args.offset)])
            code, output = run_script("table_query.py", tq_args)
        else:
            code, output = run_script("ledger.py", ledger_args)
        print(output)
        if code != 0:
            sys.exit(code)

    elif args.command == "status":
        result = cmd_status()
        print(json.dumps(result, indent=2))

    elif args.command == "update":
        code, output = run_script("update.py", [])
        print(output)


if __name__ == "__main__":
    main()
