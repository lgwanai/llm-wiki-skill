#!/usr/bin/env python3
"""search.py — Wiki-native Hybrid Search for llm-wiki.

Karpathy/Rohit design: search compiled wiki pages (BM25 + metadata + graph),
not raw source chunks. No embeddings, no chunks, no rerankers — the wiki pages
are already structured knowledge units curated by the LLM during compile.

Streams:
- metadata: Search page frontmatter (aliases, keywords, questions, summary)
- bm25: Full-page BM25 keyword search with jieba Chinese segmentation
- graph: Entity-aware graph search with symbolic name matching + traversal
- table: BM25 search over DuckDB ledger tables
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import yaml
from config import get_wiki_dir

try:
    import jieba
except ImportError:
    jieba = None

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
ENTITIES_FILE = os.path.join(GRAPH_DIR, "entities.json")
EDGES_FILE = os.path.join(GRAPH_DIR, "edges.json")


def _load_jieba_entities():
    """Add Chinese entity names to jieba's dictionary for better tokenization."""
    if jieba is None:
        return
    try:
        entities_path = Path(ENTITIES_FILE)
        if not entities_path.exists():
            return
        entities = json.loads(entities_path.read_text(encoding="utf-8"))
        for eid, data in entities.items():
            if not isinstance(data, dict):
                continue
            name = data.get("name", "")
            if name and any('一' <= c <= '鿿' for c in name):
                jieba.add_word(name, freq=100)
                if any('一' <= c <= '鿿' for c in eid):
                    jieba.add_word(eid, freq=80)
    except Exception:
        pass  # Best-effort


# ── Module-level caches (invalidated when pages change) ──
_cache_marker: tuple[int, float] | None = None
_entities_cache: dict | None = None
_edges_cache: dict | list | None = None
_bm25_index: dict | None = None
_BM25_CACHE_FILE = WIKI_DIR / "graph" / ".bm25_index.json"
_METADATA_CACHE_FILE = WIKI_DIR / "graph" / ".metadata_index.json"


def _pages_changed() -> bool:
    """Check if any wiki page has been modified since last cache build."""
    global _cache_marker
    count = 0
    latest_mtime = 0.0
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        scan_dir = PAGES_DIR / subdir
        if not scan_dir.is_dir():
            continue
        for f in scan_dir.iterdir():
            if f.suffix == '.md':
                count += 1
                mtime = f.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
    marker = (count, latest_mtime)
    if _cache_marker != marker:
        _cache_marker = marker
        return True
    return False


