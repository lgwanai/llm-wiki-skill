#!/usr/bin/env python3
"""wiki.py — Unified CLI for LLM Wiki operations.

Commands:
    wiki add <source>     Add source to wiki (URL, file, or content)
    wiki update <target>  Update existing entity or source
    wiki query <query>    Search wiki
    wiki lint             Run quality checks
    wiki consolidate      Run memory consolidation
    wiki status           Show wiki statistics
    wiki init             Initialize wiki structure

Usage:
    python scripts/wiki.py add https://example.com
    python scripts/wiki.py add document.pdf
    python scripts/wiki.py add "some text to remember"
    python scripts/wiki.py query "React state management"
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WIKI_DIR = ".wiki"
SOURCE_DIR = os.path.join(WIKI_DIR, "source")
PAGES_DIR = os.path.join(WIKI_DIR, "pages")
GRAPH_DIR = os.path.join(WIKI_DIR, "graph")
MEMORY_DIR = os.path.join(WIKI_DIR, "memory")
AUDIT_DIR = os.path.join(WIKI_DIR, "audit")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}
OCR_EXTENSIONS = {".pdf"} | IMAGE_EXTENSIONS
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".epub"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".sh", ".bash", ".zsh",
}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}
TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".org", ".tex"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    import re
    return re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-').replace('_', '-'))


def _log_audit(op: str, details: dict) -> None:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    entry = {"op": op, **details, "ts": _now()}
    with open(os.path.join(AUDIT_DIR, "trail.jsonl"), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _run_command(cmd: list[str], capture: bool = True) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=capture, text=True)
    return result.returncode, result.stdout if capture else ""


def detect_input_type(source: str) -> tuple[str, str]:
    if source.startswith(("http://", "https://")):
        return "url", source
    if os.path.exists(source):
        ext = os.path.splitext(source)[1].lower()
        if ext in OCR_EXTENSIONS:
            return "ocr", source
        if ext in OFFICE_EXTENSIONS:
            return "office", source
        if ext in CODE_EXTENSIONS:
            return "code", source
        if ext in CONFIG_EXTENSIONS:
            return "config", source
        if ext in TEXT_EXTENSIONS:
            return "text", source
        if ext == ".html" or ext == ".htm":
            return "html", source
        return "file", source
    return "content", source


def cmd_add(source: str, embed: bool = True, source_type: str | None = None) -> dict:
    input_type, path_or_content = detect_input_type(source)
    os.makedirs(SOURCE_DIR, exist_ok=True)

    slug = _slugify(os.path.basename(source) if os.path.exists(source) else source[:50])

    if input_type == "url":
        output_path = os.path.join(SOURCE_DIR, "articles", f"{slug}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        code, _ = _run_command([
            sys.executable,
            os.path.join(script_dir, "url2markdown.py"),
            path_or_content,
            "--output", output_path,
        ])
        if code != 0:
            return {"error": f"Failed to fetch URL: {source}", "success": False}
        source_path = output_path
        actual_type = "article"

    elif input_type == "ocr":
        output_path = os.path.join(SOURCE_DIR, "documents", f"{slug}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        code, out = _run_command([
            sys.executable,
            os.path.join(script_dir, "ingest.py"),
            path_or_content,
            "--ocr",
            "--convert-only",
            "--output", output_path,
        ])
        if code != 0:
            return {"error": f"Failed to OCR: {source}", "success": False}
        source_path = output_path
        actual_type = "doc"

    elif input_type in ("office", "html"):
        output_path = os.path.join(SOURCE_DIR, "documents", f"{slug}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        code, _ = _run_command([
            sys.executable,
            os.path.join(script_dir, "ingest.py"),
            path_or_content,
            "--convert-only",
            "--output", output_path,
        ])
        if code != 0:
            return {"error": f"Failed to convert: {source}", "success": False}
        source_path = output_path
        actual_type = "doc"

    elif input_type in ("code", "config"):
        output_path = os.path.join(SOURCE_DIR, "code", f"{slug}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        code, _ = _run_command([
            sys.executable,
            os.path.join(script_dir, "ingest.py"),
            path_or_content,
            "--copy",
            "--output", output_path,
        ])
        if code != 0:
            return {"error": f"Failed to copy: {source}", "success": False}
        source_path = output_path
        actual_type = "code"

    elif input_type == "text":
        output_path = os.path.join(SOURCE_DIR, "misc", f"{slug}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        code, _ = _run_command([
            sys.executable,
            os.path.join(script_dir, "ingest.py"),
            path_or_content,
            "--copy",
            "--output", output_path,
        ])
        if code != 0:
            return {"error": f"Failed to copy: {source}", "success": False}
        source_path = output_path
        actual_type = source_type or "article"

    else:
        output_path = os.path.join(SOURCE_DIR, "misc", f"{slug}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        header = f"---\nsource: raw-content\nadded_at: {_now()}\ntype: source\n---\n\n"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(header + path_or_content)
        source_path = output_path
        actual_type = source_type or "article"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    ingest_cmd = [
        sys.executable,
        os.path.join(script_dir, "ingest.py"),
        source_path,
        "--type", actual_type,
    ]
    if embed:
        ingest_cmd.append("--embed")

    code, out = _run_command(ingest_cmd)
    if code != 0:
        return {"error": f"Failed to ingest: {source_path}", "success": False}

    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        result = {"raw_output": out}

    _log_audit("add", {"source": source, "type": input_type, "output": source_path})

    return {
        "success": True,
        "source": source,
        "detected_type": input_type,
        "stored_at": source_path,
        "ingest_result": result,
    }


def cmd_update(target: str, content: str | None = None) -> dict:
    if target.startswith("entity/"):
        entity_name = target[7:]
        entity_path = os.path.join(PAGES_DIR, "entities", f"{entity_name}.md")
        if not os.path.exists(entity_path):
            return {"error": f"Entity not found: {entity_name}", "success": False}

    elif target.startswith("source/"):
        source_name = target[7:]
        source_path = os.path.join(SOURCE_DIR, source_name)
        if not os.path.exists(source_path):
            for subdir in ["articles", "documents", "code", "misc"]:
                candidate = os.path.join(SOURCE_DIR, subdir, source_name)
                if os.path.exists(candidate):
                    source_path = candidate
                    break
            else:
                return {"error": f"Source not found: {source_name}", "success": False}

    else:
        for subdir in ["articles", "documents", "code", "misc"]:
            candidate = os.path.join(SOURCE_DIR, subdir, f"{_slugify(target)}.md")
            if os.path.exists(candidate):
                source_path = candidate
                break
        else:
            return {"error": f"Target not found: {target}", "success": False}

    _log_audit("update", {"target": target, "content_provided": content is not None})

    return {
        "success": True,
        "target": target,
        "message": "Update functionality requires interactive mode",
    }


def cmd_query(query: str) -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(script_dir, "search.py"), query]

    code, out = _run_command(cmd)
    if code != 0:
        return {"error": "Search failed", "success": False}

    try:
        return {"success": True, "results": json.loads(out)}
    except json.JSONDecodeError:
        return {"success": True, "raw_output": out}


def cmd_lint(fix: bool = False) -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(script_dir, "lint.py")]
    if fix:
        cmd.append("--fix")

    code, out = _run_command(cmd)

    _log_audit("lint", {"fix": fix, "exit_code": code})

    try:
        return {"success": code == 0, "results": json.loads(out)}
    except json.JSONDecodeError:
        return {"success": code == 0, "raw_output": out}


def cmd_consolidate() -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(script_dir, "consolidate.py")]

    code, out = _run_command(cmd)

    _log_audit("consolidate", {"exit_code": code})

    try:
        return {"success": code == 0, "results": json.loads(out)}
    except json.JSONDecodeError:
        return {"success": code == 0, "raw_output": out}


def cmd_compile(embed: bool = False, full: bool = False) -> dict:
    """Regenerate ALL wiki pages from graph data and source files.

    This is the main compilation step — it rebuilds entity pages, concept pages,
    index.md, and log.md from the knowledge graph. Source → Graph → Pages → Index.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not os.path.isdir(WIKI_DIR):
        return {"error": "Wiki not initialized. Run 'wiki init' first.", "success": False}

    result = {
        "success": True,
        "entity_pages": 0,
        "concept_pages": 0,
        "edges_rebuilt": 0,
        "index_regenerated": False,
        "log_regenerated": False,
        "embeddings": 0,
    }

    graph_script = os.path.join(script_dir, "graph.py")
    ingest_script = os.path.join(script_dir, "ingest.py")

    # Phase 1: Rebuild graph from existing pages
    print("Phase 1: Rebuilding knowledge graph from existing pages...", file=sys.stderr)
    code, out = _run_command([sys.executable, graph_script, "build"])
    if code == 0:
        try:
            graph_result = json.loads(out)
            result["entities_found"] = graph_result.get("entities", 0)
            result["edges_rebuilt"] = graph_result.get("edges", 0)
            print(f"  Graph: {result['entities_found']} entities, {result['edges_rebuilt']} edges", file=sys.stderr)
        except json.JSONDecodeError:
            pass

    # Phase 2: Re-ingest all source files to regenerate entity/concept pages
    print("Phase 2: Regenerating entity and concept pages from sources...", file=sys.stderr)
    sources_dir = Path(SOURCE_DIR)
    if sources_dir.exists():
        source_files = list(sources_dir.rglob("*.md"))
        for sf in sorted(source_files):
            try:
                code, _ = _run_command([
                    sys.executable, ingest_script,
                    str(sf), "--embed" if embed else "",
                ])
                if code == 0:
                    result["entity_pages"] += 1
                    result["concept_pages"] += 1
            except Exception as e:
                print(f"  Warning: failed to process {sf}: {e}", file=sys.stderr)
        print(f"  Processed {len(source_files)} source files", file=sys.stderr)

    if full:
        print("Phase 3 (full): LLM concept page generation...", file=sys.stderr)
        entities_file = os.path.join(GRAPH_DIR, "entities.json")
        if os.path.exists(entities_file):
            with open(entities_file, encoding="utf-8") as f:
                registry = json.load(f)
            all_concepts = [e for e in registry.values() if isinstance(e, dict) and e.get("type") == "concept"]
            if all_concepts:
                for sf in sorted(sources_dir.rglob("*.md")) if sources_dir.exists() else []:
                    try:
                        content = sf.read_text(encoding="utf-8")
                        from ingest import _generate_concept_pages as gen_pages
                        count = gen_pages(all_concepts, content, sf.name)
                        result["concept_pages"] += count
                    except Exception:
                        pass

    # Phase 4: Rebuild index and log
    print("Phase 4: Rebuilding index.md and log.md...", file=sys.stderr)
    try:
        from ingest import _rebuild_index
        _rebuild_index()
        result["index_regenerated"] = True
    except Exception as e:
        print(f"  Warning: index rebuild failed: {e}", file=sys.stderr)

    # Rebuild log from audit trail
    try:
        _rebuild_log_from_audit()
        result["log_regenerated"] = True
    except Exception as e:
        print(f"  Warning: log rebuild failed: {e}", file=sys.stderr)

    print("  Index and log regenerated", file=sys.stderr)

    # Phase 5: Generate embeddings if requested
    if embed:
        print("Phase 5: Generating entity embeddings...", file=sys.stderr)
        entities_file = os.path.join(GRAPH_DIR, "entities.json")
        if os.path.exists(entities_file):
            with open(entities_file, encoding="utf-8") as f:
                registry = json.load(f)
            from ingest import _embed_entities
            result["embeddings"] = _embed_entities(registry)
            print(f"  Generated {result['embeddings']} embeddings", file=sys.stderr)

    _log_audit("compile", result)

    return result


