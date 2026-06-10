#!/usr/bin/env python3
"""query.py — Query wiki and answer questions (Karpathy v1 + Rohit v2).

Operations:
- Search wiki pages (BM25 + graph traversal)
- Synthesize answer from relevant pages
- File back high-quality answers as new wiki pages (optional)

Usage:
    python scripts/query.py "What is DeepSeek-V4's architecture?"
    python scripts/query.py "Explain Muon optimizer" --file-back
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import get_config, get_wiki_dir, get_llm_config, get_api_url, get_query_config, get_reranker_config

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"


DEFAULT_SEARCH_STREAMS = ["metadata", "chunk", "bm25", "chunk_vector", "vector", "graph", "ledger"]

# ── Cross-encoder reranker (lazy-loaded, multi-backend) ──
_reranker_model = None
_reranker_tokenizer = None
_reranker_backend = None  # "mlx", "flagembedding", or None
_RERANKER_PATH = None  # resolved at load time


_QWEN3_RERANKER_SYSTEM = (
    'Judge whether the Document meets the requirements based on the Query '
    'and the Instruct provided. Output only "yes" or "no".'
)

_QWEN3_RERANKER_INSTRUCT = (
    "Given a web search query, retrieve relevant passages that answer the query"
)

_reranker_config_cache: Optional[dict] = None
# For mlx-embeddings backend
_mlx_model = None
_mlx_processor = None


def _resolve_reranker_config() -> dict:
    """Resolve reranker config after wiki dir / config file are available."""
    global _RERANKER_PATH, _reranker_config_cache

    if _reranker_config_cache is not None:
        return _reranker_config_cache

    cfg = get_reranker_config()
    if not cfg.get("enabled", True):
        _RERANKER_PATH = ""  # sentinel: disabled
        _reranker_config_cache = {}
        return _reranker_config_cache

    backend = cfg.get("backend", "mlx")
    model_path = cfg.get("model_path", "")

    # auto-detect: prefer MLX if model path contains mlx-community
    if backend == "auto":
        if "mlx-community" in model_path.lower():
            backend = "mlx"
        else:
            backend = "flagembedding"

    cfg["_resolved_backend"] = backend
    _RERANKER_PATH = model_path
    _reranker_config_cache = cfg
    return cfg


def _get_reranker():
    """Lazy-load the reranker model (MLX embeddings or FlagEmbedding backend).

    MLX backend: Uses ``mlx-embeddings`` for Apple Silicon native inference.
    The model encodes query and documents separately (bi-encoder), then
    cosine similarity with batch-normalized scoring produces relevance scores.

    FlagEmbedding backend: Uses ``FlagEmbedding.FlagReranker`` for
    cross-encoder scoring (PyTorch, works on CPU/MPS/CUDA).
    """
    global _reranker_model, _reranker_tokenizer, _reranker_backend
    global _mlx_model, _mlx_processor

    if _reranker_model is not None:
        return _reranker_model

    cfg = _resolve_reranker_config()
    backend = cfg.get("_resolved_backend", "")
    model_path = cfg.get("model_path", "")

    if not backend or not model_path or not os.path.isdir(model_path):
        if cfg.get("enabled", True):
            backend_label = backend or "unknown"
            print(
                f"  [reranker] Model not found: backend={backend_label}, "
                f"path={model_path or '(not set)'}. "
                f"Reranking disabled — install model or set reranker.enabled=false in wiki_config.yaml",
                file=sys.stderr,
            )
        return None

    if backend == "mlx":
        try:
            from mlx_embeddings import load as me_load
            print(
                f"  [reranker] Loading MLX bi-encoder model from {model_path}...",
                file=sys.stderr,
            )
            _mlx_model, _mlx_processor = me_load(model_path)
            _reranker_model = _mlx_model  # signal that model is loaded
            _reranker_backend = "mlx"
            print(
                f"  [reranker] ⚠️  MLX backend is a bi-encoder, NOT a cross-encoder. "
                f"For better reranking quality, use backend=flagembedding with "
                f"a cross-encoder model like BAAI/bge-reranker-v2-m3.",
                file=sys.stderr,
            )
            return _reranker_model
        except (ImportError, Exception) as e:
            print(
                f"  [reranker] MLX model load failed: {e}. "
                f"Install mlx-embeddings: pip install mlx-embeddings",
                file=sys.stderr,
            )
            return None

    # FlagEmbedding / transformers cross-encoder backend
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        print(
            f"  [reranker] Loading FlagEmbedding cross-encoder from {model_path}...",
            file=sys.stderr,
        )
        _reranker_tokenizer = AutoTokenizer.from_pretrained(model_path)
        _reranker_model = AutoModelForSequenceClassification.from_pretrained(model_path)
        import torch
        _reranker_model.eval()
        _reranker_backend = "flagembedding"
        print(
            f"  [reranker] ✓ Cross-encoder loaded successfully (backend=flagembedding)",
            file=sys.stderr,
        )
        return _reranker_model
    except (ImportError, Exception) as e:
        print(
            f"  [reranker] FlagEmbedding model load failed: {e}. "
            f"Install: pip install transformers torch",
            file=sys.stderr,
        )
        return None


def _mlx_rerank_scores(
    query: str,
    documents: list[str],
) -> list[float]:
    """Score query-document pairs using MLX embeddings (bi-encoder).

    Encodes the query and each document through the MLX model, computes
    cosine similarities, and normalizes within the batch for discrimination.

    IMPORTANT: This is a bi-encoder approximation. For true cross-encoding
    (where [query, doc] pairs are scored jointly), use flagembedding backend.
    We use the Qwen3 reranker instruction format to improve encoding quality.
    """
    import mlx.core as mx

    if not documents:
        return []

    # Format query with reranker instruction for better encoding
    instructed_query = (
        f"{_QWEN3_RERANKER_INSTRUCT}\n"
        f"Query: {query}\n"
        f"Document: "
    )

    all_texts = [instructed_query] + documents

    from mlx_embeddings import generate as me_generate
    output = me_generate(_mlx_model, _mlx_processor, texts=all_texts)
    embeddings = output.text_embeds  # [N+1, hidden_size]

    query_emb = embeddings[0]
    doc_embs = embeddings[1:]

    # Cosine similarities
    query_norm = mx.linalg.norm(query_emb)
    query_norm_f = float(query_norm)
    if query_norm_f < 1e-8:
        return [0.5] * len(documents)

    sims = []
    for i in range(len(documents)):
        doc_norm = mx.linalg.norm(doc_embs[i])
        doc_norm_f = float(doc_norm)
        if doc_norm_f < 1e-8:
            sims.append(0.5)
        else:
            sim = float((query_emb @ doc_embs[i].T) / (query_norm * doc_norm))
            # Cosine sim is in [-1, 1]; map to [0, 1]
            sims.append((sim + 1.0) / 2.0)

    # Soft normalization: scale to [0, 1] without overly compressing
    if len(sims) > 1:
        sim_min = min(sims)
        sim_max = max(sims)
        span = sim_max - sim_min
        if span > 0.01:
            sims = [(s - sim_min) / span for s in sims]

    return sims


def _extract_candidate_texts(candidates: list[dict]) -> list[str]:
    """Extract text content from candidate dicts for reranker scoring."""
    texts = []
    for c in candidates:
        text = c.get("text", "")
        if not text:
            try:
                text = Path(c.get("path", "")).read_text(encoding="utf-8")[:2000]
            except Exception:
                text = f"{c.get('id', '')} {c.get('type', '')}"
        texts.append(text[:2000])
    return texts


def cross_encode_rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Re-rank candidates using a cross-encoder model for precise relevance scoring.

    Supports two backends:
    - flagembedding: Cross-encoder via FlagEmbedding (BGE/Qwen3-Reranker).
      This is the RECOMMENDED backend — it uses true cross-encoding where
      [query, document] pairs are scored jointly.
    - mlx: Apple Silicon native bi-encoder. **IMPORTANT**: This is a bi-encoder
      (separate query/doc embeddings → cosine sim), NOT a true cross-encoder.
      Results may be less discriminative. Prefer flagembedding for reranking.

    Operates on up to 256 candidates, re-ranks them, and returns top_k results.
    """
    cfg = _resolve_reranker_config()
    if not cfg:
        return candidates[:top_k]

    reranker = _get_reranker()
    if reranker is None:
        return candidates[:top_k]

    # Only skip if we have very few candidates (2 or fewer is pointless to rerank)
    if len(candidates) <= 2:
        return candidates[:top_k]

    max_pairs = min(cfg.get("max_pairs", 256), len(candidates))
    candidates = candidates[:max_pairs]
    docs = _extract_candidate_texts(candidates)

    if _reranker_backend == "mlx":
        # MLX bi-encoder: embed query + docs, compute cosine sim, normalize.
        # NOTE: This is NOT a true cross-encoder. The model may have been trained
        # as a cross-encoder (e.g., Qwen3-Reranker) and using it as a bi-encoder
        # produces poor results. We combine bi-encoder scores with a lexical
        # overlap fallback for robustness.
        try:
            scores = _mlx_rerank_scores(query, docs)
            # Combine with lexical overlap to stabilize scores
            query_terms = set(re.findall(r"[\w一-鿿]+", query.lower()))
            for i, (c, s) in enumerate(zip(candidates, scores)):
                doc_text = docs[i].lower()
                lexical = sum(1 for t in query_terms if t in doc_text) / max(len(query_terms), 1)
                # Blend: 70% bi-encoder + 30% lexical overlap
                c["cross_score"] = round(0.7 * s + 0.3 * lexical, 4)
            candidates_sorted = sorted(
                candidates, key=lambda x: -x.get("cross_score", 0)
            )
            return candidates_sorted[:top_k]
        except Exception as e:
            print(f"  [reranker] MLX rerank failed: {e}, using original order",
                  file=sys.stderr)
            pass
        return candidates[:top_k]

    # Cross-encoder backend (transformers / FlagEmbedding)
    pairs = [[query, d] for d in docs]
    try:
        import torch
        with torch.no_grad():
            inputs = _reranker_tokenizer(
                [p[0] for p in pairs], [p[1] for p in pairs],
                padding=True, truncation=True, return_tensors="pt", max_length=512,
            )
            scores = _reranker_model(**inputs, return_dict=True).logits.view(-1).float()
            for c, s in zip(candidates, scores.tolist()):
                c["cross_score"] = round(float(s), 4)
            candidates_sorted = sorted(
                candidates, key=lambda x: -x.get("cross_score", 0)
            )
            return candidates_sorted[:top_k]
    except Exception as e:
        print(f"  [reranker] Cross-encoder rerank failed: {e}, using original order",
              file=sys.stderr)
        pass

    return candidates[:top_k]


