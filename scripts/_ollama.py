"""Ollama embedding utilities for llm-wiki vector search.

Uses Ollama's /api/embeddings endpoint with qwen3-embedding:8b.
Works with urllib (stdlib) — no requests dependency needed.
"""

import json
import urllib.error
import urllib.request
from typing import Optional

OLLAMA_BASE = "http://localhost:11434"
EMBED_MODEL = "qwen3-embedding:8b"


def get_embedding(text: str, model: str = EMBED_MODEL) -> Optional[list[float]]:
    """Generate an embedding vector for the given text via Ollama.

    Returns None if Ollama is unreachable or returns an error.
    """
    if not text or not text.strip():
        return None

    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    url = f"{OLLAMA_BASE}/api/embeddings"

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            embedding = data.get("embedding")
            if embedding and isinstance(embedding, list) and len(embedding) > 0:
                return [float(v) for v in embedding]
            return None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None


def is_available() -> bool:
    """Check if Ollama is running and the embedding model is available."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(EMBED_MODEL in m or EMBED_MODEL.replace(":8b", "") in m for m in models)
    except Exception:
        return False
