#!/usr/bin/env python3
"""query.py — Query wiki and answer questions (Karpathy v1 + Rohit v2).

Operations:
- Search wiki pages (BM25 + metadata + graph + ledger)
- Synthesize answer from compiled wiki pages with citations

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
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _llm_utils import call_llm
from config import (
    get_embeddings_config,
    get_query_config,
    get_reranker_config,
    get_wiki_dir,
)


def _log_exc(msg: str = ""):
    """Log exception traceback to stderr for debugging."""
    if msg:
        print(f"  [WARN] {msg}: {traceback.format_exc()}", file=sys.stderr)
    else:
        print(f"  [WARN] {traceback.format_exc()}", file=sys.stderr)



WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"

DEFAULT_SEARCH_STREAMS = ["metadata", "bm25", "graph", "ledger"]


def enabled_search_streams() -> set[str]:
    """Return enabled retrieval streams from env/config."""
    env_value = os.environ.get("LLM_WIKI_SEARCH_STREAMS", "").strip()
    configured = env_value or str(get_query_config().get("search_streams", "") or "")
    defaults = set(DEFAULT_SEARCH_STREAMS)
    if get_embeddings_config().get("enabled"):
        defaults.add("vector")
    if not configured:
        return defaults
    if configured.lower() in {"all", "*"}:
        return defaults
    streams = {stream.strip() for stream in configured.split(",") if stream.strip()}
    if not env_value and get_embeddings_config().get("enabled"):
        streams.add("vector")
    return streams


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


# ═══════════════════════════════════════════════════════════════════════════
# Query planning & rewriting (lightweight, no extra LLM calls)
# ═══════════════════════════════════════════════════════════════════════════

def plan_query(query: str) -> dict:
    """Simple query planner for retrieval stream routing."""
    q = query.lower()
    ledger_terms = (
        "表", "台账", "预算", "金额", "状态", "字段", "行",
        "row", "table", "ledger", "sql",
    )
    graph_terms = ("影响", "依赖", "关系", "路径", "关联", "impact", "depends", "relationship")
    compare_terms = ("比较", "对比", "区别", "compare", "difference")

    preferred = ["metadata", "bm25", "graph", "ledger"]
    intent = "fact"
    if any(term in q for term in ledger_terms):
        intent = "ledger_filter"
        preferred = ["ledger", "metadata", "bm25", "graph"]
    elif any(term in q for term in graph_terms):
        intent = "relationship"
        preferred = ["graph", "metadata", "bm25", "ledger"]
    elif any(term in q for term in compare_terms):
        intent = "comparison"

    return {
        "intent": intent,
        "preferred_streams": preferred,
        "keywords": [t for t in re.split(r"\s+", query.strip()) if t],
    }


def _stream_weights(plan: dict) -> dict[str, float]:
    """Intent-aware retrieval weights for weighted RRF."""
    base = {"metadata": 1.2, "bm25": 1.2, "graph": 1.0, "ledger": 1.0, "vector": 1.0}
    intent = plan.get("intent")
    if intent == "ledger_filter":
        base.update({"ledger": 2.2, "metadata": 1.0, "bm25": 0.9})
    elif intent == "relationship":
        base.update({"graph": 2.0, "metadata": 1.2})
    elif intent == "comparison":
        base.update({"bm25": 1.3, "vector": 1.3, "graph": 1.2})
    return base


def rewrite_query(query: str, plan: dict) -> list[str]:
    """Generate lightweight lexical variants for better recall.

    Only does string-level transforms (normalization, hyphen/space swaps).
    No LLM calls — the wiki is already compiled, we just need to match it.
    """
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

    deduped = []
    seen = set()
    for variant in variants:
        variant = variant.strip()
        if variant and variant not in seen:
            seen.add(variant)
            deduped.append(variant)
    return deduped[:5]


# ═══════════════════════════════════════════════════════════════════════════
# Reranking (lightweight heuristics — no cross-encoder, no embeddings)
# ═══════════════════════════════════════════════════════════════════════════

# Conservative entity type weights for content-rich types
_TYPE_WEIGHTS: dict[str, float] = {
    "concept": 1.10, "technique": 1.10, "model": 1.08, "framework": 1.05,
    "algorithm": 1.10, "process": 1.05, "rule": 1.05, "policy": 1.05,
    "benchmark": 0.95, "paper": 0.92, "certification": 0.95, "event": 0.92,
    "entity": 0.95, "metric": 0.95, "tool": 0.95, "system": 0.95,
    "product": 0.95, "role": 0.95,
}

# Intent → preferred entity types for smarter reranking
_INTENT_TYPE_PREFERENCE: dict[str, list[str]] = {
    "fact": ["concept", "technique", "model", "algorithm", "framework"],
    "relationship": ["technique", "concept", "model", "framework"],
    "comparison": ["model", "framework", "benchmark", "technique"],
    "ledger_filter": ["entity", "event", "process"],
}


def _entity_type_weight(entity_type: str, intent: str) -> float:
    """Calculate entity type bonus based on query intent."""
    base = _TYPE_WEIGHTS.get(entity_type, 1.0)
    preferred = _INTENT_TYPE_PREFERENCE.get(intent, [])
    if entity_type in preferred:
        rank = preferred.index(entity_type)
        if rank == 0:
            base *= 1.08
        elif rank <= 2:
            base *= 1.04
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Improvement 5: Pre-search entity linking (O(n) symbol match, zero cost)
# ═══════════════════════════════════════════════════════════════════════════

def _extract_query_entities(query: str) -> dict[str, float]:
    """Extract entity mentions from a natural-language query using entities.json.

    O(n) string matching against all entity names/aliases — no LLM, no embeddings.
    Returns {entity_id: match_score} for entities explicitly mentioned in the query.
    Score: 1.0 = exact name match, 0.8 = name contained in query, 0.6 = query term in name.
    """
    entities = _get_entities()
    if not entities:
        return {}

    query_lower = query.lower()
    query_norm = re.sub(r"[\s_\-./:]+", "", query_lower)

    matches: dict[str, float] = {}
    for eid, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        names = [eid, str(entity.get("name", "")), str(entity.get("id", ""))]
        # Aliases from frontmatter
        aliases = entity.get("aliases", [])
        if isinstance(aliases, list):
            names.extend(str(a) for a in aliases)

        for name in names:
            name = str(name).strip()
            if not name or len(name) < 2:
                continue
            name_lower = name.lower()
            name_norm = re.sub(r"[\s_\-./:]+", "", name_lower)

            # Tier 1: exact normalized match (e.g., "MLA" = "mla")
            if name_norm == query_norm or name_lower == query_lower:
                matches[eid] = 1.0
                break
            # Tier 2: entity name appears as substring in query ("Multi-head Latent Attention" in query)
            if len(name_norm) >= 3 and name_norm in query_norm:
                matches[eid] = max(matches.get(eid, 0), 0.85)
            # Tier 3: query term appears in entity name/alias
            elif len(name_lower) >= 3 and name_lower in query_lower:
                matches[eid] = max(matches.get(eid, 0), 0.65)

    return matches


# ═══════════════════════════════════════════════════════════════════════════
# Improvement 2: Graph-powered ranking (knowledge graph as ranking signal)
# ═══════════════════════════════════════════════════════════════════════════

def _graph_boost(results: list[dict], query_entities: dict[str, float]) -> list[dict]:
    """Annotate results with graph connection strength to query-matched entities.

    Does NOT modify scores — just adds a ``graph_boost`` annotation. The actual
    ranking formula in ``rerank_results`` consumes this as signal.

    Direct entity match: marks as ``graph_boost`` = 1.0 + 0.25*match_score
    1-hop neighbor: marks as ``graph_boost`` = 1.0 + 0.15*connections
    """
    if not query_entities:
        return results

    try:
        import json as _json

        edges_file = WIKI_DIR / "graph" / "edges.json"
        if not edges_file.exists():
            return results
        edges_data = _json.loads(edges_file.read_text(encoding="utf-8"))
        all_edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []
    except Exception:
        return results

    if not all_edges:
        return results

    # Build 1-hop adjacency
    neighbors: dict[str, set[str]] = {}
    for edge in all_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            neighbors.setdefault(src, set()).add(tgt)
            neighbors.setdefault(tgt, set()).add(src)

    query_entity_ids = set(query_entities.keys())

    for r in results:
        eid = r.get("id", "")
        boost = 0.0

        # Direct entity match: result IS a query entity
        if eid in query_entities:
            match_score = query_entities[eid]
            boost = 0.25 * match_score  # up to +25%

        # 1-hop neighbor of query entities
        if eid in neighbors:
            connected = neighbors[eid] & query_entity_ids
            if connected:
                boost = max(boost, min(len(connected) * 0.15, 0.30))

        if boost > 0:
            r["graph_boost"] = round(1.0 + boost, 3)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Improvement 1: Clear 3-signal ranking formula
# ═══════════════════════════════════════════════════════════════════════════

def rerank_results(
    query: str,
    results: list[dict],
    plan: dict,
    query_entities: dict[str, float] | None = None,
) -> list[dict]:
    """Rank results with three clear, independently-weighted signals.

    Signal 1 — BM25 keyword relevance (weight 0.5):
        Normalized BM25 score from full-page search. Excels at term-level matching.

    Signal 2 — Metadata exact match (weight 0.30):
        Did the query explicitly name this entity or its aliases? High-precision
        signal from ``_extract_query_entities`` and metadata stream ranks.

    Signal 3 — Graph entity signal (weight 0.20):
        Knowledge graph topology from ``_graph_boost``. Direct entity matches
        and 1-hop neighbors get boosted. Captures semantic relatedness.

    All signals are in [0, 1]. Entity type weighting (±5%) is applied as a
    final multiplier.
    """
    if not results:
        return results

    query_entities = query_entities or {}
    intent = plan.get("intent", "fact")

    # ── Compute normalized BM25 scores across the candidate set ──
    bm25_raw: dict[str, float] = {}
    max_bm25 = 1.0
    for r in results:
        stream_scores = r.get("stream_scores", {})
        bm25 = float(stream_scores.get("bm25", 0) or 0)
        bm25_raw[r.get("id", "")] = bm25
        if bm25 > max_bm25:
            max_bm25 = bm25

    def score(result: dict) -> float:
        eid = result.get("id", "")
        etype = result.get("type", "")

        # ── Signal 1: BM25 (0.5 weight) ──
        raw = bm25_raw.get(eid, 0)
        signal_bm25 = (raw / max_bm25) * 0.5 if max_bm25 > 0 else 0

        # ── Signal 2: Metadata exact match (0.30 weight) ──
        signal_meta = 0.0
        if eid in query_entities:
            # Direct entity mention → strong signal
            signal_meta = query_entities[eid] * 0.30
        # Also reward high metadata stream rank
        stream_ranks = result.get("stream_ranks", {})
        meta_rank = stream_ranks.get("metadata")
        if meta_rank and int(meta_rank) <= 3:
            # rank 1 → +0.18, rank 2 → +0.12, rank 3 → +0.06
            signal_meta = max(signal_meta, (4 - int(meta_rank)) * 0.06)

        # ── Signal 3: Graph entity signal (0.20 weight) ──
        signal_graph = 0.0
        graph_boost = result.get("graph_boost", 1.0)
        if graph_boost > 1.0:
            signal_graph = (graph_boost - 1.0) * 0.8  # scale to ~0.20 max

        # ── Entity type micro-adjustment (±5%) ──
        type_w = _entity_type_weight(etype, intent)

        signal_rrf = min(float(result.get("score", 0) or 0) * 8.0, 1.0) * 0.25
        stream_names = set(str(result.get("stream", "")).split(","))
        signal_special = 0.15 if stream_names & {"ledger", "vector"} else 0.0
        total = (signal_rrf + signal_bm25 + signal_meta + signal_graph + signal_special) * type_w
        return total

    ranked = [dict(r) for r in results]
    for item in ranked:
        item["rerank_score"] = round(score(item), 4)
    ranked.sort(key=lambda r: -r["rerank_score"])
    return ranked


# ═══════════════════════════════════════════════════════════════════════════
# Improvement B: Fact-based precision ranking (zero extra cost)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# Cross-link wiki pages with ledger tables (台账 ↔ Wiki 双向关联)
# ═══════════════════════════════════════════════════════════════════════════

def _cross_link_wiki_ledger(results: list[dict]) -> list[dict]:
    """Bidirectional cross-linking between wiki pages and ledger table rows.

    Problem: wiki pages and ledger data are retrieved independently and
    surfaced as disconnected results. A query about "Project Alpha" should
    return BOTH the wiki page AND the ledger row, with each referencing
    the other.

    This function does lightweight entity resolution:
    1. Extract entity-like values from ledger row columns (names, IDs)
    2. Match against entities.json → find related wiki pages
    3. Extract entity names from wiki pages → find related ledger rows
    4. Annotate both sides with cross-references

    O(n*m) string matching. Zero LLM calls. Sub-millisecond.
    """
    # Separate wiki page results from ledger results
    wiki_results = [r for r in results if r.get("stream") not in ("table", "table_vector", "ledger")]
    ledger_results = [r for r in results if r.get("stream") in ("table", "table_vector", "ledger")]

    if not ledger_results or not wiki_results:
        return results  # Nothing to cross-link

    entities = _get_entities()
    if not entities:
        return results

    # Build entity lookup: normalized name → entity_id
    name_to_eid: dict[str, str] = {}
    for eid, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        for name in [eid, str(entity.get("name", "")), str(entity.get("id", ""))]:
            name_norm = _normalize_entity_name(name)
            if name_norm and len(name_norm) >= 2:
                name_to_eid[name_norm] = eid
        for alias in (entity.get("aliases") or []):
            alias_norm = _normalize_entity_name(str(alias))
            if alias_norm and len(alias_norm) >= 2:
                name_to_eid[alias_norm] = eid

    # Wiki page IDs for quick lookup
    wiki_ids: dict[str, dict] = {r.get("id", ""): r for r in wiki_results if r.get("id")}

    # ── Direction 1: Ledger → Wiki ──
    for lr in ledger_results:
        linked_pages: list[str] = []

        if lr.get("is_table_level"):
            # Table-level result: match table name/description against entities
            display_name = lr.get("display_name", "")
            table_name = lr.get("table_name", "")
            table_searchable = _normalize_entity_name(f"{display_name} {table_name}")
            for name_norm, eid in name_to_eid.items():
                if len(name_norm) >= 2 and name_norm in table_searchable:
                    if eid in wiki_ids and eid not in linked_pages:
                        linked_pages.append(eid)
        else:
            # Row-level result: match column values
            row_data = lr.get("row_data", {})
            for key, val in row_data.items():
                if not isinstance(val, str):
                    continue
                val = val.strip()
                if not val or len(val) < 2:
                    continue
                if val.replace(".", "").replace("-", "").replace("/", "").isdigit():
                    continue

                val_norm = _normalize_entity_name(val)
                if val_norm in name_to_eid:
                    eid = name_to_eid[val_norm]
                    if eid in wiki_ids and eid not in linked_pages:
                        linked_pages.append(eid)
                        continue

                for name_norm, eid in name_to_eid.items():
                    if len(name_norm) >= 3 and name_norm in val_norm:
                        if eid in wiki_ids and eid not in linked_pages:
                            linked_pages.append(eid)

        if linked_pages:
            lr["linked_wiki_pages"] = linked_pages

    # ── Direction 2: Wiki → Ledger (table-level + row-level) ──
    for wr in wiki_results:
        page_id = wr.get("id", "")
        page_name_norm = _normalize_entity_name(page_id)
        linked_tables: dict[str, dict] = {}  # table_name → {schema, matching_rows}

        for lr in ledger_results:
            table_name = lr.get("display_name", lr.get("table_name", ""))
            table_key = table_name

            if lr.get("is_table_level"):
                # Table-level: check if wiki entity name matches table metadata
                table_schema = lr.get("table_schema", {})
                sample_rows = lr.get("sample_rows", [])
                table_searchable = _normalize_entity_name(
                    f"{table_name} {' '.join(table_schema.keys())}"
                )
                if page_name_norm and len(page_name_norm) >= 2 and page_name_norm in table_searchable:
                    if table_key not in linked_tables:
                        linked_tables[table_key] = {
                            "table": table_name,
                            "actual_name": lr.get("table_name", ""),
                            "schema": table_schema,
                            "sample_rows": sample_rows,
                            "match_type": "table_concept",
                        }
            else:
                # Row-level: check column values
                row_data = lr.get("row_data", {})
                for key, val in row_data.items():
                    if not isinstance(val, str):
                        continue
                    val_norm = _normalize_entity_name(val)
                    if page_name_norm and len(page_name_norm) >= 2 and page_name_norm in val_norm:
                        if table_key not in linked_tables:
                            linked_tables[table_key] = {
                                "table": table_name,
                                "actual_name": lr.get("table_name", ""),
                                "schema": lr.get("table_schema", {}),
                                "sample_rows": [],
                                "match_type": "row_value",
                            }
                        # Add matching row
                        linked_tables[table_key].setdefault("matching_rows", [])
                        linked_tables[table_key]["matching_rows"].append({
                            "field": key,
                            "value": val,
                            "row_data": {k: v for k, v in row_data.items() if not str(k).startswith("_")},
                        })
                        break

        if linked_tables:
            wr["linked_ledger_tables"] = list(linked_tables.values())

    return results


def _normalize_entity_name(name: str) -> str:
    """Normalize entity names for cross-referencing."""
    return re.sub(r"[\s_\-./:]+", "", str(name).lower())


def _lead_section_boost(
    results: list[dict],
    query: str,
) -> list[dict]:
    """Boost pages where query terms concentrate in the lead section.

    The first ~500 chars of a wiki page (Overview + Key Details/Facts)
    are the most information-dense. If query terms cluster there rather
    than scattered throughout, the page is likely more relevant.

    Simple heuristic: count query term density in first 800 chars of body
    vs. full page. Pages with high lead density get a small boost.
    O(n) string matching, sub-millisecond.
    """
    if not results:
        return results

    query_terms = {t.lower() for t in re.findall(r"[\w一-鿿]+", query) if len(t) >= 2}
    if not query_terms:
        return results

    for c in results:
        path = c.get("path", "")
        if not path:
            continue
        try:
            content = Path(path).read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                body = parts[2] if len(parts) >= 3 else content
            else:
                body = content
        except Exception:
            continue

        body_lower = body.lower()
        lead = body_lower[:800]

        lead_hits = sum(1 for t in query_terms if t in lead)
        if lead_hits >= 2:
            # Terms cluster in the lead → likely relevant
            boost = min(lead_hits * 0.03, 0.15)
            c["rerank_score"] = c.get("rerank_score", 0) + boost
            c["lead_boost"] = round(boost, 3)

    results.sort(key=lambda x: -x.get("rerank_score", 0))
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Core search: BM25 + metadata + graph + ledger, fused via RRF
# ═══════════════════════════════════════════════════════════════════════════

def reciprocal_rank_merge(results: list[dict], limit: int = 10) -> list[dict]:
    """Deduplicate one stream while preserving rank evidence across query variants."""
    merged: dict[str, dict] = {}
    for rank, item in enumerate(results, 1):
        key = item.get("path") or item.get("file") or str(rank)
        if key not in merged:
            merged[key] = dict(item)
            merged[key]["variant_score"] = 0.0
        merged[key]["variant_score"] += 1.0 / (60 + rank)
        merged[key]["score"] = max(
            float(merged[key].get("score", 0)), float(item.get("score", 0))
        )
    sorted_items = sorted(
        merged.values(),
        key=lambda item: (float(item.get("score", 0)), item.get("variant_score", 0)),
        reverse=True,
    )
    return sorted_items[:limit]


_entities_cache: dict | None = None


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
    entities = _get_entities()
    if eid in entities:
        return entities[eid].get("type", "concept")
    return "concept"


def _lexical_candidates(
    search_function,
    query_variants: list[str],
    initial_limit: int,
    required_count: int,
    scope_filter: set[str],
    status_filter: set[str],
) -> list[dict]:
    """Over-fetch and refill after access/lifecycle filters until exhausted."""
    fetch_limit = initial_limit
    while True:
        batches = [search_function(variant, fetch_limit) for variant in query_variants]
        merged = reciprocal_rank_merge(
            [item for batch in batches for item in batch], limit=fetch_limit
        )
        filtered = _filter_by_allowed_scopes(merged, scope_filter)
        filtered = _filter_by_excluded_statuses(filtered, status_filter)
        exhausted = all(len(batch) < fetch_limit for batch in batches)
        if len(filtered) >= required_count or exhausted or fetch_limit >= 10_000:
            return filtered
        fetch_limit = min(fetch_limit * 2, 10_000)


def search_wiki(
    query: str,
    limit: int = 5,
    debug: bool = False,
    allowed_scopes: list[str] | set[str] | None = None,
    exclude_statuses: list[str] | set[str] | None = None,
) -> list[dict] | tuple[list[dict], dict]:
    """Hybrid search: metadata + BM25 + graph + ledger, fused by RRF.

    Wiki-native design: searches compiled wiki pages, not raw source chunks.
    No embeddings, no cross-encoders, no chunking. The quality comes from
    the compile step — well-structured wiki pages with typed entities and
    relationships.
    """
    all_streams: list[list[dict]] = []
    candidate_limit = max(limit * 8, 20)
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
    futures: dict[str, Future] = {}
    executor: ThreadPoolExecutor | None = None
    if get_query_config().get("parallel_search", True):
        executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="wiki-search")
        if "graph" in enabled_streams:
            try:
                from search import graph_search

                futures["graph"] = executor.submit(
                    graph_search, query, str(WIKI_DIR / "graph"), candidate_limit
                )
            except Exception as e:
                trace["streams"]["graph_error"] = str(e)
        if "ledger" in enabled_streams:
            try:
                from ledger import search_ledgers as ledger_search

                futures["ledger"] = executor.submit(ledger_search, query, candidate_limit)
            except Exception as e:
                trace["streams"]["ledger_error"] = str(e)
        if "vector" in enabled_streams:
            try:
                from zvec_backend import vector_search

                futures["vector"] = executor.submit(
                    vector_search,
                    query,
                    PAGES_DIR,
                    WIKI_DIR,
                    get_embeddings_config(),
                    candidate_limit,
                )
            except Exception as e:
                trace["streams"]["vector_error"] = str(e)

    # Stream 1: Metadata search (aliases, keywords, questions, summary)
    if "metadata" in enabled_streams:
        try:
            from search import metadata_search
            metadata_results = _lexical_candidates(
                lambda variant, fetch_limit: metadata_search(
                    variant, str(PAGES_DIR), limit=fetch_limit
                ),
                query_variants,
                candidate_limit,
                limit,
                scope_filter,
                status_filter,
            )
            trace["streams"]["metadata"] = metadata_results
            if metadata_results:
                all_streams.append(metadata_results)
        except Exception as e:
            trace["streams"]["metadata_error"] = str(e)
            _log_exc("stream failed")

    # Stream 2: BM25 keyword search (full wiki pages, not chunks)
    if "bm25" in enabled_streams:
        try:
            from search import bm25_search
            bm25_results = _lexical_candidates(
                lambda variant, fetch_limit: bm25_search(
                    variant, str(PAGES_DIR), limit=fetch_limit
                ),
                query_variants,
                candidate_limit,
                limit,
                scope_filter,
                status_filter,
            )
            trace["streams"]["bm25"] = bm25_results
            if bm25_results:
                all_streams.append(bm25_results)
        except Exception as e:
            trace["streams"]["bm25_error"] = str(e)
            _log_exc("stream failed")

    # Stream 3: Graph entity search (symbolic name matching + traversal)
    if "graph" in enabled_streams:
        try:
            if "graph" in futures:
                graph_results = futures["graph"].result()
            else:
                from search import graph_search

                graph_results = graph_search(
                    query, str(WIKI_DIR / "graph"), limit=candidate_limit
                )
            trace["streams"]["graph_raw"] = graph_results
            if graph_results:
                converted = []
                for g in graph_results:
                    eid = g.get("entity_id", "")
                    path_value = g.get("path", "")
                    page_path = Path(path_value) if path_value else Path("")
                    if not page_path.exists():
                        from search import _page_path_for_id

                        resolved = _page_path_for_id(eid, PAGES_DIR)
                        page_path = Path(resolved) if resolved else Path("")
                    if page_path.exists():
                        converted.append({
                            "file": eid,
                            "path": str(page_path),
                            "score": g.get("confidence", 0.5),
                            "stream": "graph",
                            "text": g.get("name", ""),
                        })
                if converted:
                    trace["streams"]["graph"] = converted
                    all_streams.append(converted)
        except Exception as e:
            trace["streams"]["graph_error"] = str(e)
            _log_exc("stream failed")

    # Stream 4: Ledger search (structured tables)
    if "ledger" in enabled_streams:
        try:
            if "ledger" in futures:
                ledger_results = futures["ledger"].result()
            else:
                from ledger import search_ledgers as ledger_search

                ledger_results = ledger_search(query, limit=candidate_limit)
            trace["streams"]["ledger_raw"] = ledger_results
            if ledger_results:
                converted = []
                for lr in ledger_results:
                    converted.append({
                        "file": lr["id"],
                        "path": f"table://{lr['id']}",
                        "score": lr.get("score", 1),
                        "stream": "ledger",
                        "ledger_name": lr["name"],
                        "display_name": lr["name"],
                        "table_name": lr["id"],
                        "ledger_fields": lr.get("fields", []),
                        "ledger_preview": lr.get("preview", []),
                        "row_data": (lr.get("preview") or [{}])[0],
                    })
                all_streams.append(converted)
                trace["streams"]["ledger"] = converted
        except Exception as e:
            trace["streams"]["ledger_error"] = str(e)
            _log_exc("stream failed")

    # Stream 5: Optional Zvec semantic search over compiled OKF concepts
    if "vector" in enabled_streams:
        try:
            if "vector" in futures:
                vector_results = futures["vector"].result()
            else:
                from zvec_backend import vector_search

                vector_results = vector_search(
                    query,
                    PAGES_DIR,
                    WIKI_DIR,
                    get_embeddings_config(),
                    limit=candidate_limit,
                )
            vector_results = _filter_by_allowed_scopes(vector_results, scope_filter)
            vector_results = _filter_by_excluded_statuses(vector_results, status_filter)
            trace["streams"]["vector"] = vector_results
            if vector_results:
                all_streams.append(vector_results)
        except Exception as e:
            trace["streams"]["vector_error"] = str(e)
            _log_exc("vector stream failed")

    if executor is not None:
        executor.shutdown(wait=True)

    # Fuse streams with RRF
    if len(all_streams) >= 2:
        try:
            from search import reciprocal_rank_fusion
            fused = reciprocal_rank_fusion(all_streams, weights=_stream_weights(plan))
            trace["fused"] = fused
            results = []
            seen = set()
            for f in fused[:max(limit * 4, limit)]:
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
                        "text": f.get("text", ""),
                        "stream_ranks": f.get("stream_ranks", {}),
                        "stream_scores": f.get("stream_scores", {}),
                    })
            if results:
                # Improvement 5: pre-search entity linking
                query_entities = _extract_query_entities(query)
                trace["query_entities"] = query_entities
                # Improvement 2: graph topology annotation
                results = _graph_boost(results, query_entities)
                # Improvement 1: 3-signal ranking formula
                results = rerank_results(query, results, plan, query_entities)
                # B: lead-section density boost
                results = _lead_section_boost(results, query)
                # Cross-link wiki pages with ledger data (台账 ↔ Wiki)
                results = _cross_link_wiki_ledger(results)
                results = _filter_by_allowed_scopes(results, scope_filter)
                results = _filter_by_excluded_statuses(results, status_filter)
                from rerank import rerank

                results = rerank(query, results, get_reranker_config(), limit)
                trace["reranked"] = results
                return (results[:limit], trace) if debug else results[:limit]
        except Exception as e:
            trace["fusion_error"] = str(e)
            _log_exc("fusion failed")
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
                    "text": r.get("text", ""),
                })
        if results:
            query_entities = _extract_query_entities(query)
            trace["query_entities"] = query_entities
            results = _graph_boost(results, query_entities)
            results = rerank_results(query, results, plan, query_entities)
            # B: lead-section density boost
            results = _lead_section_boost(results, query)
            # Cross-link wiki pages with ledger data
            results = _cross_link_wiki_ledger(results)
            results = _filter_by_allowed_scopes(results, scope_filter)
            results = _filter_by_excluded_statuses(results, status_filter)
            from rerank import rerank

            results = rerank(query, results, get_reranker_config(), limit)
            trace["reranked"] = results
            return (results[:limit], trace) if debug else results[:limit]

    # Fallback: entity name substring match against entities.json
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
                from search import _page_path_for_id

                resolved = _page_path_for_id(eid, PAGES_DIR)
                page_path = Path(resolved) if resolved else Path("")
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


# ═══════════════════════════════════════════════════════════════════════════
# Answer synthesis
# ═══════════════════════════════════════════════════════════════════════════

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


MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target><[^>]+>|[^)\n]+)\)")
_IMAGE_TITLE_RE = re.compile(r'''\s+(".*"|'.*?'|\(.*\))\s*$''')


def _strip_image_title(target: str) -> str:
    """Return the URL/path portion of a Markdown image target.

    Drops an optional CommonMark title (``"..."``, ``'...'``, ``(...)``) and
    angle brackets so ``![alt](images/fig.png "Figure 1")`` resolves the image
    instead of treating the title as part of the filename.
    """
    if target.startswith("<"):
        end = target.find(">")
        if end != -1:
            return target[1:end].strip()
    match = _IMAGE_TITLE_RE.search(target)
    if match:
        return target[: match.start()].strip()
    return target


def extract_page_images(page_path: str) -> list[dict[str, str]]:
    """Return every image referenced by a compiled page with resolved local paths."""
    path = Path(page_path)
    content = read_page_content(page_path)
    if not content:
        return []
    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in MARKDOWN_IMAGE_RE.finditer(content):
        alt = match.group("alt").strip()
        target = _strip_image_title(match.group("target").strip())
        lowered = target.lower()
        local_path = ""
        display_url = target
        if not lowered.startswith(("http://", "https://", "data:", "blob:")):
            candidate = Path(target[7:] if lowered.startswith("file://") else target).expanduser()
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            candidate = candidate.resolve()
            if candidate.is_file():
                local_path = str(candidate)
                display_url = local_path
        identity = local_path or display_url
        if identity in seen:
            continue
        seen.add(identity)
        images.append(
            {
                "alt": alt,
                "url": display_url,
                "path": local_path,
                "markdown": f"![{alt}]({display_url})",
            }
        )
    return images


def _attach_page_images(pages: list[dict]) -> list[dict]:
    """Annotate retrieved pages with their image evidence."""
    annotated: list[dict] = []
    for page in pages:
        item = dict(page)
        item["images"] = extract_page_images(str(item.get("path", "")))
        annotated.append(item)
    return annotated


def _collect_retrieved_images(pages: list[dict]) -> list[dict[str, str]]:
    """Deduplicate images while retaining the concept that surfaced each one."""
    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in pages:
        for image in page.get("images", []):
            identity = image.get("path") or image.get("url")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            images.append({**image, "source_id": str(page.get("id", "unknown"))})
    return images


def select_evidence_sections(content: str, query: str, max_chars: int = 2800) -> str:
    """Select high-value sections from a compiled OKF concept without raw chunking."""
    if len(content) <= max_chars:
        return _reorder_for_facts(content)
    terms = {term.lower() for term in re.findall(r"[\w一-鿿]+", query) if len(term) >= 2}
    matches = list(re.finditer(r"^#{1,6}\s+.+$", content, re.MULTILINE))
    sections: list[tuple[float, int, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section = content[match.start() : end].strip()
        lowered = section.lower()
        heading = match.group(0).lower()
        score = sum(2.0 if term in heading else 1.0 for term in terms if term in lowered)
        if any(
            label in heading
            for label in (
                "key facts",
                "关键事实",
                "schema",
                "法条",
                "formula",
                "公式",
                "citations",
                "来源",
            )
        ):
            score += 2.5
        sections.append((score, index, section))
    if not sections:
        return content[:max_chars]
    selected = sorted(sections, key=lambda item: (-item[0], item[1]))
    output: list[tuple[int, str]] = []
    used = 0
    for score, index, section in selected:
        if score <= 0 and output:
            continue
        remaining = max_chars - used
        if remaining <= 120:
            break
        excerpt = section[:remaining]
        output.append((index, excerpt))
        used += len(excerpt) + 2
    return "\n\n".join(section for _, section in sorted(output))


def _format_page_context(page: dict, index: int, query: str = "") -> str:
    """Format a wiki page as structured context for the synthesis LLM.

    Reorders content to put Key Details / 关键细节 section FIRST (before Overview),
    so the LLM can't miss the precise facts in **key**: value format.
    """
    pid = page.get("id", f"unknown-{index}")
    ptype = page.get("type", "concept")
    pname = page.get("name", pid)
    # Read full page content from file — search snippets are incomplete
    content = read_page_content(page.get("path", ""))
    if not content:
        content = page.get("text", "")
        if not content:
            return ""

    # Reorder: Key Details section first, then Overview, then rest
    reordered = select_evidence_sections(content, query)

    header = f"[{ptype.upper()}] {pname}"

    graph_boost = page.get("graph_boost", 0)
    score_info = ""
    if graph_boost > 1.0:
        score_info += f" [graph-connected: +{int((graph_boost-1)*100)}%]"

    # Append linked ledger data if present (table-level with schema + rows)
    ledger_block = ""
    linked_tables = page.get("linked_ledger_tables", [])
    if linked_tables:
        ledger_block = "\n\n### 📊 Linked Ledger Data (台账关联数据)\n"
        for lt in linked_tables[:3]:
            match_label = "按表名/字段匹配" if lt.get("match_type") == "table_concept" else "按行数据匹配"
            ledger_block += f"\n**表: {lt['table']}** ({match_label})\n"
            # Show schema
            schema = lt.get("schema", {})
            if schema:
                col_names = list(schema.keys())[:8]
                ledger_block += f"字段: {', '.join(col_names)}\n"
            # Show sample rows or matching rows
            rows = lt.get("sample_rows") or lt.get("matching_rows") or []
            if rows:
                ledger_block += "数据示例:\n"
                for row in rows[:5]:
                    if isinstance(row, dict):
                        if "row_data" in row:
                            row = row["row_data"]
                        flat = ", ".join(
                            f"{k}={v}" for k, v in row.items()
                            if not str(k).startswith("_")
                        )
                        ledger_block += f"  - {flat}\n"
            ledger_block += "\n"

    image_block = ""
    images = page.get("images") or extract_page_images(page.get("path", ""))
    if images:
        image_block = "\n\n### Referenced Source Images（引用原图）\n\n"
        image_block += "\n\n".join(image["markdown"] for image in images)

    return (
        f"## DOC {index}: {header}{score_info}\n"
        f"**Type**: {ptype} | **ID**: {pid}\n\n"
        f"{reordered}"
        f"{ledger_block}"
        f"{image_block}"
    )


def _reorder_for_facts(content: str) -> str:
    """Reorder page content: put Key Details section before Overview.

    Wiki pages follow the structure: # Title → ## Overview → ## Key Details → ## Relationships
    The precise facts are in Key Details as `**key**: value` bullets.
    If we put this section first, the LLM can't miss the specific values.
    """
    # Find the Key Details section (English + Chinese)
    detail_match = re.search(
        r'(##\s+(?:Key Details|关键细节)\s*\n.*?)(?=\n##\s+(?:Relationships|关联关系|Source Context|来源上下文)|\Z)',
        content, re.DOTALL,
    )
    overview_match = re.search(
        r'(##\s+(?:Overview|概述)\s*\n.*?)(?=\n##\s+(?:Key Details|关键细节|Key Facts|关键事实)|\Z)',
        content, re.DOTALL,
    )

    if not detail_match:
        return content  # No Key Details section found, return as-is

    # Extract parts
    title_end = content.find('\n## ')
    if title_end < 0:
        title_end = len(content)

    title_section = content[:title_end]
    detail_section = detail_match.group(1)
    rest_start = detail_match.end()
    rest = content[rest_start:]

    # Remove the detail section from rest (it's now at the front)
    if overview_match:
        overview = overview_match.group(1)
        # Put: Title → Key Details → Overview → rest (without duplicate detail)
        return f"{title_section}\n\n{detail_section.strip()}\n\n{overview.strip()}\n\n{rest.strip()}"
    else:
        return f"{title_section}\n\n{detail_section.strip()}\n\n{rest.strip()}"


def synthesize_answer(query: str, pages: list[dict], fmt: str = "markdown") -> str:
    if not pages:
        return "No relevant wiki pages found. Try adding more sources with `wiki add`."

    contexts = []
    for i, page in enumerate(pages[:8]):
        # Handle table/ledger results with wiki cross-links
        if set(str(page.get("stream", "")).split(",")) & {"table", "table_vector", "ledger"}:
            table_name = page.get("display_name", page.get("table_name", "unknown"))
            row_id = page.get("row_id", "")
            row_data = page.get("row_data", {})
            if row_data:
                row_str = "\n".join(
                    f"- {k}: {v}" for k, v in row_data.items()
                    if not k.startswith("_")
                )
                # Show linked wiki pages for this ledger row
                linked = page.get("linked_wiki_pages", [])
                linked_str = ""
                if linked:
                    linked_str = f"\n**Related Wiki Pages**: {', '.join(f'[[{p}]]' for p in linked)}"
                contexts.append(
                    f"## DOC {i+1}: [TABLE] {table_name} (row {row_id}){linked_str}\n{row_str}"
                )
            continue

        ctx = _format_page_context(page, i + 1, query)
        if ctx:
            contexts.append(ctx)

    if not contexts:
        return "Wiki pages found but content could not be read."

    # Structured answer template — guides LLM to complete, cited answers
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
Provide a comparison table:

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
Create a Marp slide deck presentation:

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

    is_chinese = any('一' <= c <= '鿿' for c in query)
    contexts_text = "\n".join(contexts)

    if is_chinese:
        system_prompt = f"""你是一个精确的维基查询引擎。