def enabled_search_streams() -> set[str]:
    """Return enabled retrieval streams from env/config."""
    env_value = os.environ.get("LLM_WIKI_SEARCH_STREAMS", "").strip()
    configured = env_value or str(get_query_config().get("search_streams", "") or "")
    if not configured:
        return set(DEFAULT_SEARCH_STREAMS)
    if configured.lower() in {"all", "*"}:
        return set(DEFAULT_SEARCH_STREAMS)
    return {stream.strip() for stream in configured.split(",") if stream.strip()}


def load_config():
    return get_config()


def call_llm(system_prompt: str, user_content: str, config: dict) -> str:
    import requests

    llm_config = get_llm_config()
    provider = llm_config.get("provider", "deepseek")
    
    if provider == "ollama":
        api_url = f"{llm_config['base_url'].rstrip('/')}/api/chat"
        payload = {
            "model": llm_config.get("model", "llama3.2"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {
                "temperature": llm_config.get("temperature", 0.3),
                "num_ctx": llm_config.get("num_ctx", 32768),
            }
        }
        headers = {"Content-Type": "application/json"}
    elif provider == "custom":
        api_url = get_api_url()
        payload = {
            "model": llm_config.get("model", ""),
            "temperature": llm_config.get("temperature", 0.3),
            "max_tokens": 8000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.get('api_key', '')}",
        }
    else:
        api_url = get_api_url()
        api_key = llm_config.get("api_key", "")
        if not api_key:
            raise RuntimeError("LLM API key not configured.")
        
        payload = {
            "model": llm_config.get("model", "deepseek-v4-flash"),
            "temperature": llm_config.get("temperature", 0.3),
            "max_tokens": 8000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        
        if provider == "ollama":
            return (data.get("message", {}).get("content", "") or "").strip()
        else:
            msg = data["choices"][0]["message"]
            return (msg.get("content") or "").strip()
    except requests.RequestException as e:
        raise RuntimeError(f"LLM API call failed: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected LLM API response: {e}")


def _allowed_scopes_from_env() -> set[str]:
    raw = os.environ.get("LLM_WIKI_ALLOWED_SCOPES", "").strip()
    return {scope.strip() for scope in raw.split(",") if scope.strip()}


def _excluded_statuses_from_env() -> set[str]:
    raw = os.environ.get("LLM_WIKI_EXCLUDE_STATUSES", "").strip()
    return {status.strip() for status in raw.split(",") if status.strip()}


def _page_frontmatter_value(path: str, key: str, default: str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, PermissionError):
        return default
    if not text.startswith("---"):
        return default
    for line in text.splitlines()[1:40]:
        if line.strip() == "---":
            break
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'") or default
    return default


def _page_scope(path: str) -> str:
    return _page_frontmatter_value(path, "scope", "public")


def _page_status(path: str) -> str:
    return _page_frontmatter_value(path, "status", "current")


def _filter_by_allowed_scopes(results: list[dict], allowed_scopes: set[str]) -> list[dict]:
    if not allowed_scopes:
        return results
    filtered = []
    for result in results:
        path = result.get("path", "")
        if not path or _page_scope(path) in allowed_scopes:
            filtered.append(result)
    return filtered


def _filter_by_excluded_statuses(results: list[dict], excluded_statuses: set[str]) -> list[dict]:
    if not excluded_statuses:
        return results
    filtered = []
    for result in results:
        path = result.get("path", "")
        if not path or _page_status(path) not in excluded_statuses:
            filtered.append(result)
    return filtered


def search_wiki(
    query: str,
    limit: int = 5,
    debug: bool = False,
    allowed_scopes: list[str] | set[str] | None = None,
    exclude_statuses: list[str] | set[str] | None = None,
) -> list[dict] | tuple[list[dict], dict]:
    """Hybrid search: BM25 + Vector + Graph + entities.json fallback, fused by RRF."""
    all_streams: list[list[dict]] = []
    plan = plan_query(query)
    query_variants = rewrite_query(query, plan)
    enabled_streams = enabled_search_streams()
    scope_filter = set(allowed_scopes or []) or _allowed_scopes_from_env()
    status_filter = set(exclude_statuses or []) or _excluded_statuses_from_env()
    trace: dict = {
        "query": query,
        "plan": plan,
        "query_variants": query_variants,
        "enabled_streams": sorted(enabled_streams),
        "allowed_scopes": sorted(scope_filter),
        "exclude_statuses": sorted(status_filter),
        "streams": {},
    }

    # 0. Metadata search over aliases/keywords/questions/summary.
    if "metadata" in enabled_streams:
        try:
            from search import metadata_search
            metadata_results = []
            for variant in query_variants:
                metadata_results.extend(metadata_search(variant, str(PAGES_DIR), limit=limit * 4))
            metadata_results = reciprocal_rank_merge(metadata_results, limit=limit * 4)
            trace["streams"]["metadata"] = metadata_results
            if metadata_results:
                all_streams.append(metadata_results)
        except Exception as e:
            trace["streams"]["metadata_error"] = str(e)

    # 1. Chunk-level BM25 search for precise page-local matches
    if "chunk" in enabled_streams:
        try:
            from search import chunk_search
            chunk_results = []
            for variant in query_variants:
                chunk_results.extend(chunk_search(variant, str(PAGES_DIR), limit=limit * 4))
            chunk_results = reciprocal_rank_merge(chunk_results, limit=limit * 4)
            trace["streams"]["chunk"] = chunk_results
            if chunk_results:
                all_streams.append(chunk_results)
        except Exception as e:
            trace["streams"]["chunk_error"] = str(e)

    # 2. BM25 keyword search (now supports Chinese via jieba)
    if "bm25" in enabled_streams:
        try:
            from search import bm25_search
            bm25_results = []
            for variant in query_variants:
                bm25_results.extend(bm25_search(variant, str(PAGES_DIR), limit=limit * 4))
            bm25_results = reciprocal_rank_merge(bm25_results, limit=limit * 4)
            trace["streams"]["bm25"] = bm25_results
            if bm25_results:
                all_streams.append(bm25_results)
        except Exception as e:
            trace["streams"]["bm25_error"] = str(e)

    # 2. Vector semantic search (via Ollama)
    if "chunk_vector" in enabled_streams:
        try:
            from search import vector_chunk_search
            chunk_vector_results = vector_chunk_search(query, str(PAGES_DIR), limit=limit * 3)
            trace["streams"]["chunk_vector"] = chunk_vector_results
            if chunk_vector_results:
                all_streams.append(chunk_vector_results)
        except Exception as e:
            trace["streams"]["chunk_vector_error"] = str(e)

    # 3. Page-level vector semantic search
    if "vector" in enabled_streams:
        try:
            from search import vector_search
            vector_results = vector_search(query, str(PAGES_DIR), limit=limit * 3)
            trace["streams"]["vector"] = vector_results
            if vector_results:
                all_streams.append(vector_results)
        except Exception as e:
            trace["streams"]["vector_error"] = str(e)

    # 4. Graph entity search
    if "graph" in enabled_streams:
        try:
            from search import graph_search
            graph_results = graph_search(query, str(WIKI_DIR / "graph"), limit=limit * 3)
            trace["streams"]["graph_raw"] = graph_results
            if graph_results:
                # Convert graph results to BM25-compatible format
                converted = []
                for g in graph_results:
                    eid = g.get("entity_id", "")
                    page_dir = "concepts" if g.get("type") in ("concept", "technique", "model") else "entities"
                    page_path = PAGES_DIR / page_dir / f"{eid}.md"
                    if page_path.exists():
                        converted.append({
                            "file": eid,
                            "path": str(page_path),
                            "score": g.get("confidence", 0.5),
                            "stream": "graph",
                        })
                if converted:
                    trace["streams"]["graph"] = converted
                    all_streams.append(converted)
        except Exception as e:
            trace["streams"]["graph_error"] = str(e)

    # 5. Ledger search (structured tables)
    if "ledger" in enabled_streams:
        try:
            from ledger import search_ledgers as ledger_search
            ledger_results = ledger_search(query, limit=limit)
            trace["streams"]["ledger_raw"] = ledger_results
            if ledger_results:
                converted = []
                for lr in ledger_results:
                    converted.append({
                        "file": lr["id"],
                        "path": str(WIKI_DIR / "ledger" / lr["id"]),
                        "score": lr.get("score", 1),
                        "stream": "ledger",
                        "ledger_name": lr["name"],
                        "ledger_fields": lr.get("fields", []),
                        "ledger_preview": lr.get("preview", []),
                    })
                all_streams.append(converted)
                trace["streams"]["ledger"] = converted
        except Exception as e:
            trace["streams"]["ledger_error"] = str(e)

    # Fuse results with RRF if multiple streams
    if len(all_streams) >= 2:
        try:
            from search import reciprocal_rank_fusion
            fused = reciprocal_rank_fusion(all_streams)
            trace["fused"] = fused
            results = []
            seen = set()
            for f in fused[: max(limit * 4, limit)]:
                path = f.get("path", "")
                if path and path not in seen:
                    seen.add(path)
                    eid = f.get("file") or f.get("entity_id", "")
                    results.append({
                        "path": path,
                        "score": f.get("rrf_score", 0),
                        "id": eid,
                        "type": _infer_type(eid),
                        "stream": ",".join(f.get("streams", [])),
                        "chunk_id": f.get("chunk_id", ""),
                        "heading_path": f.get("heading_path", []),
                        "text": f.get("text", ""),
                        "stream_ranks": f.get("stream_ranks", {}),
                        "stream_scores": f.get("stream_scores", {}),
                    })
            if results:
                results = rerank_results(query, results, plan)
                # Graph expansion (Phase 3): fetch connected entities (configurable)
                if os.environ.get("LLM_WIKI_GRAPH_EXPAND", "").lower() in ("1", "true", "yes"):
                    results = _graph_expand(results, limit=limit * 3)
                # Cross-encoder re-rank (Phase 2): re-scores top candidates
                results = cross_encode_rerank(query, results, top_k=limit)
                results = _filter_by_allowed_scopes(results, scope_filter)
                results = _filter_by_excluded_statuses(results, status_filter)
                trace["reranked"] = results
                return (results[:limit], trace) if debug else results[:limit]
        except Exception as e:
            trace["fusion_error"] = str(e)
    elif all_streams:
        # Single stream — convert directly
        results = []
        seen = set()
        for r in all_streams[0]:
            path = r.get("path", "")
            if path and path not in seen:
                seen.add(path)
                eid = r.get("file", "")
                results.append({
                    "path": path,
                    "score": r.get("score", 0),
                    "id": eid,
                    "type": _infer_type(eid),
                    "stream": r.get("stream", ""),
                    "chunk_id": r.get("chunk_id", ""),
                    "heading_path": r.get("heading_path", []),
                    "text": r.get("text", ""),
                })
        if results:
            results = rerank_results(query, results, plan)
            results = _graph_boost(results)
            # Graph expansion (Phase 3): fetch connected entities (configurable)
            if os.environ.get("LLM_WIKI_GRAPH_EXPAND", "").lower() in ("1", "true", "yes"):
                results = _graph_expand(results, limit=limit * 3)
            results = cross_encode_rerank(query, results, top_k=limit)
            results = _filter_by_allowed_scopes(results, scope_filter)
            results = _filter_by_excluded_statuses(results, status_filter)
            trace["reranked"] = results
            return (results[:limit], trace) if debug else results[:limit]

    # 4. Entity name fallback (substring match against entities.json)
    entities = _get_entities()
    results = []
    seen = set()
    if entities:
        query_lower = query.lower()
        for eid, data in entities.items():
            if eid in seen:
                continue
            name = data.get("name", "")
            if query_lower in eid.lower() or query_lower in name.lower() or any(
                qt in name for qt in query_lower.split() if len(qt) >= 2
            ):
                etype = data.get("type", "")
                page_dir = "concepts" if etype in ("concept", "technique", "model", "framework", "benchmark", "paper") else "entities"
                page_path = PAGES_DIR / page_dir / f"{eid}.md"
                if page_path.exists():
                    seen.add(eid)
                    results.append({
                        "path": str(page_path),
                        "score": 0.80,
                        "id": eid,
                        "type": etype,
                    })

    results = rerank_results(query, results, plan)
    if os.environ.get("LLM_WIKI_GRAPH_EXPAND", "").lower() in ("1", "true", "yes"):
        results = _graph_expand(results, limit=limit * 2)
    results = cross_encode_rerank(query, results, top_k=limit)
    results = _filter_by_allowed_scopes(results, scope_filter)
    results = _filter_by_excluded_statuses(results, status_filter)
    trace["reranked"] = results
    return (results[:limit], trace) if debug else results[:limit]


_entities_cache: Optional[dict] = None


def _get_entities() -> dict:
    global _entities_cache
    if _entities_cache is None:
        entities_file = WIKI_DIR / "graph" / "entities.json"
        if entities_file.exists():
            try:
                _entities_cache = json.loads(entities_file.read_text(encoding="utf-8"))
                if not isinstance(_entities_cache, dict):
                    _entities_cache = {}
            except (json.JSONDecodeError, OSError):
                _entities_cache = {}
        else:
            _entities_cache = {}
    return _entities_cache


def _infer_type(eid: str) -> str:
    """Infer entity type from ID or entities.json."""
    entities = _get_entities()
    if eid in entities:
        return entities[eid].get("type", "concept")
    return "concept"


def reciprocal_rank_merge(results: list[dict], limit: int = 10) -> list[dict]:
    """Deduplicate one stream while preserving rank evidence across query variants."""
    merged: dict[str, dict] = {}
    for rank, item in enumerate(results, 1):
        key = item.get("path") or item.get("file") or str(rank)
        if key not in merged:
            merged[key] = dict(item)
            merged[key]["variant_score"] = 0.0
        merged[key]["variant_score"] += 1.0 / (60 + rank)
        merged[key]["score"] = max(float(merged[key].get("score", 0)), float(item.get("score", 0)))
    sorted_items = sorted(
        merged.values(),
        key=lambda item: (float(item.get("score", 0)), item.get("variant_score", 0)),
        reverse=True,
    )
    return sorted_items[:limit]


def plan_query(query: str) -> dict:
    """Simple query planner for retrieval routing."""
    q = query.lower()
    ledger_terms = ("表", "台账", "预算", "金额", "状态", "字段", "行", "row", "table", "ledger", "sql")
    graph_terms = ("影响", "依赖", "关系", "路径", "关联", "impact", "depends", "relationship")
    compare_terms = ("比较", "对比", "区别", "compare", "difference")

    preferred = ["metadata", "chunk", "chunk_vector", "bm25", "vector", "graph", "ledger"]
    intent = "fact"
    if any(term in q for term in ledger_terms):
        intent = "ledger_filter"
        preferred = ["ledger", "metadata", "chunk", "chunk_vector", "bm25", "vector", "graph"]
    elif any(term in q for term in graph_terms):
        intent = "relationship"
        preferred = ["graph", "metadata", "chunk", "chunk_vector", "bm25", "vector", "ledger"]
    elif any(term in q for term in compare_terms):
        intent = "comparison"

    return {
        "intent": intent,
        "preferred_streams": preferred,
        "keywords": [t for t in re.split(r"\s+", query.strip()) if t],
    }


def rewrite_query(query: str, plan: dict) -> list[str]:
    """Generate lexical + LLM semantic variants for recall."""
    variants = [query]
    normalized = re.sub(r"[\s_]+", " ", query).strip()
    if normalized and normalized not in variants:
        variants.append(normalized)
    if "-" in query:
        variants.append(query.replace("-", " "))
    if " " in query:
        variants.append(query.replace(" ", "-"))
    if plan.get("intent") == "ledger_filter":
        for token in ("台账", "表格", "字段"):
            if token not in query:
                variants.append(f"{query} {token}")

    # LLM-based semantic expansion for non-trivial queries (>10 chars, non-ledger)
    if len(query) > 10 and plan.get("intent") != "ledger_filter":
        try:
            llm_variants = _llm_expand_query(query, plan)
            variants.extend(llm_variants)
        except Exception:
            pass  # LLM expansion is best-effort, fall back to lexical

    deduped = []
    seen = set()
    for variant in variants:
        variant = variant.strip()
        if variant and variant not in seen:
            seen.add(variant)
            deduped.append(variant)
    return deduped[:8]


def _graph_traverse_recall(entity_ids: list[str], depth: int = 2, limit: int = 10) -> list[dict]:
    """Expand search recall by traversing knowledge graph from top entities.

    For relationship/synthesis queries, top entities' graph neighbors may contain
    relevant information not captured by text-based retrieval.
    """
    try:
        from graph import traverse, _paths
        _, entities_file, _ = _paths()
        import json as _json
        entities_data = _json.loads(Path(entities_file).read_text(encoding="utf-8"))
    except Exception:
        return []

    expanded = []
    seen_ids = set(entity_ids)

    for eid in entity_ids[:3]:  # top 3 entities
        try:
            subgraph = traverse(eid, depth=depth)
            for node_id, node_data in subgraph.items():
                if node_id in seen_ids:
                    continue
                entity = node_data.get("entity", {})
                if not isinstance(entity, dict):
                    continue
                seen_ids.add(node_id)
                etype = entity.get("type", "concept")
                page_dir = "concepts" if etype in ("concept", "technique", "model", "framework", "benchmark") else "entities"
                page_path = PAGES_DIR / page_dir / f"{node_id}.md"
                if page_path.exists():
                    expanded.append({
                        "file": node_id,
                        "path": str(page_path),
                        "score": 0.35,  # lower base score — graph recall supplement
                        "type": etype,
                        "stream": "graph_recall",
                    })
        except Exception:
            continue

    return expanded[:limit]


def _graph_boost(results: list[dict]) -> list[dict]:
    """Boost pages connected to top-ranked results via knowledge graph edges.

    A page that is connected (via typed edges) to a top-3 result gets a
    small score boost, since related entities are more likely relevant.
    """
    if len(results) < 3:
        return results

    try:
        from graph import _paths
        import json as _json
        _, _, edges_file = _paths()
        edges_data = _json.loads(Path(edges_file).read_text(encoding="utf-8"))
        all_edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []
    except Exception:
        return results

    top_ids = {r.get("id", "") for r in results[:3] if r.get("id")}
    if not top_ids:
        return results

    # Build adjacency: which entities are connected to top entities
    connected_to_top: dict[str, int] = {}
    for edge in all_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in top_ids and tgt:
            connected_to_top[tgt] = connected_to_top.get(tgt, 0) + 1
        if tgt in top_ids and src:
            connected_to_top[src] = connected_to_top.get(src, 0) + 1

    for r in results:
        eid = r.get("id", "")
        connections = connected_to_top.get(eid, 0)
        if connections > 0:
            # +5% per connection, max +15%
            boost = 1.0 + min(connections, 3) * 0.05
            r["score"] = r.get("score", 0) * boost
            r["graph_boost"] = round(boost, 2)

    return sorted(results, key=lambda x: -x.get("score", 0))


def _graph_expand(results: list[dict], limit: int = 10) -> list[dict]:
    """Expand result pool by fetching entities connected via knowledge graph edges.

    compile_v2 splits documents into fine-grained entity pages. A query
    matching entity A may need info from entity B (connected via uses/depends_on).
    This function adds connected entities to the candidate pool so they can
    be scored and included in the top results.

    Connected entities get a lower initial score (0.7 * source score) since
    they were matched indirectly. The cross-encoder reranker then determines
    their true relevance.
    """
    if not results:
        return results

    try:
        from graph import _paths
        import json as _json
        _, entities_file, edges_file = _paths()
        entities_data = _json.loads(Path(entities_file).read_text(encoding="utf-8"))
        edges_data = _json.loads(Path(edges_file).read_text(encoding="utf-8"))
        all_edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []
    except Exception:
        return results

    if not all_edges or not entities_data:
        return results

    # Find connected entities for top results
    existing_ids = {r.get("id", "") for r in results}
    top_ids = {r.get("id", "") for r in results[:5] if r.get("id")}
    source_scores: dict[str, float] = {
        r.get("id", ""): r.get("score", 0) for r in results[:5]
    }

    expanded: list[dict] = []
    added_ids: set[str] = set()

    for edge in all_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        relation = edge.get("type", "related_to")

        # If one end is in top results, the other end might be relevant
        for connected_id in (tgt, src):
            other_id = src if connected_id == tgt else tgt
            if other_id in top_ids and connected_id not in existing_ids and connected_id not in added_ids:
                entity = entities_data.get(connected_id)
                if not entity or not isinstance(entity, dict):
                    continue
                page_rel = entity.get("page", "")
                if not page_rel:
                    continue

                page_path = WIKI_DIR / page_rel
                if not page_path.exists():
                    continue

                source_score = source_scores.get(other_id, 0.1)
                added_ids.add(connected_id)
                expanded.append({
                    "path": str(page_path),
                    "score": round(source_score * 0.7, 4),
                    "id": connected_id,
                    "type": entity.get("type", "concept"),
                    "stream": "graph_expand",
                    "text": "",
                    "graph_relation": f"{relation} → {other_id}",
                })

    if expanded:
        results = list(results) + expanded
        # Re-sort by score
        results.sort(key=lambda x: -x.get("score", 0))

    return results[:limit]


def _llm_expand_query(query: str, plan: dict) -> list[str]:
    """Use LLM to generate 2-3 semantic query variants for better recall."""
    intent = plan.get("intent", "fact")
    is_chinese = any('一' <= c <= '鿿' for c in query)

    if is_chinese:
        hint = (
            "Generate query variants in BOTH Chinese and English. "
            "For Chinese variants: include synonyms, alternative phrasings, and related terms. "
            "For English variants: translate key technical concepts, use standard English terminology, "
            "include the original English names of any models/frameworks/tools mentioned. "
            "Generate 3-5 variants total mixing both languages."
        )
    else:
        intent_hints = {
            "fact": "include key technical terms and synonyms",
            "relationship": "include entity names and relationship words",
            "comparison": "include comparison phrases and entity names",
        }
        hint = intent_hints.get(intent, "include key terms")

    prompt = f"""Generate 2-3 alternative search queries for: "{query}"
Intent: {intent}. {hint}.
Output each query on its own line. Keep each query concise (<15 words). Do not add numbering or bullets."""

    # Use a minimal LLM call with low temperature for consistency
    from config import get_llm_config, get_api_url
    import requests as req

    llm_cfg = get_llm_config()
    provider = llm_cfg.get("provider", "deepseek")
    api_key = llm_cfg.get("api_key", "")
    model = llm_cfg.get("model", "deepseek-v4-flash")

    if provider == "ollama":
        api_url = f"{llm_cfg['base_url'].rstrip('/')}/api/chat"
        payload = {
            "model": llm_cfg.get("model", "llama3.2"),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
        }
        headers = {"Content-Type": "application/json"}
    else:
        api_url = get_api_url()
        payload = {
            "model": model, "temperature": 0.1, "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {api_key}"}
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}

    try:
        resp = req.post(api_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("message", {}).get("content", "") or
                data["choices"][0]["message"].get("content", "") or "")
        lines = [l.strip().lstrip("-•*#0123456789. ").strip()
                 for l in text.strip().split("\n") if l.strip()]
        return [l for l in lines if len(l) > 3 and l != query][:3]
    except Exception:
        return []  # best-effort, never block search


