#!/usr/bin/env python3
"""generate_embeddings.py — Generate vector embeddings for all wiki pages.

Uses Ollama (qwen3-embedding:8b) for local embedding generation.
writes to .wiki/graph/embeddings.json for hybrid search.

Usage:
    python3 scripts/generate_embeddings.py              # all pages
    python3 scripts/generate_embeddings.py --page id    # single page
    python3 scripts/generate_embeddings.py --verify     # check status
"""

import argparse
import json
import sys
from pathlib import Path

WIKI_DIR = Path(__file__).parent.parent / ".wiki"
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
EMBEDDINGS_FILE = GRAPH_DIR / "embeddings.json"


def read_page_content(page_path: Path) -> str:
    if not page_path.exists():
        return ""
    content = page_path.read_text(encoding="utf-8")
    if content.startswith("---"):
        lines = content.split("\n")
        end = 0
        for i, line in enumerate(lines):
            if i > 0 and line.strip() == "---":
                end = i
                break
        if end > 0:
            content = "\n".join(lines[end + 1:])
    return content.strip()[:3000]


def generate_all(force: bool = False) -> dict:
    from _ollama import get_embedding

    if not PAGES_DIR.exists():
        return {"status": "error", "message": "No wiki pages found. Run compile first."}

    existing = {}
    if EMBEDDINGS_FILE.exists() and not force:
        existing = json.loads(EMBEDDINGS_FILE.read_text(encoding="utf-8"))

    pages = []
    for subdir in ["concepts", "entities", "sessions", "decisions", "patterns"]:
        d = PAGES_DIR / subdir
        if d.exists():
            pages.extend(d.glob("*.md"))

    generated = 0
    skipped = 0
    failed = 0
    embeddings = dict(existing) if not force else {}

    for page_path in sorted(pages):
        page_id = page_path.stem
        if page_id in embeddings and not force:
            skipped += 1
            continue

        content = read_page_content(page_path)
        if not content:
            failed += 1
            continue

        emb = get_embedding(content)
        if emb is None:
            failed += 1
            print(f"  ⚠ failed: {page_id}", file=sys.stderr)
            continue

        embeddings[page_id] = emb
        generated += 1
        if generated % 5 == 0:
            print(f"  {generated}/{len(pages)} pages...", file=sys.stderr)

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_FILE.write_text(json.dumps(embeddings, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "ok",
        "total_pages": len(pages),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "total_embeddings": len(embeddings),
    }


def generate_one(page_id: str) -> dict:
    from _ollama import get_embedding

    for subdir in ["concepts", "entities", "sessions", "decisions", "patterns"]:
        page_path = PAGES_DIR / subdir / f"{page_id}.md"
        if page_path.exists():
            break
    else:
        return {"status": "error", "message": f"Page not found: {page_id}"}

    content = read_page_content(page_path)
    if not content:
        return {"status": "error", "message": f"Empty content: {page_id}"}

    emb = get_embedding(content)
    if emb is None:
        return {"status": "error", "message": "Embedding generation failed"}

    embeddings = {}
    if EMBEDDINGS_FILE.exists():
        embeddings = json.loads(EMBEDDINGS_FILE.read_text(encoding="utf-8"))

    embeddings[page_id] = emb
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_FILE.write_text(json.dumps(embeddings, ensure_ascii=False), encoding="utf-8")

    return {"status": "ok", "page": page_id, "dimensions": len(emb)}


def verify_status() -> dict:
    if not EMBEDDINGS_FILE.exists():
        return {"status": "empty", "embeddings": 0, "needs_generation": True}

    embeddings = json.loads(EMBEDDINGS_FILE.read_text(encoding="utf-8"))

    pages = []
    for subdir in ["concepts", "entities", "sessions"]:
        d = PAGES_DIR / subdir
        if d.exists():
            pages.extend(d.glob("*.md"))

    page_ids = {p.stem for p in pages}
    embedded_ids = set(embeddings.keys())

    return {
        "status": "ok",
        "total_pages": len(page_ids),
        "total_embeddings": len(embedded_ids),
        "missing": sorted(page_ids - embedded_ids),
        "coverage_pct": round(len(embedded_ids & page_ids) / max(len(page_ids), 1) * 100, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate vector embeddings for wiki pages")
    parser.add_argument("--page", help="Generate embedding for a single page")
    parser.add_argument("--force", action="store_true", help="Regenerate all embeddings")
    parser.add_argument("--verify", action="store_true", help="Check embedding status")
    args = parser.parse_args()

    if args.verify:
        result = verify_status()
    elif args.page:
        result = generate_one(args.page)
    else:
        result = generate_all(force=args.force)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
