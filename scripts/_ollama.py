"""Ollama embedding utilities for llm-wiki vector search.

Uses Ollama's /api/embeddings endpoint with Qwen3-Embedding-8B-4bit-DWQ.
Configurable via environment variables or defaults.

Environment variables:
    OLLAMA_BASE_URL  — Ollama server URL (default: http://127.0.0.1:12345)
    OLLAMA_API_KEY   — API key for authentication (default: lingting)
    EMBED_MODEL      — Embedding model name
"""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "qwen3-embedding:8b")


def get_embedding(text: str, model: str = EMBED_MODEL) -> Optional[list[float]]:
    if not text or not text.strip():
        return None

    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    url = f"{OLLAMA_BASE}/api/embeddings"
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            embedding = data.get("embedding")
            if embedding and isinstance(embedding, list) and len(embedding) > 0:
                return [float(v) for v in embedding]
            return None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None


def is_available() -> bool:
    try:
        headers = {}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(EMBED_MODEL in m or EMBED_MODEL.replace(":8b", "") in m for m in models)
    except Exception:
        return False