def _rebuild_log_from_audit() -> None:
    """Regenerate log.md from audit trail entries."""
    audit_path = os.path.join(AUDIT_DIR, "trail.jsonl")
    log_path = os.path.join(WIKI_DIR, "log.md")

    lines = ["# Wiki Log", "", "Chronological record of all wiki operations.", ""]
    if os.path.exists(audit_path):
        with open(audit_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    op = entry.get("op", "unknown")
                    ts = entry.get("ts", "")[:19].replace("T", " ")
                    source = entry.get("source", "")
                    entity_count = entry.get("entities_new", entry.get("entity_count", 0))
                    edge_count = entry.get("edges_created", entry.get("edge_count", 0))
                    lines.append(f"## [{ts}] {op} | {source}")
                    if entity_count or edge_count:
                        lines.append(f"- Entities: {entity_count} | Edges: {edge_count}")
                    lines.append("")
                except (json.JSONDecodeError, KeyError):
                    continue

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))


def cmd_status() -> dict:
    stats = {
        "wiki_dir_exists": os.path.exists(WIKI_DIR),
        "entities": 0,
        "sources": 0,
        "pages": 0,
        "recent_activity": [],
    }

    if os.path.exists(GRAPH_DIR):
        entities_file = os.path.join(GRAPH_DIR, "entities.json")
        if os.path.exists(entities_file):
            with open(entities_file, encoding='utf-8') as f:
                data = json.load(f)
                stats["entities"] = len(data) if isinstance(data, dict) else 0

    if os.path.exists(SOURCE_DIR):
        for subdir in ["articles", "documents", "code", "misc"]:
            subdir_path = os.path.join(SOURCE_DIR, subdir)
            if os.path.exists(subdir_path):
                stats["sources"] += len([f for f in os.listdir(subdir_path) if f.endswith('.md')])

    if os.path.exists(PAGES_DIR):
        for root, _, files in os.walk(PAGES_DIR):
            stats["pages"] += len([f for f in files if f.endswith('.md')])

    audit_file = os.path.join(AUDIT_DIR, "trail.jsonl")
    if os.path.exists(audit_file):
        with open(audit_file, encoding='utf-8') as f:
            lines = f.readlines()[-5:]
            stats["recent_activity"] = [json.loads(line) for line in lines if line.strip()]

    return {"success": True, **stats}