def _save_bm25_cache(idx: dict) -> None:
    """Persist BM25 index to disk."""
    try:
        serializable = {}
        for path, data in idx.items():
            serializable[path] = {
                "tokens": data["tokens"],
                "freqs": dict(data["freqs"]),
                "length": data["length"],
            }
        _BM25_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BM25_CACHE_FILE.write_text(
            json.dumps(serializable, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _load_bm25_cache() -> dict | None:
    """Load BM25 index from disk if pages haven't changed."""
    if _pages_changed() or not _BM25_CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_BM25_CACHE_FILE.read_text(encoding="utf-8"))
        result = {}
        for path, d in data.items():
            result[path] = {
                "tokens": d["tokens"],
                "freqs": Counter(d["freqs"]),
                "length": d["length"],
            }
        return result
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def _load_entities() -> dict:
    global _entities_cache
    if _entities_cache is not None and not _pages_changed():
        return _entities_cache
    _entities_cache = _load_json(ENTITIES_FILE) if os.path.exists(ENTITIES_FILE) else {}
    if not isinstance(_entities_cache, dict):
        _entities_cache = {}
    _load_jieba_entities()
    return _entities_cache


def _load_edges() -> list:
    global _edges_cache
    if _edges_cache is not None and not _pages_changed():
        return _edges_cache
    data = _load_json(EDGES_FILE)
    _edges_cache = data.get('edges', []) if isinstance(data, dict) else []
    return _edges_cache


def _load_json(path: str) -> dict | list:
    if not os.path.exists(path):
        return {} if 'entities' in path else {'edges': []}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {} if 'entities' in path else {'edges': []}


def _load_json_safe(path: str, default: dict | list) -> dict | list:
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _read_page_content(filepath: str) -> str:
    """Read a markdown page, stripping YAML frontmatter."""
    try:
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return ''
    content = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
    return content


def _read_page_parts(filepath: str) -> tuple[dict, str]:
    """Read a page as (frontmatter dict, body text)."""
    try:
        raw = Path(filepath).read_text(encoding="utf-8")
    except OSError:
        return {}, ""
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.split("\n")
    end = 0
    for i, line in enumerate(lines):
        if i > 0 and line.strip() == "---":
            end = i
            break
    if end <= 0:
        return {}, raw
    frontmatter_text = "\n".join(lines[1:end])
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(frontmatter, dict):
            frontmatter = {}
    except Exception:
        frontmatter = {}
    return frontmatter, "\n".join(lines[end + 1:])


def _page_path_for_id(page_id: str, pages_dir: str | Path = PAGES_DIR) -> str:
    """Find a wiki page path by page id across known page directories."""
    base = Path(pages_dir)
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        path = base / subdir / f"{page_id}.md"
        if path.exists():
            return str(path)
    return ""


def _known_page_paths(pages_dir: str | Path = PAGES_DIR) -> list[Path]:
    """Return all known wiki page paths."""
    base = Path(pages_dir)
    paths: list[Path] = []
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        scan_dir = base / subdir
        if scan_dir.is_dir():
            paths.extend(sorted(scan_dir.glob("*.md")))
    return paths


def _tokenize(text: str) -> list[str]:
    """Split text into tokens: jieba for Chinese, regex for English."""
    tokens: list[str] = []
    cjk_chars = sum(1 for c in text if '一' <= c <= '鿿')
    if cjk_chars > 0 and jieba is not None:
        tokens.extend(w for w in jieba.cut(text) if len(w.strip()) > 1)
    else:
        tokens.extend(re.findall(r'[a-z0-9]+', text.lower()))
    # Extract English tokens if CJK content is mixed with English
    if cjk_chars > 0 and len(text) > cjk_chars * 1.5:
        tokens.extend(re.findall(r'[a-z0-9]+', text.lower()))
    return tokens


def _stem(word: str) -> str:
    """Simple suffix-stripping stemmer. English only — CJK passed through."""
    if any('一' <= c <= '鿿' for c in word):
        return word
    if word.endswith('ing') and len(word) > 5:
        word = word[:-3]
    elif word.endswith('ed') and len(word) > 4:
        word = word[:-2]
    elif word.endswith('s') and not word.endswith('ss') and len(word) > 3:
        word = word[:-1]
    elif word.endswith('ion') and len(word) > 5:
        word = word[:-3]
    return word


# ═══════════════════════════════════════════════════════════════════════════
# Stream 1: BM25 keyword search over full wiki pages
# ═══════════════════════════════════════════════════════════════════════════

def bm25_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """BM25 keyword search with stemming over wiki pages. Uses index cache."""
    global _bm25_index
    k1, b = 1.5, 0.75
    query_terms = [_stem(t) for t in _tokenize(query)]
    if not query_terms:
        return []

    if _bm25_index is None:
        _bm25_index = _load_bm25_cache()
    if _bm25_index is None:
        _bm25_index = {}
        for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                       'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
            scan_dir = os.path.join(pages_dir, subdir)
            if not os.path.isdir(scan_dir):
                continue
            for filename in os.listdir(scan_dir):
                if not filename.endswith('.md'):
                    continue
                filepath = os.path.join(scan_dir, filename)
                content = _read_page_content(filepath)
                tokens = [_stem(t) for t in _tokenize(content)]
                if tokens:
                    _bm25_index[filepath] = {
                        "tokens": tokens,
                        "freqs": Counter(tokens),
                        "length": len(tokens),
                    }
        _save_bm25_cache(_bm25_index)

    if not _bm25_index:
        return []

    num_docs = len(_bm25_index)
    total_length = sum(d["length"] for d in _bm25_index.values())
    avg_dl = total_length / num_docs if num_docs else 1

    doc_freq: Counter = Counter()
    for idx in _bm25_index.values():
        doc_freq.update(set(idx["freqs"].keys()))

    scores: list[tuple[str, float]] = []
    for path, idx in _bm25_index.items():
        score = 0.0
        dl = idx["length"]
        for term in query_terms:
            f = idx["freqs"].get(term, 0)
            if f == 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg_dl))
        if score > 0:
            scores.append((path, score))

    scores.sort(key=lambda x: -x[1])
    results = []
    for path, score in scores[:limit]:
        filename = os.path.basename(path)
        results.append({
            'file': os.path.splitext(filename)[0],
            'path': path,
            'score': round(score, 3),
            'stream': 'bm25',
        })
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Stream 2: Metadata search (frontmatter aliases, keywords, questions, summary)
# ═══════════════════════════════════════════════════════════════════════════

