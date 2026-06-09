#!/usr/bin/env python3
from __future__ import annotations
"""search.py — Hybrid Search over Wiki Pages for llm-wiki."""

import argparse
import json
import math
import os
import sys
from pathlib import Path
import re
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
from config import get_wiki_dir

import yaml

try:
    import jieba
except ImportError:
    jieba = None

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
ENTITIES_FILE = os.path.join(GRAPH_DIR, "entities.json")
EDGES_FILE = os.path.join(GRAPH_DIR, "edges.json")

# ── Module-level caches (cleared when pages change) ──
_cache_marker: tuple[int, float] | None = None  # (file_count, latest_mtime)
_entities_cache: dict | None = None
_edges_cache: dict | list | None = None
_bm25_index: dict | None = None
_BM25_CACHE_FILE = WIKI_DIR / "graph" / ".bm25_index.json"
_CHUNK_CACHE_FILE = WIKI_DIR / "graph" / ".chunk_index.json"
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
    """Persist BM25 index to disk (survives process restarts)."""
    try:
        serializable = {}
        for path, data in idx.items():
            serializable[path] = {
                "tokens": data["tokens"],
                "freqs": dict(data["freqs"]),
                "length": data["length"],
            }
        _BM25_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BM25_CACHE_FILE.write_text(json.dumps(serializable, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_bm25_cache() -> dict | None:
    """Load BM25 index from disk if it exists and pages haven't changed."""
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
    """Load JSON, returning default for missing/corrupt files (no magic detection)."""
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
    """Read a page as (frontmatter, body)."""
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
    # Chinese tokenization via jieba
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > 0 and jieba is not None:
        tokens.extend(w for w in jieba.cut(text) if len(w.strip()) > 1)
    else:
        tokens.extend(re.findall(r'[a-z0-9]+', text.lower()))
    # Also extract English tokens if CJK content is mixed with English
    if cjk_chars > 0 and len(text) > cjk_chars * 1.5:
        tokens.extend(re.findall(r'[a-z0-9]+', text.lower()))
    return tokens


def _split_markdown_chunks(content: str, page_id: str, path: str, max_chars: int = 1800) -> list[dict]:
    """Split markdown into heading-aware chunks for more precise retrieval."""
    chunks: list[dict] = []
    heading_path: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if not text:
            return
        while len(text) > max_chars:
            part = text[:max_chars]
            cut = max(part.rfind("\n\n"), part.rfind("\n"), part.rfind(". "))
            if cut < max_chars // 2:
                cut = max_chars
            chunk_text = text[:cut].strip()
            chunks.append({
                "chunk_id": f"{page_id}#chunk-{len(chunks)+1}",
                "page_id": page_id,
                "path": path,
                "heading_path": list(heading_path),
                "text": chunk_text,
            })
            text = text[cut:].strip()
        if text:
            chunks.append({
                "chunk_id": f"{page_id}#chunk-{len(chunks)+1}",
                "page_id": page_id,
                "path": path,
                "heading_path": list(heading_path),
                "text": text,
            })

    for line in content.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            flush()
            current_lines = []
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_path = heading_path[: level - 1]
            heading_path.append(title)
            current_lines.append(line)
        else:
            current_lines.append(line)
    flush()
    return chunks


def build_chunk_index(pages_dir: str | Path = PAGES_DIR) -> list[dict]:
    """Build chunk metadata for all pages."""
    chunks: list[dict] = []
    for path in _known_page_paths(pages_dir):
        content = _read_page_content(str(path))
        if not content:
            continue
        chunks.extend(_split_markdown_chunks(content, path.stem, str(path)))
    return chunks


def _load_chunk_index(pages_dir: str | Path = PAGES_DIR) -> list[dict]:
    """Load or rebuild the disk-backed chunk index."""
    if _pages_changed() or not _CHUNK_CACHE_FILE.exists():
        chunks = build_chunk_index(pages_dir)
        try:
            _CHUNK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CHUNK_CACHE_FILE.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return chunks
    try:
        data = json.loads(_CHUNK_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return build_chunk_index(pages_dir)


def chunk_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """BM25 search over heading-aware chunks."""
    chunks = _load_chunk_index(pages_dir)
    query_terms = [_stem(t) for t in _tokenize(query)]
    if not chunks or not query_terms:
        return []

    docs = []
    for chunk in chunks:
        tokens = [_stem(t) for t in _tokenize(chunk.get("text", ""))]
        if tokens:
            docs.append((chunk, tokens, Counter(tokens)))
    if not docs:
        return []

    num_docs = len(docs)
    avg_dl = sum(len(tokens) for _, tokens, _ in docs) / num_docs
    doc_freq: Counter = Counter()
    for _, _, freqs in docs:
        doc_freq.update(set(freqs.keys()))

    scored: list[tuple[dict, float]] = []
    k1, b = 1.5, 0.75
    for chunk, tokens, freqs in docs:
        dl = len(tokens)
        score = 0.0
        for term in query_terms:
            f = freqs.get(term, 0)
            if f == 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg_dl))
        if score > 0:
            scored.append((chunk, score))

    scored.sort(key=lambda x: -x[1])
    return [
        {
            "file": chunk["page_id"],
            "path": chunk["path"],
            "score": round(score, 3),
            "stream": "chunk",
            "chunk_id": chunk["chunk_id"],
            "heading_path": chunk.get("heading_path", []),
            "text": chunk.get("text", "")[:1000],
        }
        for chunk, score in scored[:limit]
    ]


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
        }
        searchable = " ".join([
            str(fields["id"]),
            str(fields["name"]),
            str(fields["type"]),
            str(fields["summary"]),
            " ".join(fields["aliases"]),
            " ".join(fields["keywords"]),
            " ".join(fields["questions"]),
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
            _METADATA_CACHE_FILE.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return items
    try:
        data = json.loads(_METADATA_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return build_metadata_index(pages_dir)


def metadata_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """Search page frontmatter metadata: aliases, keywords, summary, questions."""
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


def _stem(word: str) -> str:
    """Simple Porter-style stemming (suffix stripping). English only — CJK passed through."""
    if any('\u4e00' <= c <= '\u9fff' for c in word):
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def bm25_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """BM25 keyword search with stemming over wiki pages. Uses index cache."""
    global _bm25_index
    k1, b = 1.5, 0.75
    query_terms = [_stem(t) for t in _tokenize(query)]
    if not query_terms:
        return []

    # Build or reuse cached index (disk-backed for cross-process persistence)
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

    # Compute IDF from index
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


def vector_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """Semantic search using the configured embedding provider.

    Falls back to Jaccard similarity if:
    - embedding provider is unreachable
    - No embeddings have been generated yet (graph/embeddings.json missing)
    - embeddings are stale or incompatible with current config
    """
    embeddings_path = WIKI_DIR / "graph" / "embeddings.json"

    try:
        from generate_embeddings import (
            embedding_index_status,
            get_embedding,
            load_embedding_index,
        )
    except Exception:
        return _jaccard_fallback(query, pages_dir, limit)

    if not os.path.exists(embeddings_path):
        return _jaccard_fallback(query, pages_dir, limit)

    status = embedding_index_status(Path(embeddings_path))
    if status.get("stale"):
        return _jaccard_fallback(query, pages_dir, limit)

    _, embeddings_data = load_embedding_index(Path(embeddings_path))
    if not embeddings_data:
        return _jaccard_fallback(query, pages_dir, limit)

    query_emb = get_embedding(query)
    if query_emb is None:
        return _jaccard_fallback(query, pages_dir, limit)

    result_list: list[dict] = []
    for page_id, emb in embeddings_data.items():
        if isinstance(emb, list) and len(emb) > 0:
            sim = _cosine_similarity(query_emb, emb)
            if sim > 0:
                result_list.append({
                    'file': page_id,
                    'path': _page_path_for_id(page_id, pages_dir),
                    'score': round(sim, 4),
                    'stream': 'vector',
                })
    result_list.sort(key=lambda x: -x['score'])
    return result_list[:limit]


def vector_chunk_search(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """Semantic search over chunk-level embeddings."""
    chunk_embeddings_path = WIKI_DIR / "graph" / "chunk_embeddings.json"
    try:
        from generate_embeddings import (
            embedding_index_status,
            get_embedding,
            load_embedding_index,
        )
    except Exception:
        return []

    if not chunk_embeddings_path.exists():
        return []

    status = embedding_index_status(chunk_embeddings_path)
    if status.get("stale"):
        return []

    _, items = load_embedding_index(chunk_embeddings_path)
    if not items:
        return []

    query_emb = get_embedding(query)
    if query_emb is None:
        return []

    result_list: list[dict] = []
    for chunk_id, item in items.items():
        if not isinstance(item, dict):
            continue
        emb = item.get("embedding")
        if isinstance(emb, list) and emb:
            sim = _cosine_similarity(query_emb, emb)
            if sim > 0:
                result_list.append({
                    "file": item.get("page_id", ""),
                    "path": item.get("path", ""),
                    "score": round(sim, 4),
                    "stream": "chunk_vector",
                    "chunk_id": chunk_id,
                    "heading_path": item.get("heading_path", []),
                    "text": item.get("text", "")[:1000],
                })
    result_list.sort(key=lambda x: -x["score"])
    return result_list[:limit]



def _jaccard_fallback(query: str, pages_dir: str, limit: int = 10) -> list[dict]:
    """Jaccard similarity fallback when embeddings are unavailable."""
    all_docs: dict[str, str] = {}
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        scan_dir = os.path.join(pages_dir, subdir)
        if not os.path.isdir(scan_dir):
            continue
        for filename in os.listdir(scan_dir):
            if filename.endswith('.md'):
                filepath = os.path.join(scan_dir, filename)
                all_docs[filename] = _read_page_content(filepath)

    if not all_docs:
        return []

    query_terms = set(_tokenize(query))
    scores: list[tuple[str, float]] = []
    for filename, content in all_docs.items():
        doc_terms = set(_tokenize(content))
        if not doc_terms:
            continue
        intersection = query_terms & doc_terms
        jaccard = len(intersection) / len(query_terms | doc_terms)
        if jaccard > 0:
            scores.append((filename, jaccard))

    scores.sort(key=lambda x: -x[1])
    return [
        {
            'file': os.path.splitext(f)[0],
            'path': _page_path_for_id(os.path.splitext(f)[0], pages_dir),
            'score': round(s, 3),
            'stream': 'vector',
        }
        for f, s in scores[:limit]
    ]


def graph_search(query: str, graph_dir: str, limit: int = 10) -> list[dict]:
    """Entity-aware graph traversal search."""
    graph_path = Path(graph_dir)
    entities_data = _load_json_safe(str(graph_path / "entities.json"), {})
    if not isinstance(entities_data, dict):
        entities_data = {}
    edges_data = _load_json_safe(str(graph_path / "edges.json"), {"edges": []})
    all_edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []

    if not entities_data:
        return []

    query_lower = query.lower()
    matching: list = []

    for eid, entity in entities_data.items():
        name = entity.get('name', '').lower()
        etype = entity.get('type', '').lower()
        if query_lower in name or query_lower in etype or query_lower in eid:
            matching.append(eid)

    if not matching:
        for eid, entity in entities_data.items():
            name = entity.get('name', '').lower()
            if any(qt in name for qt in query_lower.split()):
                matching.append(eid)

    results: list[dict] = []
    visited: set = set()

    for eid in matching[:3]:
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
        results.append({
            'entity_id': eid,
            'name': entity.get('name', eid),
            'type': entity.get('type', 'unknown'),
            'confidence': entity.get('confidence', 0.5),
            'connected': connected[:5],
            'stream': 'graph',
        })

    return results[:limit]


def reciprocal_rank_fusion(results: list[list[dict]], k: int = 60) -> list[dict]:
    """Fuse multiple search result lists using Reciprocal Rank Fusion."""
    fused: dict[str, dict] = {}

    for result_list in results:
        for rank, item in enumerate(result_list, start=1):
            key = item.get('file') or item.get('entity_id', str(rank))
            if key not in fused:
                fused[key] = dict(item)
                fused[key]['rrf_score'] = 0.0
                fused[key]['streams'] = {item.get('stream', 'unknown')}
            else:
                fused[key]['streams'].add(item.get('stream', 'unknown'))
            fused[key]['rrf_score'] += 1.0 / (k + rank)

    sorted_results = sorted(fused.values(), key=lambda x: -x['rrf_score'])
    for item in sorted_results:
        item['streams'] = sorted(item['streams'])
        item['rrf_score'] = round(item['rrf_score'], 4)

    return sorted_results


def search_doctor(wiki_dir: str | Path = WIKI_DIR) -> dict:
    """Return retrieval index health diagnostics."""
    wiki = Path(wiki_dir)
    pages = []
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        d = wiki / "pages" / subdir
        if d.exists():
            pages.extend(d.glob("*.md"))

    try:
        from generate_embeddings import embedding_index_status
        embedding_status = embedding_index_status(wiki / "graph" / "embeddings.json")
        chunk_embedding_status = embedding_index_status(wiki / "graph" / "chunk_embeddings.json")
    except Exception as e:
        embedding_status = {"exists": False, "stale": True, "reason": str(e)}
        chunk_embedding_status = {"exists": False, "stale": True, "reason": str(e), "items": 0}

    chunks = build_chunk_index(wiki / "pages")
    metadata_items = build_metadata_index(wiki / "pages")
    entities = _load_json_safe(str(wiki / "graph" / "entities.json"), {})
    edges_data = _load_json_safe(str(wiki / "graph" / "edges.json"), {"edges": []})
    edges = edges_data.get("edges", []) if isinstance(edges_data, dict) else []

    page_ids = {p.stem for p in pages}
    graph_ids = set(entities.keys()) if isinstance(entities, dict) else set()

    issues = []
    if not pages:
        issues.append("no wiki pages found")
    if embedding_status.get("stale"):
        issues.append(f"embedding index stale: {embedding_status.get('reason', 'unknown')}")
    embedding_items = int(embedding_status.get("items", 0) or 0)
    chunk_embedding_items = int(chunk_embedding_status.get("items", 0) or 0)
    if pages and embedding_items == 0:
        issues.append("embedding index has no items")
    if chunks and chunk_embedding_status.get("exists") and chunk_embedding_items == 0:
        issues.append("chunk embedding index has no items")
    if len(chunks) < len(pages):
        issues.append("chunk index has fewer chunks than pages")
    if len(metadata_items) < len(pages):
        issues.append("metadata index has fewer items than pages")
    orphan_graph_ids = sorted(graph_ids - page_ids)
    if orphan_graph_ids:
        issues.append(f"{len(orphan_graph_ids)} graph entities have no matching page")

    return {
        "pages": len(pages),
        "chunks": len(chunks),
        "metadata_items": len(metadata_items),
        "entities": len(graph_ids),
        "edges": len(edges),
        "embedding": embedding_status,
        "chunk_embedding": chunk_embedding_status,
        "embedding_coverage_pct": round(embedding_items / max(len(pages), 1) * 100, 1),
        "chunk_embedding_coverage_pct": round(chunk_embedding_items / max(len(chunks), 1) * 100, 1),
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
            chunk_search(query, str(PAGES_DIR), limit=limit * 2),
            vector_chunk_search(query, str(PAGES_DIR), limit=limit),
            bm25_search(query, str(PAGES_DIR), limit=limit * 2),
            vector_search(query, str(PAGES_DIR), limit=limit),
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


# ═══════════════════════════════════════════════════════════════════════
# Ledger table search
# ═══════════════════════════════════════════════════════════════════════


def table_search(query: str, wiki_dir: str, limit: int = 10) -> list[dict]:
    """BM25 search over text columns in all ledger tables.

    Reuses jieba tokenization and BM25 scoring from bm25_search().
    Returns results compatible with reciprocal_rank_fusion().
    """
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

            # Concatenate text columns for search
            text_parts = [str(row_dict.get(c, "")) for c in search_cols if row_dict.get(c) is not None]
            search_text = " ".join(text_parts)
            if not search_text.strip():
                continue

            tokens = [_stem(t) for t in _tokenize(search_text)]
            if not tokens:
                continue

            freq = Counter(tokens)
            dl = len(tokens)

            # BM25 scoring
            score = 0.0
            for term in query_terms:
                f = freq.get(term, 0)
                if f == 0:
                    continue
                # Approximate IDF using row length
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
                    "row_data": {k: v for k, v in row_dict.items() if not k.startswith("_search")},
                })

    conn.close()
    results.sort(key=lambda x: -x["score"])
    return results[:limit]


def table_vector_search(query: str, wiki_dir: str, limit: int = 10) -> list[dict]:
    """Cosine similarity search over embedded table rows.

    Uses _embeddings table and DuckDB array_cosine_similarity.
    """
    import duckdb

    ledger_db = Path(wiki_dir) / "ledger" / "ledger.duckdb"
    if not ledger_db.exists():
        return []

    conn = duckdb.connect(str(ledger_db))

    # Check if embeddings exist
    emb_count = conn.execute("SELECT COUNT(*) FROM _embeddings").fetchone()[0]
    if emb_count == 0:
        conn.close()
        return []

    # Get query embedding
    try:
        from generate_embeddings import get_embedding
        query_emb = get_embedding(query)
    except (ImportError, Exception):
        conn.close()
        return []

    if query_emb is None:
        conn.close()
        return []

    dim = len(query_emb)
    query_emb_str = "[" + ", ".join(str(v) for v in query_emb) + "]"

    try:
        rows = conn.execute(f"""
            SELECT e.table_name, e.row_id,
                   array_cosine_similarity(e.embedding, {query_emb_str}::FLOAT[{dim}]) AS sim,
                   r.display_name
            FROM _embeddings e
            JOIN _registry r ON e.table_name = r.actual_name
            WHERE len(e.embedding) = {dim}
            ORDER BY sim DESC
            LIMIT ?
        """, [limit]).fetchall()
    except duckdb.Error:
        conn.close()
        return []

    conn.close()

    return [{
        "file": f"table::{r[0]}::{r[1]}",
        "path": "",
        "score": round(r[2], 4),
        "stream": "table_vector",
        "table_name": r[0],
        "display_name": r[3],
        "row_id": r[1],
    } for r in rows if r[2] and r[2] > 0]


def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Hybrid Search')
    parser.add_argument('query', nargs='?', help='Search query')
    parser.add_argument('--streams', default='bm25,vector,graph',
                        help='Comma-separated streams to use')
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
        print(json.dumps(eval_retrieval(args.eval_file, limit=args.limit), indent=2, ensure_ascii=False, default=str))
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
    if 'chunk' in streams:
        all_results.append(chunk_search(args.query, PAGES_DIR, args.limit))
    if 'vector' in streams:
        all_results.append(vector_search(args.query, PAGES_DIR, args.limit))
    if 'chunk_vector' in streams:
        all_results.append(vector_chunk_search(args.query, PAGES_DIR, args.limit))
    if 'graph' in streams:
        all_results.append(graph_search(args.query, GRAPH_DIR, args.limit))
    if 'table' in streams:
        all_results.append(table_search(args.query, str(WIKI_DIR), args.limit))
    if 'table_vector' in streams:
        all_results.append(table_vector_search(args.query, str(WIKI_DIR), args.limit))

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
