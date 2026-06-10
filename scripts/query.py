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
from config import get_config, get_wiki_dir, get_llm_config, get_api_url, get_query_config

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"


DEFAULT_SEARCH_STREAMS = ["metadata", "chunk", "bm25", "chunk_vector", "vector", "graph", "ledger"]

# ── Cross-encoder reranker (lazy-loaded) ──
_reranker_model = None
_RERANKER_NAME = "BAAI/bge-reranker-base"


def _get_reranker():
    """Lazy-load the cross-encoder reranker model."""
    global _reranker_model
    if _reranker_model is None:
        try:
            from FlagEmbedding import FlagReranker
            _reranker_model = FlagReranker(_RERANKER_NAME, use_fp16=True)
        except ImportError:
            return None
    return _reranker_model


def cross_encode_rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Re-rank candidates using a cross-encoder model for precise relevance scoring.

    Operates on top-20 candidates from RRF fusion, re-ranks them with
    BGE-reranker-base, and returns top_k results.
    """
    reranker = _get_reranker()
    if reranker is None or len(candidates) <= top_k:
        return candidates[:top_k]

    # Build pairs: [query, page_text]
    pairs = []
    for c in candidates[:20]:
        text = c.get("text", "")
        if not text:
            try:
                text = Path(c.get("path", "")).read_text(encoding="utf-8")[:2000]
            except Exception:
                text = f"{c.get('id', '')} {c.get('type', '')}"
        pairs.append([query, text[:2000]])

    try:
        scores = reranker.compute_score(pairs)
        # normalize scores to 0-1 range
        if isinstance(scores, list):
            for c, s in zip(candidates[:20], scores):
                c["cross_score"] = round(float(s), 4)
            candidates_sorted = sorted(
                candidates[:20], key=lambda x: -x.get("cross_score", 0)
            )
            return candidates_sorted[:top_k]
    except Exception:
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


def _llm_expand_query(query: str, plan: dict) -> list[str]:
    """Use LLM to generate 2-3 semantic query variants for better recall."""
    intent = plan.get("intent", "fact")
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
        resp = req.post(api_url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("message", {}).get("content", "") or
                data["choices"][0]["message"].get("content", "") or "")
        lines = [l.strip().lstrip("-•*#0123456789. ").strip()
                 for l in text.strip().split("\n") if l.strip()]
        return [l for l in lines if len(l) > 3 and l != query][:3]
    except Exception:
        return []  # best-effort, never block search


# Entity type weights for reranking \u2014 prioritize content-rich types.
TYPE_WEIGHTS: dict[str, float] = {
    "concept": 1.25, "technique": 1.25, "model": 1.15, "framework": 1.10,
    "benchmark": 0.95, "paper": 0.90, "certification": 0.90, "policy": 0.95,
    "entity": 0.90, "event": 0.85, "process": 0.95, "rule": 0.95,
    "algorithm": 1.20, "metric": 0.90, "tool": 0.95, "system": 0.90,
}

# Intent \u2192 preferred entity types for smarter reranking.
INTENT_TYPE_PREFERENCE: dict[str, list[str]] = {
    "fact": ["concept", "technique", "model", "algorithm", "framework"],
    "relationship": ["technique", "concept", "model", "framework"],
    "comparison": ["model", "framework", "benchmark", "technique"],
    "ledger_filter": ["entity", "event", "process"],
}

def _get_entity_type_weight(entity_type: str, intent: str) -> float:
    """Calculate entity type bonus based on query intent."""
    base = TYPE_WEIGHTS.get(entity_type, 1.0)
    preferred = INTENT_TYPE_PREFERENCE.get(intent, [])
    if entity_type in preferred:
        # Higher bonus for top-3 preferred types
        rank = preferred.index(entity_type)
        if rank == 0:
            base *= 1.15
        elif rank <= 2:
            base *= 1.08
        elif rank <= 4:
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


def synthesize_answer(query: str, pages: list[dict], config: dict, fmt: str = "markdown") -> str:
    if not pages:
        return "No relevant wiki pages found. Try adding more sources with `wiki add`."

    contexts = []
    for i, page in enumerate(pages[:5]):
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
                    f"--- TABLE: {table_name} (row {row_id}) ---\n{row_str}"
                )
            continue

        # Wiki page/chunk (unstructured markdown)
        content = page.get("text") or read_page_content(page.get("path", ""))
        if content:
            heading = " > ".join(page.get("heading_path", []))
            heading_line = f"\nHeading: {heading}" if heading else ""
            contexts.append(
                f"--- PAGE {i+1}: {page.get('id', 'unknown')} ---"
                f"{heading_line}\n{content[:2000]}"
            )

    if not contexts:
        return "Wiki pages found but content could not be read."

    format_prompts = {
        "markdown": """## Output Format
Provide a clear, concise answer with citations:

**Answer**: [Your synthesized answer]

**Sources**:
- [[page-id-1]] — relevant point

**Related**: [[related-entity-1]], [[related-entity-2]]""",

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

    system_prompt = f"""You are a wiki query engine. Answer questions based on the provided wiki pages.

{format_prompts.get(fmt, format_prompts["markdown"])}

## Rules
- Synthesize information from multiple pages
- Always cite sources with wikilinks
- Note contradictions if found
- Suggest related topics to explore"""

    user_prompt = f"""Query: {query}

Wiki Pages:
{chr(10).join(contexts)}

Answer the query based on these wiki pages."""

    return call_llm(system_prompt, user_prompt, config)


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