def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(value)]


def build_metadata_index(pages_dir: str | Path = PAGES_DIR) -> list[dict]:
    """Build a page metadata index from frontmatter search fields."""
    items: list[dict] = []
    for path in _known_page_paths(pages_dir):
        fm, body = _read_page_parts(str(path))
        title_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
        title = title_match.group(1).strip() if title_match else fm.get("name", path.stem)
        fields = {
            "id": fm.get("id", path.stem),
            "name": fm.get("name", title),
            "type": fm.get("type", ""),
            "summary": fm.get("summary", ""),
            "aliases": _as_list(fm.get("aliases")),
            "keywords": _as_list(fm.get("keywords")),
            "questions": _as_list(fm.get("questions")),
            "facts": fm.get("facts", {}),
        }
        # Build searchable text including facts
        facts_text = ""
        facts_dict = fields["facts"]
        if isinstance(facts_dict, dict):
            facts_text = " ".join(
                f"{k} {v}" for k, v in facts_dict.items()
            )
        searchable = " ".join([
            str(fields["id"]),
            str(fields["name"]),
            str(fields["type"]),
            str(fields["summary"]),
            " ".join(fields["aliases"]),
            " ".join(fields["keywords"]),
            " ".join(fields["questions"]),
            facts_text,
            title,
        ])
        items.append({
            "page_id": path.stem,
            "path": str(path),
            "title": title,
            "searchable": searchable,
            **fields,
        })
    return items


