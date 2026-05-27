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

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import get_config, get_wiki_dir

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
EMBEDDINGS_FILE = GRAPH_DIR / "embeddings.json"
CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"


def get_embeddings_config() -> dict:
    """Get embeddings configuration from wiki_config.yaml."""
    config = get_config()
    return config.get("embeddings", {
        "mode": "local",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "dimension": 384,
        "backend": "faiss",
    })


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
    api_model = config.get("api_model", "text-embedding-3-small")
    
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
    parser.add_argument("--mode", choices=["local", "api"], help="Override embedding mode")
    args = parser.parse_args()

    if args.mode:
        os.environ["EMBEDDING_MODE"] = args.mode

    if args.verify:
        result = verify_status()
    elif args.page:
        result = generate_one(args.page)
    else:
        result = generate_all(force=args.force)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()