# Entity type weights for reranking \u2014 conservative boosts for content-rich types.
TYPE_WEIGHTS: dict[str, float] = {
    "concept": 1.10, "technique": 1.10, "model": 1.08, "framework": 1.05,
    "algorithm": 1.10, "process": 1.05, "rule": 1.05, "policy": 1.05,
    "benchmark": 0.95, "paper": 0.92, "certification": 0.95, "event": 0.92,
    "entity": 0.95, "metric": 0.95, "tool": 0.95, "system": 0.95,
    "product": 0.95, "role": 0.95,
}

# Intent \u2192 preferred entity types for smarter reranking.
INTENT_TYPE_PREFERENCE: dict[str, list[str]] = {
    "fact": ["concept", "technique", "model", "algorithm", "framework"],
    "relationship": ["technique", "concept", "model", "framework"],
    "comparison": ["model", "framework", "benchmark", "technique"],
    "ledger_filter": ["entity", "event", "process"],
}

def _get_entity_type_weight(entity_type: str, intent: str) -> float:
    """Calculate entity type bonus based on query intent (conservative)."""
    base = TYPE_WEIGHTS.get(entity_type, 1.0)
    preferred = INTENT_TYPE_PREFERENCE.get(intent, [])
    if entity_type in preferred:
        rank = preferred.index(entity_type)
        if rank == 0:
            base *= 1.08
        elif rank <= 2:
            base *= 1.04
    return base