def _load_metadata_index(pages_dir: str | Path = PAGES_DIR) -> list[dict]:
    """Load or rebuild the disk-backed metadata index."""
    if _pages_changed() or not _METADATA_CACHE_FILE.exists():
        items = build_metadata_index(pages_dir)
        try:
            _METADATA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _METADATA_CACHE_FILE.write_text(
                json.dumps(items, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass
        return items
    try:
        data = json.loads(_METADATA_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return build_metadata_index(pages_dir)


def metadata_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """Search page frontmatter: aliases, keywords, summary, questions."""
    items = _load_metadata_index(pages_dir)
    query_terms = [_stem(t) for t in _tokenize(query)]
    if not items or not query_terms:
        return []

    scored: list[tuple[dict, float]] = []
    for item in items:
        searchable = item.get("searchable", "")
        tokens = [_stem(t) for t in _tokenize(searchable)]
        if not tokens:
            continue
        freqs = Counter(tokens)
        exact_bonus = 0.0
        query_lower = query.lower()
        for field in ("id", "name", "summary"):
            if query_lower and query_lower in str(item.get(field, "")).lower():
                exact_bonus += 2.0
        if any(query_lower == alias.lower() for alias in item.get("aliases", [])):
            exact_bonus += 4.0
        score = exact_bonus
        for term in query_terms:
            score += freqs.get(term, 0)
        if score > 0:
            scored.append((item, score))

    scored.sort(key=lambda x: -x[1])
    return [
        {
            "file": item["page_id"],
            "path": item["path"],
            "score": round(score, 3),
            "stream": "metadata",
            "text": item.get("summary") or item.get("searchable", "")[:800],
            "aliases": item.get("aliases", []),
            "keywords": item.get("keywords", []),
        }
        for item, score in scored[:limit]
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Stream 3: Entity-aware graph search
# ═══════════════════════════════════════════════════════════════════════════

_RELATION_QUERY_TERMS = {
    "影响", "依赖", "关系", "路径", "关联", "对比", "比较", "区别",
    "impact", "depends", "dependency", "relationship", "related",
    "compare", "difference", "versus", "vs",
}


def _normalize_match_text(text: str) -> str:
    """Normalize names/aliases for entity linking."""
    return re.sub(r"[\s_\-./:]+", "", text.lower())


def _entity_match_score(query: str, entity_id: str, entity: dict) -> float:
    """Score how strongly a natural-language query mentions an entity.

    Symbolic matching — no embeddings. Anchors queries to compiled wiki
    entities and aliases before graph traversal.
    """
    query_lower = query.lower()
    query_norm = _normalize_match_text(query)
    query_terms = {_stem(t) for t in _tokenize(query)}
    if not query_norm and not query_terms:
        return 0.0

    names = [
        entity_id,
        str(entity.get("id", "")),
        str(entity.get("name", "")),
    ]
    names.extend(_as_list(entity.get("aliases")))
    names.extend(_as_list(entity.get("keywords")))

    score = 0.0
    for raw_name in names:
        name = str(raw_name).strip()
        if not name:
            continue
        name_lower = name.lower()
        name_norm = _normalize_match_text(name)
        if not name_norm:
            continue

        # Exact match
        if query_norm == name_norm or query_lower == name_lower:
            score = max(score, 1.0)
            continue
        # Substring match (entity name contained in query)
        if len(name_norm) >= 3 and name_norm in query_norm:
            score = max(score, 0.9)
            continue
        # Substring match (query contained in entity name)
        if len(query_norm) >= 3 and query_norm in name_norm:
            score = max(score, 0.72)

        # Term overlap scoring
        name_terms = {_stem(t) for t in _tokenize(name)}
        if name_terms:
            overlap = query_terms & name_terms
            if overlap:
                coverage = len(overlap) / len(name_terms)
                score = max(score, 0.45 + 0.35 * coverage)

    if score <= 0:
        return 0.0
    confidence = float(entity.get("confidence", 0.7) or 0.7)
    return round(score * (0.85 + min(max(confidence, 0.0), 1.0) * 0.15), 4)


def _entity_page_path(entity_id: str, entity: dict, pages_dir: str | Path) -> str:
    page_rel = str(entity.get("page", "")).strip()
    if page_rel:
        path = Path(pages_dir).parent / page_rel
        if path.exists():
            return str(path)
    return _page_path_for_id(entity_id, pages_dir)


def graph_search(query: str, graph_dir: str, limit: int = 10) -> list[dict]:
    """Entity-aware graph traversal search — symbolic, no embeddings."""
    graph_path = Path(graph_dir)
    entities_data = _load_json_safe(str(graph_path / "entities.json"), {})
    if not isinstance(entities_data, dict):
        entities_data = {}
    edges_data = _load_json_safe(str(graph_path / "edges.json"), {"edges": []})
    all_edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []

    if not entities_data:
        return []

    pages_dir = graph_path.parent / "pages"
    scored_entities: list[tuple[str, float]] = []
    for eid, entity in entities_data.items():
        if not isinstance(entity, dict):
            continue
        score = _entity_match_score(query, eid, entity)
        if score > 0:
            scored_entities.append((eid, score))

    results: list[dict] = []
    visited: set = set()
    relation_query = any(term in query.lower() for term in _RELATION_QUERY_TERMS)
    neighbor_scores: dict[str, tuple[float, str, str]] = {}

    for eid, match_score in sorted(scored_entities, key=lambda item: -item[1])[:limit]:
        if eid in visited:
            continue
        visited.add(eid)
        entity = entities_data.get(eid, {})
        connected: list = []
        for edge in all_edges:
            if edge.get('source') == eid or edge.get('target') == eid:
                other = edge['target'] if edge['source'] == eid else edge['source']
                if other in entities_data:
                    connected.append({
                        'entity': other,
                        'name': entities_data[other].get('name', other),
                        'relation': edge.get('type', 'related_to'),
                    })
                    if relation_query and other not in visited:
                        neighbor_score = match_score * 0.62
                        previous = neighbor_scores.get(other)
                        if previous is None or neighbor_score > previous[0]:
                            neighbor_scores[other] = (
                                neighbor_score,
                                eid,
                                edge.get('type', 'related_to'),
                            )
        path = _entity_page_path(eid, entity, pages_dir)
        results.append({
            'entity_id': eid,
            'name': entity.get('name', eid),
            'type': entity.get('type', 'unknown'),
            'confidence': match_score,
            'connected': connected[:5],
            'path': path,
            'stream': 'graph',
        })

    # For relationship queries: include 1-hop neighbors as supplement
    if relation_query and len(results) < limit:
        for eid, (match_score, source_id, relation) in sorted(
            neighbor_scores.items(),
            key=lambda item: -item[1][0],
        ):
            if len(results) >= limit:
                break
            if eid in visited:
                continue
            entity = entities_data.get(eid, {})
            if not isinstance(entity, dict):
                continue
            visited.add(eid)
            path = _entity_page_path(eid, entity, pages_dir)
            results.append({
                'entity_id': eid,
                'name': entity.get('name', eid),
                'type': entity.get('type', 'unknown'),
                'confidence': round(match_score, 4),
                'connected': [{
                    'entity': source_id,
                    'name': entities_data.get(source_id, {}).get('name', source_id),
                    'relation': relation,
                }],
                'path': path,
                'stream': 'graph',
                'graph_anchor': source_id,
            })

    return results[:limit]


# ═══════════════════════════════════════════════════════════════════════════
# Reciprocal Rank Fusion
# ═══════════════════════════════════════════════════════════════════════════

def reciprocal_rank_fusion(results: list[list[dict]], k: int = 60) -> list[dict]:
    """Fuse multiple search result lists using Reciprocal Rank Fusion."""
    fused: dict[str, dict] = {}

    for result_list in results:
        for rank, item in enumerate(result_list, start=1):
            key = item.get('file') or item.get('entity_id', str(rank))
            stream = item.get('stream', 'unknown')
            if key not in fused:
                fused[key] = dict(item)
                fused[key]['rrf_score'] = 0.0
                fused[key]['streams'] = {stream}
                fused[key]['stream_ranks'] = {}
                fused[key]['stream_scores'] = {}
            else:
                fused[key]['streams'].add(stream)
            fused[key]['rrf_score'] += 1.0 / (k + rank)
            ranks = fused[key].setdefault('stream_ranks', {})
            scores = fused[key].setdefault('stream_scores', {})
            ranks[stream] = min(rank, int(ranks.get(stream, rank)))
            try:
                score = float(item.get('score', 0))
            except (TypeError, ValueError):
                score = 0.0
            scores[stream] = max(score, float(scores.get(stream, 0.0)))

    sorted_results = sorted(fused.values(), key=lambda x: -x['rrf_score'])
    for item in sorted_results:
        item['streams'] = sorted(item['streams'])
        item['rrf_score'] = round(item['rrf_score'], 4)

    return sorted_results


# ═══════════════════════════════════════════════════════════════════════════
# Ledger table search
# ═══════════════════════════════════════════════════════════════════════════

def table_search(query: str, wiki_dir: str, limit: int = 10) -> list[dict]:
    """BM25 search over text columns in all ledger tables."""
    import duckdb

    ledger_db = Path(wiki_dir) / "ledger" / "ledger.duckdb"
    if not ledger_db.exists():
        return []

    conn = duckdb.connect(str(ledger_db))

    rows = conn.execute(
        "SELECT actual_name, display_name, fields_json FROM _registry WHERE record_count > 0"
    ).fetchall()

    if not rows:
        conn.close()
        return []

    query_terms = [_stem(t) for t in _tokenize(query)]
    if not query_terms:
        conn.close()
        return []

    results: list[dict] = []
    k1, b = 1.5, 0.75

    for actual_name, display_name, fields_json_str in rows:
        fields = json.loads(fields_json_str)
        search_cols = [
            f["name"] for f in fields
            if f.get("type") in ("string", "text") and not f.get("auto_increment")
        ]
        if not search_cols:
            continue

        try:
            table_rows = conn.execute(f'SELECT * FROM "{actual_name}"').fetchall()
            col_names = [desc[0] for desc in conn.description]
        except duckdb.Error:
            continue

        for row in table_rows:
            row_dict = dict(zip(col_names, row))
            row_id = row_dict.get("_id", "")

            text_parts = [
                str(row_dict.get(c, ""))
                for c in search_cols
                if row_dict.get(c) is not None
            ]
            search_text = " ".join(text_parts)
            if not search_text.strip():
                continue

            tokens = [_stem(t) for t in _tokenize(search_text)]
            if not tokens:
                continue

            freq = Counter(tokens)
            dl = len(tokens)

            score = 0.0
            for term in query_terms:
                f = freq.get(term, 0)
                if f == 0:
                    continue
                idf = math.log(1.0 + (50.0 - 0.5) / (0.5 + 0.5))
                score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / 50.0))

            if score > 0:
                results.append({
                    "file": f"table::{actual_name}::{row_id}",
                    "path": "",
                    "score": round(score, 3),
                    "stream": "table",
                    "table_name": actual_name,
                    "display_name": display_name,
                    "row_id": row_id,
                    "row_data": {k: v for k, v in row_dict.items()
                                 if not k.startswith("_search")},
                })

    # ── Table-level results: match table name/description/fields ──
    # A "预算表" may have no cell containing "预算", but the table IS about budgets.
    # Table-level results surface the entire table when the concept matches.
    table_results: list[dict] = []
    all_rows = conn.execute(
        "SELECT actual_name, display_name, description, fields_json FROM _registry WHERE record_count > 0"
    ).fetchall()

    for actual_name, display_name, description, fields_json_str in all_rows:
        fields = json.loads(fields_json_str)
        field_names = [f["name"] for f in fields]

        # Score table metadata against query
        table_searchable = " ".join([
            str(display_name),
            str(description or ""),
            " ".join(field_names),
        ])
        table_tokens = [_stem(t) for t in _tokenize(table_searchable)]
        if not table_tokens:
            continue

        # Simple TF scoring for table metadata
        table_score = 0.0
        for term in query_terms:
            count = table_tokens.count(term)
            if count > 0:
                table_score += count * 0.5  # Lower weight than row matches

        if table_score > 0:
            # Get sample rows for context
            try:
                sample_rows = conn.execute(
                    f'SELECT * FROM "{actual_name}" LIMIT 5'
                ).fetchall()
                sample_cols = [desc[0] for desc in conn.description]
                sample_data = [
                    {c: v for c, v in zip(sample_cols, row) if not str(c).startswith("_")}
                    for row in sample_rows
                ]
            except duckdb.Error:
                sample_data = []

            table_results.append({
                "file": f"table::{actual_name}",
                "path": "",
                "score": round(table_score, 3),
                "stream": "table",
                "table_name": actual_name,
                "display_name": display_name,
                "row_id": "",
                "is_table_level": True,
                "table_schema": {f["name"]: f["type"] for f in fields},
                "sample_rows": sample_data,
            })

    conn.close()

    # Merge row-level and table-level results
    results.sort(key=lambda x: -x["score"])
    table_results.sort(key=lambda x: -x["score"])

    # Deduplicate: if we have table-level result for a table that already has
    # row-level results, keep the table-level one as a summary (lower score)
    table_names_with_rows = {r["table_name"] for r in results}
    merged = list(results)
    for tr in table_results:
        if tr["table_name"] not in table_names_with_rows:
            # Table matched but no rows matched → add as table-level result
            merged.append(tr)
        # If rows exist, table-level result is still useful as context summary

    merged.sort(key=lambda x: -x["score"])
    return merged[:limit]


# ═══════════════════════════════════════════════════════════════════════════
# Diagnostics
# ═══════════════════════════════════════════════════════════════════════════

def search_doctor(wiki_dir: str | Path = WIKI_DIR) -> dict:
    """Return retrieval index health diagnostics."""
    wiki = Path(wiki_dir)
    pages = []
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        d = wiki / "pages" / subdir
        if d.exists():
            pages.extend(d.glob("*.md"))

    metadata_items = build_metadata_index(wiki / "pages")
    entities = _load_json_safe(str(wiki / "graph" / "entities.json"), {})
    edges_data = _load_json_safe(str(wiki / "graph" / "edges.json"), {"edges": []})
    edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []

    page_ids = {p.stem for p in pages}
    graph_ids = set(entities.keys()) if isinstance(entities, dict) else set()

    issues = []
    if not pages:
        issues.append("no wiki pages found")
    if len(metadata_items) < len(pages):
        issues.append("metadata index has fewer items than pages")
    orphan_graph_ids = sorted(graph_ids - page_ids)
    if orphan_graph_ids:
        issues.append(f"{len(orphan_graph_ids)} graph entities have no matching page")

    return {
        "pages": len(pages),
        "metadata_items": len(metadata_items),
        "entities": len(graph_ids),
        "edges": len(edges),
        "orphan_graph_entities": orphan_graph_ids[:20],
        "issues": issues,
        "healthy": not issues,
    }


def eval_retrieval(eval_file: str | Path, limit: int = 5) -> dict:
    """Evaluate search recall from a jsonl file."""
    eval_path = Path(eval_file)
    if not eval_path.exists():
        return {"status": "error", "message": f"Eval file not found: {eval_path}"}

    cases = []
    for line in eval_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))

    evaluated = []
    hits = 0
    reciprocal_ranks = []
    for case in cases:
        query = case.get("query", "")
        expected = set(case.get("expected_pages", []))
        results = reciprocal_rank_fusion([
            metadata_search(query, str(PAGES_DIR), limit=limit * 2),
            bm25_search(query, str(PAGES_DIR), limit=limit * 2),
            graph_search(query, str(GRAPH_DIR), limit=limit),
        ])[:limit]
        returned = [r.get("file") or r.get("entity_id", "") for r in results]
        first_rank = None
        for rank, rid in enumerate(returned, 1):
            if rid in expected:
                first_rank = rank
                break
        hit = first_rank is not None if expected else bool(returned)
        if hit:
            hits += 1
            reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        evaluated.append({
            "query": query,
            "expected": sorted(expected),
            "returned": returned,
            "hit": hit,
            "rank": first_rank,
        })

    total = len(cases)
    return {
        "status": "ok",
        "cases": total,
        "recall_at_k": round(hits / total, 4) if total else 0.0,
        "mrr": round(sum(reciprocal_ranks) / total, 4) if total else 0.0,
        "details": evaluated,
    }


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Hybrid Search')
    parser.add_argument('query', nargs='?', help='Search query')
    parser.add_argument('--streams', default='metadata,bm25,graph,ledger',
                        help='Comma-separated streams: metadata,bm25,graph,table')
    parser.add_argument('--limit', type=int, default=10, help='Max results per stream')
    parser.add_argument('--impact', help='Impact analysis (entity ID)')
    parser.add_argument('--related', help='Find entities related to this entity ID')
    parser.add_argument('--doctor', action='store_true', help='Diagnose retrieval index health')
    parser.add_argument('--eval', dest='eval_file', help='Evaluate retrieval with a jsonl file')
    args = parser.parse_args()

    if args.doctor:
        print(json.dumps(search_doctor(WIKI_DIR), indent=2, ensure_ascii=False, default=str))
        return

    if args.eval_file:
        print(json.dumps(
            eval_retrieval(args.eval_file, limit=args.limit),
            indent=2, ensure_ascii=False, default=str,
        ))
        return

    if args.impact:
        from graph import impact_analysis
        result = impact_analysis(args.impact)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.related:
        from graph import traverse
        result = traverse(args.related, depth=1)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not args.query:
        parser.print_help()
        sys.exit(1)

    streams = [s.strip() for s in args.streams.split(',')]
    all_results: list[list[dict]] = []

    if 'bm25' in streams:
        all_results.append(bm25_search(args.query, PAGES_DIR, args.limit))
    if 'metadata' in streams:
        all_results.append(metadata_search(args.query, PAGES_DIR, args.limit))
    if 'graph' in streams:
        all_results.append(graph_search(args.query, GRAPH_DIR, args.limit))
    if 'table' in streams:
        all_results.append(table_search(args.query, str(WIKI_DIR), args.limit))

    if len(all_results) >= 2:
        fused = reciprocal_rank_fusion(all_results)
        output = {'query': args.query, 'streams': streams, 'method': 'rrf',
                  'total_results': len(fused), 'results': fused}
    else:
        output = {'query': args.query, 'streams': streams, 'method': 'single',
                  'total_results': len(all_results[0]) if all_results else 0,
                  'results': all_results[0] if all_results else []}

    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