你唯一的知识来源是下面提供的维基文档——你没有其他知识。

{format_prompts.get(fmt, format_prompts["markdown"])}

## ⚠️ 关键规则 — 违反任何一条都会产生错误结果
0. **★先提取再判断（最重要！）**:
在说"不知道"之前，逐篇仔细阅读每篇文档的每个部分。文档的"关键细节/Key Details"部分用
`**属性**: 值` 格式列出了精确事实——这些就是你需要的答案。提取所有数字、日期、名称。
只有确认所有文档都没有相关信息时，才能说"不知道"。漏读文档中的数值是最严重的错误！
1. **禁止使用外部知识**:
你绝对不能使用未在提供的维基文档中明确说明的信息。
2. **每条声明必须引用**: 每个事实性声明后面必须跟上 OKF 概念链接 `[标题](/concept-id.md)`。
3. **说"不知道"**（仅在所有文档确实没有信息时）:
先逐行读完所有文档。如果仍然没有足够信息回答，说："维基文档中没有足够信息来回答此问题。"
然后列出文档中已有的相关信息（即使不完整）。
4. **禁止编造**: 不要编造事实、数字、日期、名称或关系。不确定的用 [不确定] 标注。
5. **写前验证**: 每写一句之前，先问自己："哪篇维基文档支持这句话？"如果找不到，就不要写。
6. **使用精确数值**: 当文档包含具体数字/日期/名称时，逐字使用原文。
7. **区分来源**: 如果多篇文档对同一主题有不同说法，明确标注分歧。
8. **简洁但完整**: 直接回答问题。不要添加与查询无直接关系的背景内容。
9. **保留图片证据**: 检索文档包含与答案直接相关的原图时，在答案中保留其 Markdown 图片引用，不得只改写成文字描述。"""
        user_prompt = f"""## 查询
{query}

