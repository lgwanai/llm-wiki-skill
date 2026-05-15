#!/usr/bin/env python3
from __future__ import annotations
"""search.py — Hybrid Search over Wiki Pages for llm-wiki."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
from collections import Counter

WIKI_DIR = Path(__file__).parent.parent / ".wiki"
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
ENTITIES_FILE = os.path.join(GRAPH_DIR, "entities.json")
EDGES_FILE = os.path.join(GRAPH_DIR, "edges.json")


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


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens."""
    return re.findall(r'[a-z0-9]+', text.lower())


def _stem(word: str) -> str:
    """Simple Porter-style stemming (suffix stripping)."""
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
    """BM25 keyword search with stemming over wiki pages."""
    k1, b = 1.5, 0.75
    query_terms = [_stem(t) for t in _tokenize(query)]

    # Collect all pages
    all_docs: dict[str, str] = {}
    for subdir in ('concepts', 'entities', 'models', 'techniques', 'frameworks',
                   'benchmarks', 'papers', 'decisions', 'sessions', 'patterns'):
        scan_dir = os.path.join(pages_dir, subdir)
        if not os.path.isdir(scan_dir):
            continue
        for filename in os.listdir(scan_dir):
            if filename.endswith('.md'):
                filepath = os.path.join(scan_dir, filename)
                all_docs[filepath] = _read_page_content(filepath)

    if not all_docs or not query_terms:
        return []

    # Compute document lengths and term frequencies
    doc_lengths: dict[str, int] = {}
    doc_term_freqs: dict[str, Counter] = {}
    total_length = 0

    for path, content in all_docs.items():
        tokens = [_stem(t) for t in _tokenize(content)]
        doc_lengths[path] = len(tokens)
        doc_term_freqs[path] = Counter(tokens)
        total_length += len(tokens)

    avg_dl = total_length / len(all_docs) if all_docs else 1
    num_docs = len(all_docs)
    doc_freq: Counter = Counter()

    for tf in doc_term_freqs.values():
        doc_freq.update(set(tf.keys()))

    # Score each document
    scores: list[tuple[str, float]] = []
    for path, tf in doc_term_freqs.items():
        score = 0.0
        dl = doc_lengths[path]
        for term in query_terms:
            if term not in tf:
                continue
            f = tf[term]
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
    """Semantic search using Ollama embeddings (qwen3-embedding:8b).

    Falls back to Jaccard similarity if:
    - Ollama is unreachable
    - No embeddings have been generated yet (graph/embeddings.json missing)
    """
    embeddings_path = WIKI_DIR / "graph" / "embeddings.json"

    if os.path.exists(embeddings_path):
        embeddings_data = _load_json_safe(embeddings_path, {})
    else:
        embeddings_data = {}

    if isinstance(embeddings_data, dict) and embeddings_data:
        from _ollama import get_embedding

        query_emb = get_embedding(query)
        if query_emb is None:
            return _jaccard_fallback(query, pages_dir, limit)

        result_list: list[dict] = []
        for page_id, emb in embeddings_data.items():
            if isinstance(emb, list) and len(emb) > 0:
                sim = _cosine_similarity(query_emb, emb)
                if sim > 0:
                    result_list.append({'file': page_id, 'score': round(sim, 4), 'stream': 'vector'})
        result_list.sort(key=lambda x: -x['score'])
        return result_list[:limit]

    return _jaccard_fallback(query, pages_dir, limit)


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
    return [{'file': f, 'score': round(s, 3), 'stream': 'vector'} for f, s in scores[:limit]]


def graph_search(query: str, graph_dir: str, limit: int = 10) -> list[dict]:
    """Entity-aware graph traversal search."""
    entities_data = _load_json(ENTITIES_FILE)
    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []

    if not isinstance(entities_data, dict) or not entities_data:
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


def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Hybrid Search')
    parser.add_argument('query', nargs='?', help='Search query')
    parser.add_argument('--streams', default='bm25,vector,graph',
                        help='Comma-separated streams to use')
    parser.add_argument('--limit', type=int, default=10, help='Max results per stream')
    parser.add_argument('--impact', help='Impact analysis (entity ID)')
    parser.add_argument('--related', help='Find entities related to this entity ID')
    args = parser.parse_args()

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
    if 'vector' in streams:
        all_results.append(vector_search(args.query, PAGES_DIR, args.limit))
    if 'graph' in streams:
        all_results.append(graph_search(args.query, GRAPH_DIR, args.limit))

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
