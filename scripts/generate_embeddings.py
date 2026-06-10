#!/usr/bin/env python3
"""generate_embeddings.py — Generate vector embeddings for all wiki pages.

Supports three modes:
  - local: Local embedding via sentence-transformers (modelscope/huggingface/Ollama)
  - api: Remote embedding API (OpenAI-compatible)
  - Default: local with Qwen3-Embedding-8B from ModelScope

Writes to .wiki/graph/embeddings.json for hybrid search.

Usage:
    python3 scripts/generate_embeddings.py              # all pages
    python3 scripts/generate_embeddings.py --page id    # single page
    python3 scripts/generate_embeddings.py --verify     # check status
    python3 scripts/generate_embeddings.py --mode api   # use API mode
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import get_config, get_wiki_dir

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
EMBEDDINGS_FILE = Path(os.environ.get("EMBEDDINGS_FILE", GRAPH_DIR / "embeddings.json"))
CHUNK_EMBEDDINGS_FILE = Path(os.environ.get("CHUNK_EMBEDDINGS_FILE", GRAPH_DIR / "chunk_embeddings.json"))
CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
EMBEDDING_SCHEMA_VERSION = 2
PAGE_SUBDIRS = [
    "concepts", "entities", "models", "techniques", "frameworks",
    "benchmarks", "papers", "decisions", "sessions", "patterns",
]
_LOCAL_MODELS: dict[str, object] = {}
_DEVICE: Optional[str] = None


def get_embeddings_config() -> dict:
    """Get embeddings configuration from wiki_config.yaml."""
    config = get_config()
    embeddings_config = dict(config.get("embeddings", {
        "mode": "local",
        "model": "Qwen/Qwen3-Embedding-8B",
        "model_backend": "modelscope",
        "dimension": 4096,
        "backend": "faiss",
        "device": "auto",
        "batch_size": 16,
    }))
    if os.environ.get("EMBEDDING_MODE"):
        embeddings_config["mode"] = os.environ["EMBEDDING_MODE"]
    if os.environ.get("EMBEDDING_MODEL"):
        embeddings_config["model"] = os.environ["EMBEDDING_MODEL"]
        embeddings_config.pop("dimension", None)
    if os.environ.get("EMBEDDING_DEVICE"):
        embeddings_config["device"] = os.environ["EMBEDDING_DEVICE"]
    return embeddings_config


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
        "index_path": str(EMBEDDINGS_FILE),
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
        if current.get(key) is not None and meta.get(key) != current.get(key)
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


def _resolve_device(config: dict) -> str:
    """Resolve the best available compute device."""
    global _DEVICE
    if _DEVICE is not None:
        return _DEVICE

    device = config.get("device", "auto")
    if device != "auto":
        _DEVICE = device
        return _DEVICE

    try:
        import torch
        if torch.cuda.is_available():
            _DEVICE = "cuda"
        elif torch.backends.mps.is_available():
            _DEVICE = "mps"
        else:
            _DEVICE = "cpu"
    except ImportError:
        _DEVICE = "cpu"

    return _DEVICE


def _load_local_model(model_name: str, config: dict) -> object:
    """Load a local embedding model, downloading from ModelScope if configured.

    Caches the loaded model in _LOCAL_MODELS for reuse.
    Auto-detects MLX models and uses MLXEmbeddingWrapper.
    """
    cache_key = f"{model_name}__{config.get('model_backend', 'modelscope')}__{config.get('matryoshka_dim', 'full')}"
    if cache_key in _LOCAL_MODELS:
        return _LOCAL_MODELS[cache_key]

    backend = config.get("model_backend", "modelscope")
    device = _resolve_device(config)

    # Resolve model path — download from ModelScope if needed
    if backend == "modelscope" and not os.path.isabs(model_name):
        from model_utils import resolve_model_path
        try:
            model_path = resolve_model_path(model_name, backend="modelscope")
        except Exception as e:
            print(f"  ModelScope download failed: {e}", file=sys.stderr)
            print(f"  Falling back to HuggingFace for: {model_name}", file=sys.stderr)
            model_path = model_name
    else:
        model_path = model_name

    # ── MLX model detection ──
    if os.path.isdir(model_path):
        from model_utils import _is_mlx_model, MLXEmbeddingWrapper
        if _is_mlx_model(model_path):
            print(f"  Loading MLX embedding model: {model_path}", file=sys.stderr)
            print(f"  Device: {device}", file=sys.stderr)
            matryoshka_dim = config.get("matryoshka_dim")
            model = MLXEmbeddingWrapper(model_path, device=device, matryoshka_dim=matryoshka_dim)
            model._load()
            dim = model.get_embedding_dimension()
            print(f"  Embedding dimension: {dim}", file=sys.stderr)
            _LOCAL_MODELS[cache_key] = model
            return model

    from sentence_transformers import SentenceTransformer

    print(f"  Loading embedding model: {model_path}", file=sys.stderr)
    print(f"  Device: {device}", file=sys.stderr)

    model = SentenceTransformer(
        model_path,
        device=device,
        trust_remote_code=True,
    )

    try:
        dim = model.get_embedding_dimension()
    except AttributeError:
        dim = model.get_sentence_embedding_dimension()  # legacy API
    print(f"  Embedding dimension: {dim}", file=sys.stderr)

    _LOCAL_MODELS[cache_key] = model
    return model


def get_embedding_local(text: str, model: str, config: Optional[dict] = None) -> Optional[list[float]]:
    """Generate embedding using local model.

    Supports:
      - ollama:<name> — Ollama API
      - modelscope models — auto-download from ModelScope
      - huggingface models — via sentence-transformers
      - local paths — load from disk
    """
    if model.startswith("ollama:"):
        model_name = model.replace("ollama:", "")
        return get_embedding_ollama(text, model_name)

    config = config or get_embeddings_config()
    try:
        st_model = _load_local_model(model, config)
        emb = st_model.encode(text, convert_to_numpy=True)
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


def get_embeddings_api(texts: list[str], config: dict) -> list[Optional[list[float]]]:
    """Generate embeddings for a batch using an OpenAI-compatible API."""
    import requests

    if not texts:
        return []

    api_url = config.get("api_url", "")
    api_key = config.get("api_key", "")
    api_model = config.get("api_model") or config.get("model") or "text-embedding-3-small"

    if not api_url:
        print("Error: embeddings.api_url not configured", file=sys.stderr)
        return [None] * len(texts)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.post(
            api_url,
            headers=headers,
            json={"model": api_model, "input": texts},
            timeout=120,
        )
        if resp.status_code == 429:
            time.sleep(5)
            resp = requests.post(
                api_url,
                headers=headers,
                json={"model": api_model, "input": texts},
                timeout=120,
            )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("data", [])
        embeddings.sort(key=lambda item: item.get("index", 0))
        result = [item.get("embedding") for item in embeddings]
        if len(result) != len(texts):
            return [None] * len(texts)
        return result
    except Exception as e:
        print(f"API batch embedding error: {e}", file=sys.stderr)
        return [None] * len(texts)


def get_embeddings_local(texts: list[str], model: str, config: Optional[dict] = None) -> list[Optional[list[float]]]:
    """Generate local embeddings for a batch of texts.

    Uses batch encoding for efficiency. Falls back to per-text for Ollama.
    """
    if not texts:
        return []
    if model.startswith("ollama:"):
        model_name = model.replace("ollama:", "")
        return [get_embedding_ollama(text, model_name) for text in texts]

    config = config or get_embeddings_config()
    try:
        st_model = _load_local_model(model, config)
        batch_size = int(config.get("batch_size", 16))
        embeddings = st_model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=batch_size,
        )
        return [emb.tolist() for emb in embeddings]
    except ImportError:
        print("Install sentence-transformers: pip install sentence-transformers", file=sys.stderr)
        return [None] * len(texts)
    except Exception as e:
        print(f"Local batch embedding error: {e}", file=sys.stderr)
        return [None] * len(texts)


def get_embeddings(texts: list[str]) -> list[Optional[list[float]]]:
    """Generate embeddings for a batch based on configuration."""
    config = get_embeddings_config()
    mode = config.get("mode", "local")
    model = config.get("model", "Qwen/Qwen3-Embedding-8B")

    if mode == "api":
        return get_embeddings_api(texts, config)
    return get_embeddings_local(texts, model, config)


def get_embedding(text: str) -> Optional[list[float]]:
    """Generate embedding based on configuration."""
    embeddings = get_embeddings([text])
    return embeddings[0] if embeddings else None


def generate_all(force: bool = False, batch_size: int = 32) -> dict:
    if not PAGES_DIR.exists():
        return {"status": "error", "message": "No wiki pages found. Run compile first."}

    existing = {}
    if EMBEDDINGS_FILE.exists() and not force:
        status = embedding_index_status(EMBEDDINGS_FILE)
        if status.get("stale"):
            force = True
        else:
            _, existing = load_embedding_index(EMBEDDINGS_FILE)

    pages = []
    for subdir in PAGE_SUBDIRS:
        d = PAGES_DIR / subdir
        if d.exists():
            pages.extend(d.glob("*.md"))

    generated = 0
    skipped = 0
    failed = 0
    embeddings = dict(existing) if not force else {}

    pending: list[tuple[str, str]] = []
    for page_path in sorted(pages):
        page_id = page_path.stem
        if page_id in embeddings and not force:
            skipped += 1
            continue

        content = read_page_content(page_path)
        if not content:
            failed += 1
            continue
        pending.append((page_id, content))

    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        batch_embeddings = get_embeddings([content for _, content in batch])
        for (page_id, _), emb in zip(batch, batch_embeddings):
            if emb is None:
                failed += 1
                print(f"  ⚠ failed: {page_id}", file=sys.stderr)
                continue

            embeddings[page_id] = emb
            generated += 1
        if generated and generated % max(batch_size, 1) == 0:
            print(f"  {generated}/{len(pending)} pages...", file=sys.stderr)

    write_embedding_index(embeddings, EMBEDDINGS_FILE)

    return {
        "status": "ok",
        "total_pages": len(pages),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "total_embeddings": len(embeddings),
    }


def generate_chunks(force: bool = False, batch_size: int = 32) -> dict:
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
        status = embedding_index_status(CHUNK_EMBEDDINGS_FILE)
        if status.get("stale"):
            force = True
        else:
            _, existing = load_embedding_index(CHUNK_EMBEDDINGS_FILE)

    generated = 0
    skipped = 0
    failed = 0
    items = dict(existing) if not force else {}

    pending: list[tuple[dict, str, str]] = []
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
        pending.append((chunk, chunk_id, text))

    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        batch_embeddings = get_embeddings([text[:3000] for _, _, text in batch])
        for (chunk, chunk_id, text), emb in zip(batch, batch_embeddings):
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
        if generated and generated % max(batch_size, 1) == 0:
            print(f"  {generated}/{len(pending)} chunks...", file=sys.stderr)

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
    for subdir in PAGE_SUBDIRS:
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
    for subdir in PAGE_SUBDIRS:
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
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size")
    args = parser.parse_args()

    if args.mode:
        os.environ["EMBEDDING_MODE"] = args.mode

    if args.verify:
        result = verify_status()
    elif args.chunks:
        result = generate_chunks(force=args.force, batch_size=args.batch_size)
    elif args.page:
        result = generate_one(args.page)
    else:
        result = generate_all(force=args.force, batch_size=args.batch_size)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