## 维基文档（你唯一的知识来源）
{contexts_text}

## 任务
只使用上面维基文档中的信息回答问题。每个事实都要标明 OKF 概念链接。
如果文档中缺少答案，明确说明——不要猜测或使用外部知识。保留与答案直接相关的原图引用。"""
    else:
        system_prompt = f"""You are a precise wiki query engine.
Your ONLY knowledge source is the wiki documents provided below — you have NO other knowledge.

{format_prompts.get(fmt, format_prompts["markdown"])}

## ⚠️ CRITICAL RULES — Violating Any Will Produce Incorrect Results
0. **★ EXTRACT BEFORE YOU DECIDE (MOST IMPORTANT!)**:
Before saying "I don't know", read EVERY line of EVERY provided document carefully.
Documents use `**key**: value` format in Key Details sections — these ARE the answers.
Extract ALL numbers, dates, names, thresholds first. Missing a value that's clearly
present in a document is the worst possible error!
1. **NO EXTERNAL KNOWLEDGE**:
You MUST NOT use any information that is not explicitly stated in the provided wiki documents.
2. **CITE EVERY CLAIM**:
Every factual claim MUST be followed by its source [[page-id]] inline.
Example: "Transformers use self-attention [Transformer paper](/papers/transformer.md)."
3. **SAY "I DON'T KNOW"** (only after exhausting all documents):
Read every document line by line first. If after thorough reading you still lack the
answer, state: "The wiki does not contain sufficient information to answer this question."
Then list what partial information IS available.
4. **NO FABRICATION**:
Do NOT invent facts, numbers, dates, names, or relationships. If unsure, use [uncertain].
5. **VERIFY BEFORE WRITING**:
Before writing each sentence, ask yourself: "Which wiki document supports this?"
If you can't point to one, don't write it.
6. **USE PRECISE VALUES**:
When the documents contain specific numbers/dates/names, use them verbatim.
7. **DISTINGUISH SOURCES**:
If multiple documents say different things about the same topic, note the disagreement.
8. **CONCISE BUT COMPLETE**:
Answer the query directly. Don't add background context unless directly relevant.
9. **PRESERVE IMAGE EVIDENCE**:
When a retrieved document includes a relevant source image, keep its Markdown image
reference in the answer instead of replacing it with a text-only description."""

        user_prompt = f"""## Query
{query}

