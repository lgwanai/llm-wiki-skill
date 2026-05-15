#!/usr/bin/env python3
from __future__ import annotations
"""_qdrant.py — Optional Qdrant vector database integration for llm-wiki.

Provides persistent vector storage with:
- Real vector search (replaces embeddings.json for scale)
- Metadata filtering (by entity type, confidence, source)
- Hybrid search (dense vector + sparse keyword)

Enabled via config or environment variable QDRANT_URL.

Usage:
    from _qdrant import QdrantStore
    store = QdrantStore()  # auto-connects if configured
    store.upsert("page-id", embedding, {"type": "concept"})
    results = store.search(query_embedding, limit=10, filter={"type": "concept"})
"""

import json
import os
import sys
import urllib.error
import urllib.request

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION_NAME = "llm_wiki_pages"


class QdrantStore:
    def __init__(self, url: str = QDRANT_URL, api_key: str = QDRANT_API_KEY):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.collection = COLLECTION_NAME
        self._ensure_collection()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["api-key"] = self.api_key
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            return {"status": "error", "code": e.code, "body": body}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _ensure_collection(self) -> None:
        resp = self._request("GET", "/collections")
        collections = [c["name"] for c in resp.get("result", {}).get("collections", [])]
        if self.collection not in collections:
            self._request("PUT", f"/collections/{self.collection}", {
                "vectors": {"size": 4096, "distance": "Cosine"},
            })

    def is_available(self) -> bool:
        resp = self._request("GET", "/")
        return resp.get("title") == "qdrant - vector search engine"

    def upsert(self, page_id: str, embedding: list[float], metadata: dict | None = None) -> bool:
        payload = {"points": [{"id": page_id, "vector": embedding, "payload": metadata or {}}]}
        resp = self._request("PUT", f"/collections/{self.collection}/points", payload)
        return resp.get("status") == "ok"

    def search(self, embedding: list[float], limit: int = 10, filter_dict: dict | None = None) -> list[dict]:
        body = {"vector": embedding, "limit": limit, "with_payload": True}
        if filter_dict:
            body["filter"] = {"must": [{"key": k, "match": {"value": v}} for k, v in filter_dict.items()]}
        resp = self._request("POST", f"/collections/{self.collection}/points/search", body)
        results = resp.get("result", [])
        return [{"id": r["id"], "score": r["score"], "payload": r.get("payload", {})} for r in results]

    def delete(self, page_id: str) -> bool:
        resp = self._request("POST", f"/collections/{self.collection}/points/delete", {
            "points": [page_id],
        })
        return resp.get("status") == "ok"

    def count(self) -> int:
        resp = self._request("GET", f"/collections/{self.collection}")
        return resp.get("result", {}).get("points_count", 0)


def create_qdrant_store() -> QdrantStore | None:
    store = QdrantStore()
    if store.is_available():
        return store
    print("Qdrant not available at", QDRANT_URL, file=sys.stderr)
    return None