def rerank_results(query: str, results: list[dict], plan: dict) -> list[dict]:
    """Reranker using stream preference, entity type weights, and lexical overlap."""
    query_terms = {t.lower() for t in re.findall(r"[\w\u4e00-\u9fff]+", query) if len(t) >= 2}
    preferred = plan.get("preferred_streams", [])
    stream_weight = {stream: len(preferred) - i for i, stream in enumerate(preferred)}
    dense_weight = float(os.environ.get("LLM_WIKI_DENSE_RERANK_WEIGHT", "1.5"))
    intent = plan.get("intent", "fact")

    def score(result: dict) -> float:
        stream_ranks = result.get("stream_ranks") or {}
        stream_scores = result.get("stream_scores") or {}
        if stream_ranks:
            weighted_rrf = 0.0
            for stream, rank in stream_ranks.items():
                rank = max(int(rank), 1)
                weight = 1.0
                if stream in {"vector", "chunk_vector"}:
                    weight = dense_weight
                elif stream == "chunk":
                    weight = 1.15
                elif stream == "metadata":
                    weight = 1.1
                elif stream == "graph":
                    weight = 1.08
                weighted_rrf += weight / (60 + rank)

            # Entity type bonus (new)
            etype = result.get("type", "")
            type_bonus = _get_entity_type_weight(etype, intent)

            score_bonus = 0.0
            if "bm25" in stream_scores:
                score_bonus += min(float(stream_scores.get("bm25", 0.0) or 0.0), 50.0) * 0.0001
            for stream in ("vector", "chunk_vector"):
                if stream in stream_scores:
                    score_bonus += float(stream_scores.get(stream, 0.0) or 0.0) * 0.01
            return weighted_rrf * type_bonus + score_bonus

        text = " ".join([
            result.get("id", ""),
            result.get("type", ""),
            result.get("stream", ""),
            result.get("text", ""),
            " ".join(result.get("heading_path", [])),
        ]).lower()
        overlap = sum(1 for term in query_terms if term in text)
        streams = result.get("stream", "").split(",") if result.get("stream") else []
        stream_bonus = max((stream_weight.get(s, 0) for s in streams), default=0)
        # Apply entity type weight to fallback scoring path
        etype = result.get("type", "")
        type_bonus = _get_entity_type_weight(etype, intent)
        return (float(result.get("score", 0)) + overlap * 0.05 + stream_bonus * 0.01) * type_bonus

    ranked = [dict(r) for r in results]
    for item in ranked:
        item["rerank_score"] = round(score(item), 4)
    ranked.sort(key=lambda r: -r["rerank_score"])
    return ranked