## Wiki Documents (YOUR ONLY KNOWLEDGE SOURCE)
{contexts_text}

## Task
Answer the query using ONLY information from the wiki documents above. For each fact,
cite the source as an OKF concept link inline immediately after the claim. If the documents lack the
answer, say so explicitly — do NOT guess or use outside knowledge."""

    return call_llm(system_prompt, user_prompt)


def synthesize_answer_agent(query: str, pages: list[dict], fmt: str = "markdown") -> str:
    """Return an Agent synthesis task using retrieved wiki pages only.

    This is the default skill path: search is local, and the current Agent
    performs the final synthesis without using the configured LLM API.
    """
    if not pages:
        return "No relevant wiki pages found. Try adding more sources with `wiki compile`."

    contexts = []
    for i, page in enumerate(pages[:8]):
        if set(str(page.get("stream", "")).split(",")) & {"table", "table_vector", "ledger"}:
            table_name = page.get("display_name", page.get("table_name", "unknown"))
            row_id = page.get("row_id", "")
            row_data = page.get("row_data", {})
            if row_data:
                row_str = "\n".join(
                    f"- {k}: {v}" for k, v in row_data.items()
                    if not k.startswith("_")
                )
                contexts.append(
                    f"## DOC {i + 1}: [TABLE] {table_name} (row {row_id})\n{row_str}"
                )
            continue

        ctx = _format_page_context(page, i + 1, query)
        if ctx:
            contexts.append(ctx)

    if not contexts:
        return "Wiki pages found but content could not be read."
    contexts_text = "\n".join(contexts)

    source_links = ", ".join(
        f"[{page.get('id', 'unknown')}](/"
        f"{page.get('id', 'unknown')}.md)" for page in pages[:8]
    )
    output_hint = {
        "markdown": "Answer in concise Markdown with inline OKF concept links.",
        "table": "Answer with a Markdown comparison table and cite sources.",
        "timeline": "Answer with a Markdown timeline and cite sources.",
        "slides": "Answer as a Marp slide outline and cite sources.",
        "json": "Answer as valid JSON with answer, sources, related, and confidence.",
    }.get(fmt, "Answer in concise Markdown with inline OKF concept links.")

    return f"""# Agent Query Synthesis Task

