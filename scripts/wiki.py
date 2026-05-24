#!/usr/bin/env python3
"""wiki.py — Unified CLI for LLM Wiki v2.

Commands:
    wiki compile <source>  Compile source → build wiki pages
    wiki query <question>  Search wiki → answer questions
    wiki lint              Health check → auto-heal
    wiki status            Show wiki statistics
    wiki init              Initialize wiki structure

Usage:
    python scripts/wiki.py compile source.md
    python scripts/wiki.py query "What is X?"
    python scripts/wiki.py lint --auto-heal
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure scripts/ is importable for direct module calls
sys.path.insert(0, str(Path(__file__).parent))

WIKI_DIR = Path(os.environ.get("LLM_WIKI_DIR", str(Path(__file__).parent.parent / ".wiki")))
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"


def run_script(script_name: str, args: list[str]) -> tuple[int, str]:
    script_dir = Path(__file__).parent
    script_path = script_dir / script_name
    result = subprocess.run(
        [sys.executable, str(script_path)] + args,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout


def cmd_compile(source: str, source_type: str = "doc", force: bool = False) -> dict:
    args = [source, "--type", source_type]
    if force:
        args.append("--force")

    code, output = run_script("compile_v2.py", args)

    if code == 0:
        return {"success": True, "message": output.strip()}
    else:
        return {"success": False, "error": output}


def cmd_query(question: str, file_back: bool = False, fmt: str = "markdown",
              synthesis: bool = True) -> dict:
    # Direct import for speed — avoids subprocess overhead (~0.3s)
    try:
        import query as qm
        result = qm.query_wiki(question, file_back=file_back, fmt=fmt,
                               synthesis=synthesis)
        return {"success": True, "answer": result.get("answer", "")}
    except Exception as e:
        # Fallback to subprocess on import failure
        args = [question]
        if file_back:
            args.append("--file-back")
        if fmt != "markdown":
            args.extend(["--format", fmt])
        if not synthesis:
            args.append("--no-synthesis")
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
    pages_dir = PAGES_DIR
    concepts = list((pages_dir / "concepts").glob("*.md")) if (pages_dir / "concepts").exists() else []
    entities = list((pages_dir / "entities").glob("*.md")) if (pages_dir / "entities").exists() else []

    graph_file = GRAPH_DIR / "entities.json"
    entities_count = 0
    edges_count = 0

    if graph_file.exists():
        data = json.loads(graph_file.read_text())
        entities_count = len(data)

    edges_file = GRAPH_DIR / "edges.json"
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
            "log": (WIKI_DIR / "log.md").exists(),
            "audit": (WIKI_DIR / "audit.json").exists(),
        }
    }


def cmd_init() -> dict:
    dirs = [
        WIKI_DIR / "source" / "articles",
        WIKI_DIR / "source" / "documents",
        WIKI_DIR / "source" / "code",
        WIKI_DIR / "source" / "misc",
        PAGES_DIR / "concepts",
        PAGES_DIR / "entities",
        PAGES_DIR / "sessions",
        GRAPH_DIR,
        WIKI_DIR / "memory",
        WIKI_DIR / "audit",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    index_file = PAGES_DIR / "index.md"
    if not index_file.exists():
        index_file.write_text("# Wiki Index\n\nWelcome to your knowledge base.\n")
    
    schema_src = Path(__file__).parent.parent / "templates" / "schema.md"
    schema_dest = WIKI_DIR / "schema.md"
    if schema_src.exists() and not schema_dest.exists():
        import shutil
        shutil.copy2(schema_src, schema_dest)
        
    log_file = WIKI_DIR / "log.md"
    if not log_file.exists():
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        log_file.write_text(f"# Wiki Log\n\nChronological record of all wiki operations.\n\n## [{now}] init | wiki initialized\n")

    return {"success": True, "created": len(dirs)}


def main():
    parser = argparse.ArgumentParser(description="LLM Wiki v2 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="Compile source to wiki")
    compile_parser.add_argument("source", help="Source file to compile")
    compile_parser.add_argument("--type", dest="source_type", default="doc",
                                choices=["doc", "article", "code", "conversation"],
                                help="Source type (controls entity focus)")
    compile_parser.add_argument("--force", action="store_true", help="Force re-compile")

    query_parser = subparsers.add_parser("query", help="Query wiki")
    query_parser.add_argument("question", help="Question to answer")
    query_parser.add_argument("--file-back", action="store_true", help="File answer to wiki")
    query_parser.add_argument("--format", choices=["markdown","table","timeline","slides","json","graph"],
                               default="markdown", help="Output format")
    query_parser.add_argument("--no-synthesis", action="store_true",
                               help="Skip LLM — return raw search results (fast)")

    lint_parser = subparsers.add_parser("lint", help="Health check wiki")
    lint_parser.add_argument("--auto-heal", action="store_true", help="Auto-fix issues")

    embed_parser = subparsers.add_parser("embed", help="Generate vector embeddings")
    embed_parser.add_argument("--force", action="store_true", help="Regenerate all embeddings")

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
    
    cons_parser = subparsers.add_parser("consolidate", help="Consolidate memory tiers and apply decay")
    cons_parser.add_argument("--tiers", default="working,episodic,semantic", help="Tiers to consolidate")
    cons_parser.add_argument("--decay-only", action="store_true", help="Only apply retention decay")

    subparsers.add_parser("status", help="Show wiki statistics")
    subparsers.add_parser("init", help="Initialize wiki structure")

    args = parser.parse_args()

    if args.command == "compile":
        result = cmd_compile(args.source, source_type=args.source_type, force=args.force)
        if result.get("success"):
            print(result.get("message", "Done"))
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")

    elif args.command == "query":
        result = cmd_query(args.question, file_back=args.file_back, fmt=args.format,
                           synthesis=not args.no_synthesis)
        if result.get("success"):
            print(result["answer"])
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")

    elif args.command == "lint":
        result = cmd_lint(auto_heal=args.auto_heal)
        print(result["output"])

    elif args.command == "embed":
        code, output = run_script("generate_embeddings.py",
                                   ["--force"] if args.force else [])
        print(output)
    
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

    elif args.command == "status":
        result = cmd_status()
        print(json.dumps(result, indent=2))

    elif args.command == "init":
        result = cmd_init()
        print(f"Wiki initialized: {result['created']} directories created")


if __name__ == "__main__":
    main()