def read_page_content(page_path: str) -> str:
    try:
        content = Path(page_path).read_text(encoding="utf-8")
        if content.startswith("---"):
            lines = content.split("\n")
            end = 0
            for i, line in enumerate(lines):
                if i > 0 and line.strip() == "---":
                    end = i
                    break
            if end > 0:
                content = "\n".join(lines[end + 1:])
        return content.strip()
    except (OSError, UnicodeDecodeError, PermissionError):
        return ""


def _format_page_context(page: dict, index: int) -> str:
    """Format a wiki page as structured context for the synthesis LLM.

    Includes entity type, name, relationships, and content to help the LLM
    understand what kind of information each page provides.
    """
    pid = page.get("id", f"unknown-{index}")
    ptype = page.get("type", "concept")
    pname = page.get("name", pid)
    content = page.get("text") or read_page_content(page.get("path", ""))
    if not content:
        return ""

    # Build metadata header
    header = f"[{ptype.upper()}] {pname}"

    # Include heading path if available (chunk results)
    heading = " > ".join(page.get("heading_path", []))
    if heading:
        header += f" | Section: {heading}"

    # Include graph relationships if available
    graph_boost = page.get("graph_boost", 0)
    cross_score = page.get("cross_score", 0)
    score_info = ""
    if graph_boost > 1.0:
        score_info += f" [graph-connected: +{int((graph_boost-1)*100)}%]"
    if cross_score:
        score_info += f" [relevance: {cross_score:.2f}]"

    return (
        f"## DOC {index}: {header}{score_info}\n"
        f"**Type**: {ptype} | **ID**: {pid}\n\n"
        f"{content[:3000]}"
    )