This task was generated in Agent mode. Do not call the configured LLM API.

## Query

{query}

## Output Requirement

{output_hint}

Use ONLY the wiki documents below. Cite every factual claim with its OKF concept link.
If the documents do not contain enough information, say so and summarize the
partial information that is available. Do not use outside knowledge.
Keep any directly relevant Markdown source images in the synthesized answer.

Available source IDs: {source_links}

## Retrieved Wiki Documents

{contexts_text}
"""


def file_answer_back(query: str, answer: str, sources: list[dict]) -> str:
    concepts_dir = PAGES_DIR / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    slug = query.lower().replace(" ", "-").replace("?", "")[:50]
    slug = "".join(c for c in slug if c.isalnum() or c == "-")

    page_path = concepts_dir / f"{slug}.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    source_links = [
        f"[{item.get('id', Path(item.get('path', '')).stem)}]"
        f"(/{Path(item.get('path', '')).relative_to(PAGES_DIR).as_posix()})"
        for item in sources
        if item.get("path") and Path(item["path"]).is_relative_to(PAGES_DIR)
    ]
    frontmatter = f"""---
type: Query Answer
title: "{query[:50]}"
description: "Answer generated from compiled OKF concepts."
tags: [query-generated]
timestamp: {now}T00:00:00Z
provenance: query
---