def cmd_init(template: str | None = None) -> dict:
    dirs = [
        os.path.join(SOURCE_DIR, subdir)
        for subdir in ["articles", "documents", "code", "misc"]
    ] + [
        os.path.join(PAGES_DIR, subdir)
        for subdir in ["entities", "concepts", "decisions", "sessions", "patterns"]
    ] + [GRAPH_DIR, MEMORY_DIR, AUDIT_DIR]

    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # schema.md
    schema_path = os.path.join(WIKI_DIR, "schema.md")
    if not os.path.exists(schema_path):
        with open(schema_path, 'w', encoding='utf-8') as f:
            f.write("# Wiki Schema\n\n")
            f.write("## Entity Types\n\n")
            f.write("## Relationship Types\n\n")
            f.write("## Quality Standards\n")

    # config.json
    config_path = os.path.join(WIKI_DIR, "config.json")
    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump({
                "hooks": {
                    "on_new_source": {"enabled": True, "auto_ingest": True},
                    "on_session_end": {"enabled": True, "auto_crystallize": True},
                },
                "retention": {
                    "architecture_decisions": {"half_life_days": 180},
                    "project_facts": {"half_life_days": 90},
                },
                "quality": {"auto_heal": True, "min_score": 0.4},
            }, f, indent=2)

    # index.md
    index_path = os.path.join(PAGES_DIR, "index.md")
    if not os.path.exists(index_path):
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write("# Wiki Index\n\nWelcome to your knowledge base.\n")

    # log.md — chronological operation record (Karpathy pattern)
    log_path = os.path.join(WIKI_DIR, "log.md")
    if not os.path.exists(log_path):
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("# Wiki Log\n\n")
            f.write("Chronological record of all wiki operations.\n\n")
            f.write(f"## [{now_utc}] init | wiki initialized\n")
            f.write("- Wiki structure created\n")
            f.write("- Schema, config, index, and log initialized\n\n")

    _log_audit("init", {"template": template})

    return {
        "success": True,
        "created_dirs": len(dirs),
        "created_files": ["schema.md", "config.json", "pages/index.md", "log.md"],
    }


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM Wiki CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  wiki add https://example.com/article
  wiki add document.pdf
  wiki add "important note to remember"
  wiki query "React hooks"
  wiki lint
  wiki status
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add source to wiki")
    add_parser.add_argument("source", help="URL, file path, or content to add")
    add_parser.add_argument("--no-embed", action="store_true", help="Skip embedding generation")
    add_parser.add_argument("--type", help="Source type (article, code, doc, conversation)")

    update_parser = subparsers.add_parser("update", help="Update wiki content")
    update_parser.add_argument("target", help="Target to update (entity/name or source/slug)")
    update_parser.add_argument("--content", help="New content to merge")

    query_parser = subparsers.add_parser("query", help="Search wiki")
    query_parser.add_argument("query", help="Search query")

    lint_parser = subparsers.add_parser("lint", help="Run quality checks")
    lint_parser.add_argument("--fix", action="store_true", help="Auto-fix issues")

    subparsers.add_parser("consolidate", help="Run memory consolidation")
    subparsers.add_parser("status", help="Show wiki statistics")

    compile_parser = subparsers.add_parser("compile", help="Regenerate all wiki pages from graph data")
    compile_parser.add_argument("--embed", action="store_true", help="Generate Ollama embeddings")
    compile_parser.add_argument("--full", action="store_true", help="Full LLM regeneration of concept pages")

    init_parser = subparsers.add_parser("init", help="Initialize wiki structure")
    init_parser.add_argument("--template", help="Schema template file")

    args = parser.parse_args()

    if args.command == "add":
        result = cmd_add(args.source, embed=not args.no_embed, source_type=args.type)
    elif args.command == "update":
        result = cmd_update(args.target, content=args.content)
    elif args.command == "query":
        result = cmd_query(args.query)
    elif args.command == "lint":
        result = cmd_lint(fix=args.fix)
    elif args.command == "consolidate":
        result = cmd_consolidate()
    elif args.command == "compile":
        result = cmd_compile(embed=args.embed, full=args.full)
    elif args.command == "status":
        result = cmd_status()
    elif args.command == "init":
        result = cmd_init(template=args.template)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