def synthesize_answer(query: str, pages: list[dict], config: dict, fmt: str = "markdown") -> str:
    if not pages:
        return "No relevant wiki pages found. Try adding more sources with `wiki add`."

    # Phase 4: Structured context formatting (4.1)
    contexts = []
    for i, page in enumerate(pages[:8]):  # Increased from 5 to 8 pages
        # Handle table/ledger results (structured data, no file path)
        if page.get("stream") in ("table", "table_vector"):
            table_name = page.get("display_name", page.get("table_name", "unknown"))
            row_id = page.get("row_id", "")
            row_data = page.get("row_data", {})
            if row_data:
                row_str = "\n".join(
                    f"- {k}: {v}" for k, v in row_data.items()
                    if not k.startswith("_")
                )
                contexts.append(
                    f"## DOC {i+1}: [TABLE] {table_name} (row {row_id})\n{row_str}"
                )
            continue

        ctx = _format_page_context(page, i + 1)
        if ctx:
            contexts.append(ctx)

    if not contexts:
        return "Wiki pages found but content could not be read."

    # Phase 4: Structured answer template (4.2) — guides LLM to complete answers
    format_prompts = {
        "markdown": """## Output Format
Structure your answer as follows:

**Direct Answer**: [2-3 sentence summary directly answering the question]

**Key Details**:
- [Specific fact 1 from the wiki pages] — [[source-id]]
- [Specific fact 2] — [[source-id]]
- [Include specific numbers, dates, names when available]

**Sources**:
- [[page-id-1]] — how this page contributed to the answer
- [[page-id-2]] — how this page contributed to the answer

**Related Topics**: [[related-1]], [[related-2]] (optional)

If a claim cannot be verified from the provided wiki pages, mark it as **[uncertain]**.""",

        "table": """## Output Format
Provide a comparison table comparing the key entities:

**Answer**: [Brief overview]

## Comparison Table

| Entity | Key Feature 1 | Key Feature 2 | Use Case |
|--------|--------------|--------------|----------|
| name | detail | detail | use case |

**Sources**: [[page-id-1]] — data source""",

        "timeline": """## Output Format
Provide a timeline of key events/milestones:

**Answer**: [Context for this timeline]

## Timeline

| Date/Version | Event | Significance |
|-------------|-------|-------------|
| 2024-01 | Event | Description |

**Sources**: [[page-id-1]] — supporting evidence""",

        "slides": """## Output Format
Create a Marp slide deck presentation. Use Marp syntax:

---
marp: true
theme: default
---

# [Title]

## Slide 1: Overview
- Key point 1
- Key point 2

---

## Slide 2: Details
...

**Sources**: [[page-id-1]]""",

        "json": """## Output Format
Output ONLY valid JSON (no markdown, no explanation):

{
  "answer": "Synthesized answer",
  "sources": [{"id": "page-id", "relevance": "why relevant"}],
  "related": ["related-1", "related-2"],
  "confidence": 0.85
}""",
    }

    # Detect query language for localized instructions
    is_chinese = any('一' <= c <= '鿿' for c in query)

    if is_chinese:
        system_prompt = f"""你是一个精确的维基查询引擎。你唯一的知识来源是下面提供的维基文档——你没有其他知识。

{format_prompts.get(fmt, format_prompts["markdown"])}

## ⚠️ 关键规则 — 违反任何一条都会产生错误结果
1. **禁止使用外部知识**: 你绝对不能使用未在提供的维基文档中明确说明的信息。如果文档没提到，你就不知道。
2. **每条声明必须引用**: 每个事实性声明后面必须跟上来源 [[page-id]]。无引用的声明将被拒绝。
3. **说"不知道"**: 如果维基文档没有足够信息来回答问题，明确说："维基文档中没有足够信息来回答此问题。"然后列出文档中已知的相关信息。
4. **禁止编造**: 不要编造事实、数字、日期、名称或关系。不确定的用 [不确定] 标注。
5. **写前验证**: 每写一句之前，先问自己："哪篇维基文档支持这句话？"如果找不到，就不要写。
6. **使用精确数值**: 当文档包含具体数字/日期/名称时，逐字使用原文。不要改述或近似。
7. **区分来源**: 如果多篇文档对同一主题有不同说法，明确标注分歧。
8. **简洁但完整**: 直接回答问题。不要添加与查询无直接关系的背景内容。"""
        user_prompt = f"""## 查询
{query}

## 维基文档（你唯一的知识来源）
{chr(10).join(contexts)}

## 任务
只使用上面维基文档中的信息回答问题。每个事实都要标明来源 [[id]]。如果文档中缺少答案，明确说明——不要猜测或使用外部知识。"""
    else:
        system_prompt = f"""You are a precise wiki query engine. Your ONLY knowledge source is the wiki documents provided below — you have NO other knowledge.

{format_prompts.get(fmt, format_prompts["markdown"])}

## ⚠️ CRITICAL RULES — Violating Any Will Produce Incorrect Results
1. **NO EXTERNAL KNOWLEDGE**: You MUST NOT use any information that is not explicitly stated in the provided wiki documents. If the documents don't mention something, you don't know it.
2. **CITE EVERY CLAIM**: Every factual claim MUST be followed by its source [[page-id]] inline. Example: "Transformers use self-attention [[transformer-paper]]." Claims without citations will be rejected.
3. **SAY "I DON'T KNOW"**: If the wiki documents don't contain enough information to answer the query, explicitly state: "The wiki does not contain sufficient information to answer this question." Then list what IS known from the documents.
4. **NO FABRICATION**: Do NOT invent facts, numbers, dates, names, or relationships. If you're unsure, use [uncertain].
5. **VERIFY BEFORE WRITING**: Before writing each sentence, ask yourself: "Which wiki document supports this?" If you can't point to one, don't write it.
6. **USE PRECISE VALUES**: When the documents contain specific numbers/dates/names, use them verbatim. Do not paraphrase or approximate.
7. **DISTINGUISH SOURCES**: If multiple documents say different things about the same topic, note the disagreement explicitly.
8. **CONCISE BUT COMPLETE**: Answer the query directly. Don't add background context unless it's directly relevant to the query."""

        user_prompt = f"""## Query
{query}

## Wiki Documents (YOUR ONLY KNOWLEDGE SOURCE)
{chr(10).join(contexts)}

## Task
Answer the query using ONLY information from the wiki documents above. For each fact, cite the source [[id]] inline immediately after the claim. If the documents lack the answer, say so explicitly — do NOT guess or use outside knowledge."""

    # First pass: generate answer
    answer = call_llm(system_prompt, user_prompt, config)

    # Second pass: self-verify (check claims against context for faithfulness)
    if answer and contexts and fmt == "markdown":
        answer = _self_verify_answer(query, answer, contexts, config)

    return answer