"""

    content = frontmatter + f"# {query[:50]}\n\n"
    content += f"**Generated from query**: {query}\n\n"
    content += (
        answer.replace("**Answer**:", "## Answer\n\n")
        .replace("**Sources**:", "\n## Sources\n\n")
        .replace("**Related**:", "\n## Related\n\n")
    )
    if source_links:
        content += "\n# Citations\n\n" + "\n".join(
            f"[{index}] {link}" for index, link in enumerate(source_links, 1)
        )

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

    entities_file.write_text(
        json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return str(page_path)


def verify_answer_evidence(answer: str, pages: list[dict]) -> dict:
    """Check citation coverage, source identity, and exact values against evidence."""
    available = {str(page.get("id", "")) for page in pages}
    evidence = {
        str(page.get("id", "")): read_page_content(str(page.get("path", "")))
        or str(page.get("text", ""))
        for page in pages
    }
    cited = set(re.findall(r"\]\(/([^)#]+)\.md(?:#[^)]+)?\)", answer))
    cited.update(re.findall(r"\[\[([^\]|]+)", answer))
    unsupported = sorted(identifier for identifier in cited if identifier not in available)
    claim_lines = [
        line.strip()
        for line in answer.splitlines()
        if line.strip()
        and not line.lstrip().startswith(("#", "|", "```"))
        and (re.search(r"\d", line) or len(line.strip()) >= 40)
    ]
    cited_claims = sum(
        1
        for line in claim_lines
        if re.search(r"\]\(/[^)]+\.md", line) or "[[" in line
    )
    coverage = cited_claims / len(claim_lines) if claim_lines else 1.0
    unverified_values = []
    for line in claim_lines:
        line_citations = set(re.findall(r"\]\(/([^)#]+)\.md(?:#[^)]+)?\)", line))
        line_citations.update(re.findall(r"\[\[([^\]|]+)", line))
        if not line_citations:
            continue
        source_text = "\n".join(evidence.get(identifier, "") for identifier in line_citations)
        for value in re.findall(r"(?<!\w)\d[\d,.%:/-]*", line):
            if value not in source_text:
                unverified_values.append({"value": value, "claim": line[:240]})
    return {
        "status": (
            "pass"
            if not unsupported and not unverified_values and coverage >= 0.8
            else "warning"
        ),
        "citation_coverage": round(coverage, 4),
        "cited_concepts": sorted(cited),
        "unsupported_citations": unsupported,
        "unverified_values": unverified_values,
        "claims_checked": len(claim_lines),
    }


def _read_snippet(path: str, query: str, max_len: int = 120) -> str:
    """Extract a relevant snippet from a page near query terms."""
    try:
        content = Path(path).read_text(encoding="utf-8")
        content = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
        query_terms = [t for t in query.split() if len(t) >= 2]
        for term in query_terms:
            idx = content.lower().find(term.lower())
            if idx >= 0:
                start = max(0, idx - 40)
                end = min(len(content), idx + len(term) + max_len)
                snippet = content[start:end].replace("\n", " ").strip()
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(content) else ""
                return prefix + snippet + suffix
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                return line[:max_len] + "..."
    except Exception:
        _log_exc("_read_snippet failed")
        pass
    return ""

# ── Graph intent detection ─────────────────────────────────────────────

# Patterns for detecting graph-traversal intents in natural language queries
_PATH_INTENT_PATTERNS_ZH = [
    (r"(.+?)\s*(?:和|与|跟|同)\s*(.+?)\s*(?:之间|之间|间)\s*(?:的)?\s*(?:关系|依赖|关联|联系|路径|连接)",
     "path"),
    (r"(.+?)\s*(?:如何|怎么)\s*(?:依赖|关联|影响|连接)(?:于|到)\s*(.+)", "path"),
    (r"从\s*(.+?)\s*到\s*(.+?)\s*(?:的)?\s*(?:路径|关系|依赖链)", "path"),
]
_PATH_INTENT_PATTERNS_EN = [
    (r"(?:how|what).*(?:relationship|relation|connection|path|link).*between\s+(.+?)\s+and\s+(.+)", "path"),
    (r"(.+?)\s+(?:->|→|depends on|relates to|connects to)\s+(.+)", "path"),
    (r"path\s+(?:from|between)\s+(.+?)\s+(?:to|and)\s+(.+)", "path"),
]
_IMPACT_INTENT_PATTERNS_ZH = [
    (r"(.+?)\s*(?:影响|依赖|取决于)(?:什么|哪些|谁)", "impact"),
    (r"(?:什么|哪些|谁)\s*(?:依赖|取决于|受影响于)\s*(.+)", "impact"),
]
_IMPACT_INTENT_PATTERNS_EN = [
    (r"what\s+(?:depends on|relies on|uses|is affected by)\s+(.+)", "impact"),
    (r"(.+?)\s+(?:impact|influence|affect)(?:s)?\s+(?:analysis|what|which)", "impact"),
    (r"what\s+(?:would|will)\s+(?:happen|break)\s+(?:if|when)\s+(.+?)\s+(?:changes|breaks|fails)", "impact"),
]


def _detect_graph_intent(query: str) -> dict | None:
    """Detect if a query is asking for graph traversal (path or impact analysis).

    Returns a dict with keys:
        intent: "path" | "impact"
        entities: list of entity names/ids to analyze
    Or None if no graph intent detected.
    """
    import re as _re

    # ── Path intent detection ──
    for pattern, intent in _PATH_INTENT_PATTERNS_ZH + _PATH_INTENT_PATTERNS_EN:
        m = _re.search(pattern, query, _re.IGNORECASE)
        if m:
            entities = [g.strip() for g in m.groups() if g.strip()]
            if len(entities) >= 2:
                return {"intent": "path", "entities": entities[:2]}
            elif len(entities) == 1:
                return {"intent": "path", "entities": entities}

    # ── Impact intent detection ──
    for pattern, intent in _IMPACT_INTENT_PATTERNS_ZH + _IMPACT_INTENT_PATTERNS_EN:
        m = _re.search(pattern, query, _re.IGNORECASE)
        if m:
            entities = [g.strip() for g in m.groups() if g.strip()]
            if entities:
                return {"intent": "impact", "entities": entities[:1]}

    return None


def _resolve_entity_id(name: str, pages: list[dict]) -> str | None:
    """Resolve a natural-language entity name to a wiki entity ID.

    Tries: exact ID match, name match, partial match in retrieved pages.
    """
    if not name:
        return None
    slug = name.lower().strip().replace(" ", "-").replace("_", "-")

    # Direct ID match in search results
    for p in pages:
        pid = p.get("id", "").lower()
        pname = p.get("name", "").lower()
        if slug == pid or slug == pname:
            return p["id"]

    # Partial match: the entity name appears in the page ID
    for p in pages:
        pid = p.get("id", "").lower()
        if slug in pid or pid in slug:
            return p["id"]

    # Fuzzy: try as slug of search result name
    for p in pages:
        pname_slug = p.get("name", "").lower().replace(" ", "-")
        if slug in pname_slug or pname_slug in slug:
            return p["id"]

    # Fallback: use the slug directly (may match graph entities.json keys)
    return slug


def _format_path_result(path: list[dict] | None, source: str, target: str) -> str:
    """Format a graph path result as readable markdown."""
    if not path:
        return f"❌ 未找到从 **{source}** 到 **{target}** 的路径。"

    lines = [
        f"🔗 从 **{source}** 到 **{target}** 的路径 ({len(path)} 步):",
        "",
    ]
    for i, edge in enumerate(path):
        etype = edge.get("type", "relates_to")
        src = edge.get("source", "?")
        tgt = edge.get("target", "?")
        lines.append(f"  {i+1}. **[[{src}]]** —{etype}→ **[[{tgt}]]**")

    lines.append("")
    lines.append(f"💡 共 {len(path)} 步，涉及 {_count_unique_nodes(path)} 个实体。")
    return "\n".join(lines)


def _format_impact_result(impact: dict, entity: str) -> str:
    """Format an impact analysis result as readable markdown."""
    affected = impact.get("affected_entities", [])
    paths = impact.get("paths", [])

    if not affected:
        return f"✅ **{entity}** 没有下游依赖方——可以安全修改。"

    lines = [
        f"⚠️ **{entity}** 影响 {len(affected)} 个下游实体:",
        "",
    ]
    for i, ent in enumerate(affected[:15]):
        eid = ent.get("id", "?")
        ename = ent.get("name", eid)
        etype = ent.get("type", "?")
        lines.append(f"  {i+1}. **[[{eid}]]** ({etype}) — {ename}")

    lines.append("")
    lines.append("### 影响路径")
    for i, path_nodes in enumerate(paths[:5]):
        lines.append(f"  {i+1}. {' → '.join(f'**[[{n}]]**' for n in path_nodes)}")

    if len(affected) > 15:
        lines.append(f"  ... 及其他 {len(affected) - 15} 个实体")
    lines.append("")
    lines.append(f"💡 修改 **{entity}** 前，评估对以上实体的影响。")
    return "\n".join(lines)


def _count_unique_nodes(path: list[dict]) -> int:
    """Count unique nodes in a path."""
    nodes: set[str] = set()
    for edge in path:
        nodes.add(edge.get("source", ""))
        nodes.add(edge.get("target", ""))
    return len(nodes)


def _format_debug_table(trace: dict) -> str:
    """Format search debug trace as a readable Markdown table."""
    lines = [
        "## 🔍 Search Debug",
        "",
        f"**Query:** `{trace.get('query', '?')}`",
        f"**Plan:** {trace.get('plan', 'none')}",
        f"**Streams:** {', '.join(trace.get('enabled_streams', []))}",
        f"**Query variants:** {trace.get('query_variants', [])}",
        "",
    ]

    # ── Per-stream result counts ──
    lines.append("### Stream Summary")
    lines.append("")
    lines.append("| Stream | Results | Error |")
    lines.append("|--------|---------|-------|")
    for stream_name in ("metadata", "bm25", "graph", "ledger"):
        stream_data = trace.get("streams", {}).get(stream_name)
        error = trace.get("streams", {}).get(f"{stream_name}_error", "")
        count = len(stream_data) if isinstance(stream_data, list) else (1 if stream_data else 0)
        error_str = f"⚠️ {error[:40]}" if error else "✅"
        lines.append(f"| {stream_name} | {count} | {error_str} |")
    lines.append("")

    # ── Query entities ──
    query_entities = trace.get("query_entities", [])
    if query_entities:
        lines.append(f"**Detected entities:** {', '.join(f'`{e}`' for e in query_entities[:10])}")
        lines.append("")

    # ── Final ranking table ──
    reranked = trace.get("reranked", [])
    if reranked:
        lines.append("### Final Ranking")
        lines.append("")
        # Determine which score columns to show
        sample = reranked[0] if reranked else {}
        stream_scores = sample.get("stream_scores", {})
        has_bm25 = "bm25" in stream_scores
        has_metadata = "metadata" in stream_scores
        has_graph = "graph" in stream_scores
        has_ledger = "ledger" in stream_scores

        # Build header
        header_cols = ["#", "Page ID", "Type"]
        sep_cols = ["---", "------", "----"]
        if has_bm25:
            header_cols.append("BM25")
            sep_cols.append("----")
        if has_metadata:
            header_cols.append("Meta")
            sep_cols.append("----")
        if has_graph:
            header_cols.append("Graph")
            sep_cols.append("-----")
        if has_ledger:
            header_cols.append("Ledger")
            sep_cols.append("------")
        header_cols.append("Final")
        sep_cols.append("-----")

        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(sep_cols) + "|")

        for i, r in enumerate(reranked[:20]):
            pid = r.get("id", "?")[:25]
            ptype = r.get("type", "?")[:8]
            final_score = r.get("score", 0)
            ss = r.get("stream_scores", {})

            cols = [str(i + 1), pid, ptype]
            if has_bm25:
                bm25_s = ss.get("bm25", 0)
                cols.append(f"{bm25_s:.3f}" if isinstance(bm25_s, (int, float)) else str(bm25_s)[:5])
            if has_metadata:
                meta_s = ss.get("metadata", 0)
                cols.append(f"{meta_s:.3f}" if isinstance(meta_s, (int, float)) else str(meta_s)[:5])
            if has_graph:
                graph_s = ss.get("graph", 0)
                cols.append(f"{graph_s:.3f}" if isinstance(graph_s, (int, float)) else str(graph_s)[:5])
            if has_ledger:
                ledger_s = ss.get("ledger", 0)
                cols.append(f"{ledger_s:.3f}" if isinstance(ledger_s, (int, float)) else str(ledger_s)[:5])
            cols.append(f"{final_score:.3f}" if isinstance(final_score, (int, float)) else str(final_score)[:5])

            lines.append("| " + " | ".join(cols) + " |")

        if len(reranked) > 20:
            lines.append("| ... | ... | ... |")
            lines.append("")
            lines.append(f"*{len(reranked) - 20} more results not shown*")
        lines.append("")

    # ── Stream contribution legend ──
    lines.append("### Score Components")
    lines.append("")
    lines.append("- **BM25**: Keyword match score (TF-IDF with BM25 saturation)")
    lines.append("- **Meta**: Frontmatter metadata match (aliases, keywords, questions)")
    lines.append("- **Graph**: Knowledge graph entity linking + 1-hop traversal")
    lines.append("- **Ledger**: Structured data cross-reference (台账)")
    lines.append("- **Final**: Weighted fusion of all enabled streams + entity-type boost + graph boost")
    lines.append("")

    return "\n".join(lines)


def query_wiki(
    query: str,
    file_back: bool = False,
    fmt: str = "markdown",
    synthesis: bool = True,
    debug_search: bool = False,
    mode: str | None = None,
) -> dict:
    query_cfg = get_query_config()
    synthesis_mode = mode or query_cfg.get("synthesis_mode", "agent")

    if not synthesis:
        pass
    elif "llm_synthesis" in query_cfg:
        synthesis = query_cfg.get("llm_synthesis", True)

    max_results = max(1, int(query_cfg.get("max_results", 5) or 5))
    if debug_search:
        pages, trace = search_wiki(query, limit=max_results, debug=True)
    else:
        pages = search_wiki(query, limit=max_results)
        trace = {}
    pages = _attach_page_images(pages)
    retrieved_images = _collect_retrieved_images(pages)

    # ── Graph intent routing ──
    graph_intent = _detect_graph_intent(query)
    graph_section = ""
    if graph_intent:
        try:
            from graph import find_path, impact_analysis

            if graph_intent["intent"] == "path" and len(graph_intent["entities"]) >= 2:
                src = _resolve_entity_id(graph_intent["entities"][0], pages)
                tgt = _resolve_entity_id(graph_intent["entities"][1], pages)
                if src and tgt:
                    path = find_path(src, tgt)
                    graph_section = _format_path_result(path, src, tgt)
                    graph_section += "\n\n---\n\n"
            elif graph_intent["intent"] == "impact":
                entity = _resolve_entity_id(graph_intent["entities"][0], pages)
                if entity:
                    impact = impact_analysis(entity)
                    graph_section = _format_impact_result(impact, entity)
                    graph_section += "\n\n---\n\n"
        except ImportError:
            pass  # graph module not available — skip
        except Exception:
            _log_exc("graph intent query failed")
            pass  # graph query failed — continue with normal search

    if pages and not synthesis:
        # Fast path: return raw search results without LLM call
        lines = [f"## 搜索结果: {query}\n"]
        for i, p in enumerate(pages[:10], 1):
            snippet = _read_snippet(p["path"], query)
            lines.append(
                f"{i}. **[{p['id']}](/"
                f"{p['id']}.md)** ({p['type']}) — score: {p['score']:.2f}"
            )
            if snippet:
                lines.append(f"   > {snippet}")
            for image in p.get("images", []):
                lines.append(f"   {image['markdown']}")
            lines.append("")
        return {
            "query": query,
            "format": "fast",
            "answer": "\n".join(lines),
            "pages_searched": len(pages),
            "sources": [p.get("id", "unknown") for p in pages],
            "source_details": [
                {
                    "id": p.get("id", "unknown"),
                    "name": p.get("name", p.get("id", "unknown")),
                    "path": p.get("path", ""),
                    "page_type": p.get("type", "unknown"),
                    "relevance": p.get("score", 0),
                    "images": p.get("images", []),
                }
                for p in pages
            ],
            "images": retrieved_images,
            "debug_search": trace if debug_search else {},
        }

    if pages:
        if synthesis_mode == "llm":
            answer = graph_section + synthesize_answer(query, pages, fmt=fmt)
        else:
            answer = graph_section + synthesize_answer_agent(query, pages, fmt=fmt)
    else:
        answer = graph_section or "No relevant wiki pages found."

    if retrieved_images and synthesis_mode == "llm" and fmt != "json":
        gallery = "\n\n## 引用原图\n\n" + "\n\n".join(
            image["markdown"] for image in retrieved_images
        )
        answer = answer.rstrip() + gallery

    result = {
        "query": query,
        "format": fmt,
        "mode": synthesis_mode,
        "answer": answer,
        "pages_searched": len(pages),
        "sources": [p.get("id", "unknown") for p in pages],
        "source_details": [
            {
                "id": p.get("id", "unknown"),
                "name": p.get("name", p.get("id", "unknown")),
                "path": p.get("path", ""),
                "page_type": p.get("type", "unknown"),
                "relevance": p.get("score", 0),
                "images": p.get("images", []),
            }
            for p in pages
        ],
        "images": retrieved_images,
    }
    if query_cfg.get("verify_answers", True):
        result["verification"] = (
            verify_answer_evidence(answer, pages)
            if synthesis_mode == "llm"
            else {"status": "pending_agent_synthesis"}
        )
    if debug_search:
        result["debug_search"] = trace

    if file_back and pages and synthesis_mode == "llm":
        filed_path = file_answer_back(query, answer, pages)
        result["filed"] = filed_path
    elif file_back and synthesis_mode != "llm":
        result["file_back_skipped"] = "agent_mode"

    return result


def main():
    parser = argparse.ArgumentParser(description="Query wiki and answer questions")
    parser.add_argument("query", help="Question to answer")
    parser.add_argument("--file-back", action="store_true",
                        help="File answer back to wiki")
    parser.add_argument(
        "--format",
        choices=["markdown", "table", "timeline", "slides", "json", "graph"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--mode",
        choices=["agent", "llm"],
        default=None,
        help="Synthesis mode: agent (default) or llm (configured API)",
    )
    parser.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Skip synthesis — return raw search results (fast)",
    )
    parser.add_argument(
        "--debug-search",
        action="store_true",
        help="Print search trace as JSON after the answer",
    )
    args = parser.parse_args()

    if args.format == "graph":
        import subprocess
        code, out = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "graph.py"), "show"],
            capture_output=True, text=True
        )
        print(out if code == 0 else f"Graph error: {out}")
        return

    result = query_wiki(
        args.query, file_back=args.file_back, fmt=args.format,
        synthesis=not args.no_synthesis, debug_search=args.debug_search,
        mode=args.mode,
    )
    print(result["answer"])
    if args.debug_search:
        print("\n--- SEARCH DEBUG ---")
        print(_format_debug_table(result.get("debug_search", {})))

    if args.file_back and result.get("filed"):
        print(f"\n---\nFiled to: {result['filed']}", file=sys.stderr)


if __name__ == "__main__":
    main()
