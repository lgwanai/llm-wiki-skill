#!/usr/bin/env python3
"""generate_embeddings.py — Generate vector embeddings for all wiki pages.

Supports two modes:
  - local: Use sentence-transformers or Ollama for local embedding
  - api: Use remote embedding API (OpenAI, DeepSeek, etc.)

Writes to .wiki/graph/embeddings.json for hybrid search.

Usage:
    python3 scripts/generate_embeddings.py              # all pages
    python3 scripts/generate_embeddings.py --page id    # single page
    python3 scripts/generate_embeddings.py --verify     # check status
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import get_config, get_wiki_dir

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
EMBEDDINGS_FILE = GRAPH_DIR / "embeddings.json"
CHUNK_EMBEDDINGS_FILE = GRAPH_DIR / "chunk_embeddings.json"
CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
EMBEDDING_SCHEMA_VERSION = 2


def get_embeddings_config() -> dict:
    """Get embeddings configuration from wiki_config.yaml."""
    config = get_config()
    return config.get("embeddings", {
        "mode": "local",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "dimension": 384,
        "backend": "faiss",
    })


def embedding_index_meta(config: Optional[dict] = None, actual_dimension: Optional[int] = None) -> dict:
    """Return metadata describing the current embedding configuration."""
    config = config or get_embeddings_config()
    mode = config.get("mode", "local")
    model = config.get("api_model") if mode == "api" else config.get("model")
    model = model or config.get("model", "")
    return {
        "schema_version": EMBEDDING_SCHEMA_VERSION,
        "mode": mode,
        "model": model,
        "dimension": actual_dimension or config.get("dimension"),
        "backend": config.get("backend", ""),
    }


def load_embedding_index(path: Path = EMBEDDINGS_FILE) -> tuple[dict, dict]:
    """Load embeddings as (meta, items), accepting the legacy flat format."""
    if not path.exists():
        return {}, {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        items = data.get("items", {})
        return data.get("_meta", {}), items if isinstance(items, dict) else {}

    if isinstance(data, dict):
        # Legacy format: {page_id: embedding}
        return {}, data

    return {}, {}


def write_embedding_index(items: dict, path: Path = EMBEDDINGS_FILE) -> None:
    """Write embeddings with config metadata."""
    actual_dimension = None
    for emb in items.values():
        if isinstance(emb, dict):
            emb = emb.get("embedding")
        if isinstance(emb, list) and emb:
            actual_dimension = len(emb)
            break
    meta = embedding_index_meta(actual_dimension=actual_dimension)
    meta["created_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"_meta": meta, "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )


def embedding_index_status(path: Path = EMBEDDINGS_FILE) -> dict:
    """Check whether the embedding index exists and matches current config."""
    if not path.exists():
        return {
            "exists": False,
            "stale": True,
            "reason": "embedding index missing",
            "current": embedding_index_meta(),
            "index": {},
            "items": 0,
        }

    meta, items = load_embedding_index(path)
    current = embedding_index_meta()
    comparable_keys = ("schema_version", "mode", "model", "dimension")
    mismatches = {
        key: {"index": meta.get(key), "current": current.get(key)}
        for key in comparable_keys
        if meta.get(key) != current.get(key)
    }
    return {
        "exists": True,
        "stale": bool(mismatches),
        "reason": "config mismatch" if mismatches else "",
        "current": current,
        "index": meta,
        "mismatches": mismatches,
        "items": len(items),
    }


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


def get_embedding_local(text: str, model: str) -> Optional[list[float]]:
    """Generate embedding using local model."""
    if model.startswith("ollama:"):
        model_name = model.replace("ollama:", "")
        return get_embedding_ollama(text, model_name)
    
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(model)
        emb = _model.encode(text, convert_to_numpy=True)
        return emb.tolist()
    except ImportError:
        print("Install sentence-transformers: pip install sentence-transformers", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Local embedding error: {e}", file=sys.stderr)
        return None


def get_embedding_ollama(text: str, model: str) -> Optional[list[float]]:
    """Generate embedding using Ollama."""
    import requests
    
    try:
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        resp = requests.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception as e:
        print(f"Ollama embedding error: {e}", file=sys.stderr)
        return None


def get_embedding_api(text: str, config: dict) -> Optional[list[float]]:
    """Generate embedding using remote API."""
    import requests
    
    api_url = config.get("api_url", "")
    api_key = config.get("api_key", "")
    api_model = config.get("api_model") or config.get("model") or "text-embedding-3-small"
    
    if not api_url:
        print("Error: embeddings.api_url not configured", file=sys.stderr)
        return None
    
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    try:
        resp = requests.post(
            api_url,
            headers=headers,
            json={"model": api_model, "input": text},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [{}])[0].get("embedding")
    except Exception as e:
        print(f"API embedding error: {e}", file=sys.stderr)
        return None


def get_embedding(text: str) -> Optional[list[float]]:
    """Generate embedding based on configuration."""
    config = get_embeddings_config()
    mode = config.get("mode", "local")
    model = config.get("model", "sentence-transformers/all-MiniLM-L6-v2")
    
    if mode == "api":
        return get_embedding_api(text, config)
    else:
        return get_embedding_local(text, model)


def generate_all(force: bool = False) -> dict:
    if not PAGES_DIR.exists():
        return {"status": "error", "message": "No wiki pages found. Run compile first."}

    existing = {}
    if EMBEDDINGS_FILE.exists() and not force:
        _, existing = load_embedding_index(EMBEDDINGS_FILE)

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

    write_embedding_index(embeddings, EMBEDDINGS_FILE)

    return {
        "status": "ok",
        "total_pages": len(pages),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "total_embeddings": len(embeddings),
    }


def generate_chunks(force: bool = False) -> dict:
    """Generate embeddings for heading-aware page chunks."""
    if not PAGES_DIR.exists():
        return {"status": "error", "message": "No wiki pages found. Run compile first."}

    try:
        from search import build_chunk_index
    except Exception as e:
        return {"status": "error", "message": f"Chunk index unavailable: {e}"}

    chunks = build_chunk_index(PAGES_DIR)
    existing = {}
    if CHUNK_EMBEDDINGS_FILE.exists() and not force:
        _, existing = load_embedding_index(CHUNK_EMBEDDINGS_FILE)

    generated = 0
    skipped = 0
    failed = 0
    items = dict(existing) if not force else {}

    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            failed += 1
            continue
        if chunk_id in items and not force:
            skipped += 1
            continue
        text = chunk.get("text", "").strip()
        if not text:
            failed += 1
            continue
        emb = get_embedding(text[:3000])
        if emb is None:
            failed += 1
            print(f"  ⚠ failed chunk: {chunk_id}", file=sys.stderr)
            continue
        items[chunk_id] = {
            "embedding": emb,
            "page_id": chunk.get("page_id", ""),
            "path": chunk.get("path", ""),
            "heading_path": chunk.get("heading_path", []),
            "text": text[:1200],
        }
        generated += 1
        if generated % 10 == 0:
            print(f"  {generated}/{len(chunks)} chunks...", file=sys.stderr)

    write_embedding_index(items, CHUNK_EMBEDDINGS_FILE)

    return {
        "status": "ok",
        "total_chunks": len(chunks),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "total_embeddings": len(items),
    }


def generate_one(page_id: str) -> dict:
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
        _, embeddings = load_embedding_index(EMBEDDINGS_FILE)

    embeddings[page_id] = emb
    write_embedding_index(embeddings, EMBEDDINGS_FILE)

    return {"status": "ok", "page": page_id, "dimensions": len(emb)}


def verify_status() -> dict:
    if not EMBEDDINGS_FILE.exists():
        return {"status": "empty", "embeddings": 0, "needs_generation": True}

    status = embedding_index_status(EMBEDDINGS_FILE)
    _, embeddings = load_embedding_index(EMBEDDINGS_FILE)
    chunk_status = embedding_index_status(CHUNK_EMBEDDINGS_FILE)
    _, chunk_embeddings = load_embedding_index(CHUNK_EMBEDDINGS_FILE) if CHUNK_EMBEDDINGS_FILE.exists() else ({}, {})

    pages = []
    for subdir in ["concepts", "entities", "sessions"]:
        d = PAGES_DIR / subdir
        if d.exists():
            pages.extend(d.glob("*.md"))

    page_ids = {p.stem for p in pages}
    embedded_ids = set(embeddings.keys())

    return {
        "status": "ok",
        "stale": status["stale"],
        "reason": status.get("reason", ""),
        "index": status.get("index", {}),
        "current": status.get("current", {}),
        "mismatches": status.get("mismatches", {}),
        "chunk_stale": chunk_status.get("stale", True),
        "chunk_embeddings": len(chunk_embeddings),
        "total_pages": len(page_ids),
        "total_embeddings": len(embedded_ids),
        "missing": sorted(page_ids - embedded_ids),
        "coverage_pct": round(len(embedded_ids & page_ids) / max(len(page_ids), 1) * 100, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate vector embeddings for wiki pages")
    parser.add_argument("--page", help="Generate embedding for a single page")
    parser.add_argument("--force", action="store_true", help="Regenerate all embeddings")
    parser.add_argument("--chunks", action="store_true", help="Generate chunk-level embeddings")
    parser.add_argument("--verify", action="store_true", help="Check embedding status")
    parser.add_argument("--mode", choices=["local", "api"], help="Override embedding mode")
    args = parser.parse_args()

    if args.mode:
        os.environ["EMBEDDING_MODE"] = args.mode

    if args.verify:
        result = verify_status()
    elif args.chunks:
        result = generate_chunks(force=args.force)
    elif args.page:
        result = generate_one(args.page)
    else:
        result = generate_all(force=args.force)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