def _self_verify_answer(query: str, answer: str, contexts: list[str], config: dict) -> str:
    """Second-pass verification: ask LLM to check answer claims against contexts.

    Removes or marks claims that cannot be verified against the provided wiki documents.
    This catches hallucinations that slip through the first-pass generation.
    """
    if not answer or len(answer) < 20:
        return answer

    # Truncate contexts for verification (keep total under ~8k chars)
    total_ctx = 0
    trimmed_contexts = []
    for ctx in contexts:
        if total_ctx > 6000:
            break
        trimmed_contexts.append(ctx[:2000])
        total_ctx += len(ctx)

    # Detect query language for localized verification
    is_chinese = any('一' <= c <= '鿿' for c in query)

    if is_chinese:
        verify_prompt = f"""你是一个事实核查员。你的任务是验证AI生成的答案中的每一条声明是否能在提供的维基文档中找到依据。

## 维基文档（事实依据）
{chr(10).join(trimmed_contexts)}

## 待验证的AI生成答案
{answer[:3000]}

## 原始查询
{query}

## 指令
1. 逐句阅读AI答案。
2. 对每个事实声明，判断：
   - ✅ 已验证：维基文档中明确陈述
   - ⚠️ 推断：可从文档中合理推断但未明确陈述
   - ❌ 无依据：在维基文档中找不到（可能是幻觉）
3. 重写答案：
   - 保留所有已验证和推断的声明
   - 删除或标记无依据的声明，标注 ❌[无依据：原因]
   - 如果答案大部分无依据，替换为："维基文档中没有足够信息来确信地回答此问题。已知信息如下：[仅保留已验证的事实]"
4. 确保每条保留的声明都可以追溯到特定的维基文档。
5. 检查 [[id]] 引用是否存在于提供的文档中。引用不存在的文档ID的声明应标记为 ❌[引用不存在]。
6. 输出清理后的答案，保持原始格式。"""

        verify_system = "你是一个严谨的事实核查员。对照提供的文档逐条验证每项声明。删除无依据的声明。"
    else:
        verify_prompt = f"""You are a fact-checker. Your task is to verify each claim in an AI-generated answer against provided wiki documents.

## Wiki Documents (Ground Truth)
{chr(10).join(trimmed_contexts)}

## AI-Generated Answer to Verify
{answer[:3000]}

## Original Query
{query}

## Instructions
1. Read each sentence in the AI answer.
2. For each factual claim, determine if it is:
   - ✅ VERIFIED: explicitly stated in the wiki documents
   - ⚠️ INFERRED: can be reasonably inferred but not explicitly stated
   - ❌ UNSUPPORTED: not found in the wiki documents (likely hallucination)
3. Rewrite the answer:
   - Keep all VERIFIED and INFERRED claims
   - Remove or mark UNSUPPORTED claims with ❌[UNSUPPORTED: reason]
   - If the answer is mostly unsupported, replace it with: "The wiki documents do not contain sufficient information to confidently answer this query. Here is what is known: [only verified facts]"
4. Ensure every remaining claim is traceable to a specific wiki document.
5. Check that any [[id]] citations refer to documents that actually exist in the provided contexts. Claims citing non-existent IDs should be marked ❌[citation not found].
6. Output the cleaned answer in the same format as the original."""

        verify_system = "You are a meticulous fact-checker. Verify every claim against provided documents. Check citation validity. Remove unsupported claims."

    try:
        verified = call_llm(
            verify_system,
            verify_prompt,
            config,
        )
        if verified and len(verified) > 20:
            return verified
    except Exception:
        pass

    return answer


def file_answer_back(query: str, answer: str, sources: list[dict]) -> str:
    concepts_dir = PAGES_DIR / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    slug = query.lower().replace(" ", "-").replace("?", "")[:50]
    slug = "".join(c for c in slug if c.isalnum() or c == "-")

    page_path = concepts_dir / f"{slug}.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    frontmatter = f"""---
id: {slug}
type: concept
name: "{query[:50]}"
confidence: 0.80
source: query-generated
created: {now}
---

"""

    content = frontmatter + f"# {query[:50]}\n\n"
    content += f"**Generated from query**: {query}\n\n"
    content += answer.replace("**Answer**:", "## Answer\n\n").replace("**Sources**:", "\n## Sources\n\n").replace("**Related**:", "\n## Related\n\n")

    page_path.write_text(content, encoding="utf-8")

    graph_dir = WIKI_DIR / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    entities_file = graph_dir / "entities.json"

    entities = {}
    if entities_file.exists():
        entities = json.loads(entities_file.read_text(encoding="utf-8"))

    entities[slug] = {
        "id": slug,
        "type": "concept",
        "name": query[:50],
        "sources": ["query-generated"],
        "confidence": 0.80,
        "created": now,
    }

    entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")

    return str(page_path)


def query_wiki(query: str, file_back: bool = False, fmt: str = "markdown",
               synthesis: bool = True, debug_search: bool = False) -> dict:
    config = load_config()
    query_cfg = get_query_config()
    
    if not synthesis:
        pass
    elif "llm_synthesis" in query_cfg:
        synthesis = query_cfg.get("llm_synthesis", True)

    if debug_search:
        pages, trace = search_wiki(query, debug=True)
    else:
        pages = search_wiki(query)
        trace = {}

    if pages and not synthesis:
        # Fast path: return raw search results without LLM call
        lines = [f"## 搜索结果: {query}\n"]
        for i, p in enumerate(pages[:10], 1):
            snippet = _read_snippet(p["path"], query)
            lines.append(f"{i}. **[[{p['id']}]]** ({p['type']}) — score: {p['score']:.2f}")
            if snippet:
                lines.append(f"   > {snippet}")
            lines.append("")
        return {
            "query": query,
            "format": "fast",
            "answer": "\n".join(lines),
            "pages_searched": len(pages),
            "sources": [p.get("id", "unknown") for p in pages],
            "debug_search": trace if debug_search else {},
        }

    answer = synthesize_answer(query, pages, config, fmt=fmt) if pages else "No relevant wiki pages found."

    result = {
        "query": query,
        "format": fmt,
        "answer": answer,
        "pages_searched": len(pages),
        "sources": [p.get("id", "unknown") for p in pages],
    }
    if debug_search:
        result["debug_search"] = trace

    if file_back and pages:
        filed_path = file_answer_back(query, answer, pages)
        result["filed"] = filed_path

    return result


def _read_snippet(path: str, query: str, max_len: int = 120) -> str:
    """Extract a relevant snippet from a page, surrounding the query terms."""
    try:
        content = Path(path).read_text(encoding="utf-8")
        # Strip frontmatter
        content = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
        query_terms = [t for t in query.split() if len(t) >= 2]
        for term in query_terms:
            idx = content.lower().find(term.lower())
            if idx >= 0:
                start = max(0, idx - 40)
                end = min(len(content), idx + len(term) + max_len)
                snippet = content[start:end].replace("\n", " ").strip()
                return ("..." if start > 0 else "") + snippet + ("..." if end < len(content) else "")
        # Fallback: first non-empty line
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                return line[:max_len] + "..."
    except Exception:
        pass
    return ""


def main():
    parser = argparse.ArgumentParser(description="Query wiki and answer questions")
    parser.add_argument("query", help="Question to answer")
    parser.add_argument("--file-back", action="store_true", help="File answer back to wiki")
    parser.add_argument("--format", choices=["markdown", "table", "timeline", "slides", "json", "graph"],
                        default="markdown", help="Output format (default: markdown)")
    parser.add_argument("--no-synthesis", action="store_true",
                        help="Skip LLM synthesis — return raw search results (fast)")
    parser.add_argument("--debug-search", action="store_true",
                        help="Print search trace as JSON after the answer")
    args = parser.parse_args()

    if args.format == "graph":
        import subprocess
        import sys as _sys
        code, out = subprocess.run(
            [_sys.executable, str(Path(__file__).parent / "graph.py"), "show"],
            capture_output=True, text=True
        )
        print(out if code == 0 else f"Graph error: {out}")
        return

    result = query_wiki(args.query, file_back=args.file_back, fmt=args.format,
                        synthesis=not args.no_synthesis,
                        debug_search=args.debug_search)
    print(result["answer"])
    if args.debug_search:
        print("\n--- SEARCH DEBUG ---")
        print(json.dumps(result.get("debug_search", {}), indent=2, ensure_ascii=False, default=str))

    if args.file_back and result.get("filed"):
        print(f"\n---\nFiled to: {result['filed']}", file=sys.stderr)


if __name__ == "__main__":
    main()
