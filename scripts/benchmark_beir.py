#!/usr/bin/env python3
"""benchmark_beir.py — BEIR retrieval benchmark with industry baseline comparison.

Evaluates BM25, Dense, and Hybrid retrieval on standard BEIR datasets
(SciFact, NFCorpus, FiQA-2018) and compares results against published
baselines from the BEIR paper, BGE paper, and MTEB leaderboard.

Usage:
    python scripts/benchmark_beir.py scifact
    python scripts/benchmark_beir.py --all
    python scripts/benchmark_beir.py nfcorpus --methods bm25,dense,hybrid
    python scripts/benchmark_beir.py --all --report BENCHMARK.md
    python scripts/benchmark_beir.py --all -o .wiki/benchmark/beir_results.json

Dependencies:
    pip install beir
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
try:
    import jieba
except ImportError:
    jieba = None  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════
# BEIR Dataset Registry
# ═══════════════════════════════════════════════════════════════════════

BEIR_DATASETS = {
    "scifact": {
        "name": "SciFact",
        "url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
        "corpus_size": 5183,
        "queries": 1109,
        "domain": "Scientific Claim Verification",
    },
    "nfcorpus": {
        "name": "NFCorpus",
        "url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip",
        "corpus_size": 3633,
        "queries": 323,
        "domain": "Biomedical Abstracts",
    },
    "fiqa": {
        "name": "FiQA-2018",
        "url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/fiqa.zip",
        "corpus_size": 57638,
        "queries": 648,
        "domain": "Financial QA",
    },
}

# Published baselines: NDCG@10 scores from BEIR paper (Thakur et al., 2021),
# BGE paper (Xiao et al., 2023), and MTEB leaderboard.
PUBLISHED_BASELINES: dict[str, dict[str, dict[str, float]]] = {
    "scifact": {
        "BM25 (BEIR)":        {"NDCG@10": 0.665, "Recall@10": 0.907, "MRR@10": 0.587},
        "Dense-BGE-base":     {"NDCG@10": 0.725, "Recall@10": 0.940, "MRR@10": 0.645},
        "Dense-BGE-large":    {"NDCG@10": 0.740, "Recall@10": 0.948, "MRR@10": 0.660},
        "Hybrid (BM25+BGE)":  {"NDCG@10": 0.740, "Recall@10": 0.950, "MRR@10": 0.665},
        "SOTA (MTEB best)":   {"NDCG@10": 0.770, "Recall@10": 0.958, "MRR@10": 0.698},
    },
    "nfcorpus": {
        "BM25 (BEIR)":        {"NDCG@10": 0.325, "Recall@10": 0.193, "MRR@10": 0.313},
        "Dense-BGE-base":     {"NDCG@10": 0.352, "Recall@10": 0.219, "MRR@10": 0.354},
        "Dense-BGE-large":    {"NDCG@10": 0.365, "Recall@10": 0.228, "MRR@10": 0.370},
        "Hybrid (BM25+BGE)":  {"NDCG@10": 0.370, "Recall@10": 0.235, "MRR@10": 0.378},
        "SOTA (MTEB best)":   {"NDCG@10": 0.390, "Recall@10": 0.250, "MRR@10": 0.405},
    },
    "fiqa": {
        "BM25 (BEIR)":        {"NDCG@10": 0.236, "Recall@10": 0.539, "MRR@10": 0.389},
        "Dense-BGE-base":     {"NDCG@10": 0.355, "Recall@10": 0.685, "MRR@10": 0.520},
        "Dense-BGE-large":    {"NDCG@10": 0.375, "Recall@10": 0.708, "MRR@10": 0.545},
        "Hybrid (BM25+BGE)":  {"NDCG@10": 0.380, "Recall@10": 0.715, "MRR@10": 0.558},
        "SOTA (MTEB best)":   {"NDCG@10": 0.430, "Recall@10": 0.760, "MRR@10": 0.610},
    },
}


# ═══════════════════════════════════════════════════════════════════════
# Tokenization & Stemming (exact match with search.py)
# ═══════════════════════════════════════════════════════════════════════

def _tokenize(text: str) -> list[str]:
    """Split text into tokens: jieba for Chinese, regex for English."""
    tokens: list[str] = []
    cjk_chars = sum(1 for c in text if '一' <= c <= '鿿')
    if cjk_chars > 0 and jieba is not None:
        tokens.extend(w for w in jieba.cut(text) if len(w.strip()) > 1)
    else:
        tokens.extend(re.findall(r'[a-z0-9]+', text.lower()))
    if cjk_chars > 0 and len(text) > cjk_chars * 1.5:
        tokens.extend(re.findall(r'[a-z0-9]+', text.lower()))
    return tokens


def _stem(word: str) -> str:
    """Simple Porter-style stemming (suffix stripping)."""
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════════════════
# BEIR Data Download & Load
# ═══════════════════════════════════════════════════════════════════════

BEIR_CACHE_DIR = Path(__file__).parent.parent / "evals" / "beir"
BEIR_WIKI_CACHE_DIR = Path(__file__).parent.parent / "evals" / "beir_wiki"
DOWNLOAD_ENABLED = True
DEFAULT_BENCHMARK_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"


def _metric_k(k_values: list[int]) -> int:
    """Return the primary k used for summaries and baseline comparison."""
    return 10 if 10 in k_values else max(k_values)


def _get_metric(result: dict[str, Any], metric: str, k_values: list[int]) -> float:
    return float(result.get(f"{metric}@{_metric_k(k_values)}", 0.0))


def download_beir(dataset_key: str) -> Path:
    """Download a BEIR dataset zip and extract to evals/beir/<key>/."""
    info = BEIR_DATASETS[dataset_key]
    target_dir = BEIR_CACHE_DIR / dataset_key
    if target_dir.exists() and (target_dir / "corpus.jsonl").exists():
        return target_dir
    if not DOWNLOAD_ENABLED:
        raise FileNotFoundError(
            f"BEIR dataset '{dataset_key}' is not cached at {target_dir}; "
            "rerun without --no-download to fetch it."
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    url = info["url"]
    print(f"  Downloading {info['name']} from {url}...", file=sys.stderr)
    resp = urllib.request.urlopen(url, timeout=120)
    data = resp.read()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        prefix = f"{dataset_key}/"
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            rel = name[len(prefix):] if name.startswith(prefix) else name
            dest = target_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name))

    return target_dir


def load_beir(dataset_key: str) -> tuple[dict, dict, dict]:
    """Load BEIR corpus, queries, qrels. Returns (corpus, queries, qrels)."""
    data_dir = download_beir(dataset_key)

    corpus: dict[str, dict[str, str]] = {}
    corpus_file = data_dir / "corpus.jsonl"
    if corpus_file.exists():
        for line in corpus_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            doc = json.loads(line)
            doc_id = str(doc["_id"])
            corpus[doc_id] = {
                "title": doc.get("title", ""),
                "text": doc.get("text", ""),
            }

    queries: dict[str, str] = {}
    queries_file = data_dir / "queries.jsonl"
    if queries_file.exists():
        for line in queries_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            q = json.loads(line)
            queries[str(q["_id"])] = q["text"]

    qrels: dict[str, dict[str, int]] = {}
    qrels_dir = data_dir / "qrels"
    for split in ("test",):
        qrels_file = qrels_dir / f"{split}.tsv"
        if not qrels_file.exists():
            continue
        for line in qrels_file.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("query-id"):
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                qid, cid, score = parts[0], parts[1], int(parts[2])
                if score > 0:
                    qrels.setdefault(qid, {})[cid] = score

    return corpus, queries, qrels


def _doc_slug(doc_id: str) -> str:
    """Create a filesystem-safe stable wiki page id for an external document id."""
    digest = hashlib.sha1(doc_id.encode("utf-8")).hexdigest()[:16]
    return f"beir-{digest}"


def _yaml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _corpus_hash(corpus: dict[str, dict[str, str]]) -> str:
    """Stable hash of the corpus for cache invalidation."""
    h = hashlib.sha1()
    for doc_id in sorted(corpus.keys()):
        h.update(doc_id.encode())
        h.update(corpus[doc_id].get("title", "").encode())
        h.update(corpus[doc_id].get("text", "").encode())
    return h.hexdigest()[:16]


def _write_beir_sources(
    dataset_key: str, corpus: dict[str, dict[str, str]]
) -> tuple[Path, dict[str, str]]:
    """Write BEIR corpus as raw source files for compile_v2.

    Each BEIR document becomes a plain markdown source file with its
    original title and text (no wiki YAML frontmatter — that's added by
    compile_v2 during LLM entity extraction).

    Returns (source_dir, source_to_doc_map) where source_to_doc_map
    maps source basename → BEIR doc_id.
    """
    root = BEIR_WIKI_CACHE_DIR / dataset_key
    source_dir = root / "source" / "papers"
    source_dir.mkdir(parents=True, exist_ok=True)

    source_to_doc: dict[str, str] = {}
    for doc_id, doc in corpus.items():
        slug = _doc_slug(str(doc_id))
        source_to_doc[slug] = str(doc_id)
        title = doc.get("title") or str(doc_id)
        text = doc.get("text", "")
        source_content = f"# {title}\n\n{text}\n"
        (source_dir / f"{slug}.md").write_text(source_content, encoding="utf-8")

    return source_dir, source_to_doc


def _build_beir_page_map(
    wiki_dir: Path, source_to_doc: dict[str, str]
) -> dict[str, str]:
    """Map compiled wiki page IDs → BEIR doc IDs via entities.json sources.

    compile_v2 stores the source filename in entities.json as `sources: [filename]`.
    We match source basenames to BEIR doc IDs to build the reverse mapping.
    """
    entities_file = wiki_dir / "graph" / "entities.json"
    if not entities_file.exists():
        return {}

    try:
        entities = json.loads(entities_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    page_to_doc: dict[str, str] = {}
    for eid, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        sources = entity.get("sources", [])
        if isinstance(sources, str):
            sources = [sources]
        for src in sources:
            src_stem = Path(src).stem
            if src_stem in source_to_doc:
                page_to_doc[eid] = source_to_doc[src_stem]
                break

    return page_to_doc


def _ensure_beir_wiki(
    dataset_key: str,
    corpus: dict[str, dict[str, str]],
    use_compile: bool = True,
    force_recompile: bool = False,
) -> tuple[Path, dict[str, str]]:
    """Ensure BEIR corpus is materialized as an llm-wiki project.

    Two modes:
      --compile (default): Write source files → compile_v2 → wiki pages
      --no-compile: Skip LLM compile, write wiki pages directly (legacy fast path)

    Cache key includes: dataset_key, corpus hash, compile mode.
    Returns (wiki_dir, page_to_doc_map).
    """
    root = BEIR_WIKI_CACHE_DIR / dataset_key
    wiki_dir = root / ".wiki"
    manifest_path = root / "manifest.json"
    page_map_path = root / "page_to_doc_map.json"

    if not use_compile:
        # Legacy fast path: write wiki pages directly (no LLM)
        return _write_beir_wiki_legacy(dataset_key, corpus)

    # Compile mode: cache by corpus hash
    chash = _corpus_hash(corpus)
    expected_manifest = {
        "dataset_key": dataset_key,
        "corpus_size": len(corpus),
        "corpus_hash": chash,
        "format": "llm-wiki-beir-v2-compiled",
    }

    if not force_recompile and manifest_path.exists() and page_map_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest == expected_manifest:
                mapping = json.loads(page_map_path.read_text(encoding="utf-8"))
                return wiki_dir, {str(k): str(v) for k, v in mapping.items()}
        except (json.JSONDecodeError, OSError):
            pass

    # Clean and rebuild
    if root.exists():
        shutil.rmtree(root)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Write source files
    source_dir, source_to_doc = _write_beir_sources(dataset_key, corpus)
    print(f"  Wrote {len(source_to_doc)} source files → {source_dir}", file=sys.stderr)

    # Step 2: Compile through llm-wiki pipeline
    # Set LLM_WIKI_DIR to isolate from user's active wiki
    old_wiki_dir = os.environ.get("LLM_WIKI_DIR")
    os.environ["LLM_WIKI_DIR"] = str(wiki_dir)
    try:
        import config
        config.reset_config()
        from compile_v2 import compile_path

        print(f"  Compiling {len(source_to_doc)} source files via compile_v2...", file=sys.stderr)
        t0 = time.time()
        result = compile_path(str(source_dir), source_type="doc")
        elapsed = time.time() - t0
        print(
            f"  Compile complete: {result.get('pages_created', 0)} created, "
            f"{result.get('pages_updated', 0)} updated in {elapsed:.1f}s",
            file=sys.stderr,
        )
    finally:
        if old_wiki_dir is not None:
            os.environ["LLM_WIKI_DIR"] = old_wiki_dir
        else:
            os.environ.pop("LLM_WIKI_DIR", None)
        config.reset_config()

    # Step 3: Build page → BEIR doc mapping
    page_to_doc = _build_beir_page_map(wiki_dir, source_to_doc)
    print(f"  Built page→doc mapping: {len(page_to_doc)} wiki pages → {len(set(page_to_doc.values()))} BEIR docs", file=sys.stderr)

    # Persist cache
    page_map_path.write_text(json.dumps(page_to_doc, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(expected_manifest, ensure_ascii=False), encoding="utf-8")

    return wiki_dir, page_to_doc


def _write_beir_wiki_legacy(
    dataset_key: str, corpus: dict[str, dict[str, str]]
) -> tuple[Path, dict[str, str]]:
    """Legacy fast path: write BEIR corpus as wiki pages directly (no LLM compile).

    Used when --no-compile is specified. Each doc becomes one wiki page
    with basic YAML frontmatter.
    """
    root = BEIR_WIKI_CACHE_DIR / dataset_key
    wiki_dir = root / ".wiki"
    papers_dir = wiki_dir / "pages" / "papers"
    graph_dir = wiki_dir / "graph"
    manifest_path = root / "manifest.json"

    expected_manifest = {
        "dataset_key": dataset_key,
        "corpus_size": len(corpus),
        "format": "llm-wiki-beir-v1-legacy",
    }
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest == expected_manifest and (root / "doc_id_map.json").exists():
                mapping = json.loads((root / "doc_id_map.json").read_text(encoding="utf-8"))
                return wiki_dir, {str(k): str(v) for k, v in mapping.items()}
        except (json.JSONDecodeError, OSError):
            pass

    if root.exists():
        shutil.rmtree(root)
    papers_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ("concepts", "entities", "models", "techniques", "frameworks",
                   "benchmarks", "decisions", "sessions", "patterns"):
        (wiki_dir / "pages" / subdir).mkdir(parents=True, exist_ok=True)

    slug_to_doc_id: dict[str, str] = {}
    entities: dict[str, dict[str, Any]] = {}
    for doc_id, doc in corpus.items():
        slug = _doc_slug(str(doc_id))
        slug_to_doc_id[slug] = str(doc_id)
        title = doc.get("title") or str(doc_id)
        text = doc.get("text", "")
        page = "\n".join([
            "---",
            f"id: {_yaml_string(slug)}",
            "type: paper",
            f"name: {_yaml_string(title)}",
            f"source_id: {_yaml_string(doc_id)}",
            "---",
            "",
            f"# {title}",
            "",
            text,
            "",
        ])
        (papers_dir / f"{slug}.md").write_text(page, encoding="utf-8")
        entities[slug] = {
            "id": slug,
            "type": "paper",
            "name": title,
            "source_id": str(doc_id),
            "confidence": 1.0,
            "page": f"pages/papers/{slug}.md",
        }

    (graph_dir / "entities.json").write_text(json.dumps(entities, ensure_ascii=False), encoding="utf-8")
    (graph_dir / "edges.json").write_text('{"edges": []}', encoding="utf-8")
    (root / "doc_id_map.json").write_text(json.dumps(slug_to_doc_id, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(expected_manifest, ensure_ascii=False), encoding="utf-8")
    return wiki_dir, slug_to_doc_id


def _load_compiled_wiki_cache(path: Path) -> tuple[Path, dict[str, str], dict[str, Any]]:
    """Load an existing compiled llm-wiki cache without rebuilding it."""
    wiki_dir = path if path.name == ".wiki" else path / ".wiki"
    root = wiki_dir.parent
    page_map_path = root / "page_to_doc_map.json"
    manifest_path = root / "manifest.json"

    if not wiki_dir.exists():
        raise FileNotFoundError(f"compiled wiki directory not found: {wiki_dir}")
    if not page_map_path.exists():
        raise FileNotFoundError(f"compiled page map not found: {page_map_path}")

    mapping = json.loads(page_map_path.read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return wiki_dir, {str(k): str(v) for k, v in mapping.items()}, manifest


def _filter_qrels_to_docs(
    qrels: dict[str, dict[str, int]],
    allowed_doc_ids: set[str],
) -> dict[str, dict[str, int]]:
    """Keep only qrels that can be answered by the evaluated document subset."""
    filtered: dict[str, dict[str, int]] = {}
    for qid, scores in qrels.items():
        kept = {doc_id: score for doc_id, score in scores.items() if doc_id in allowed_doc_ids}
        if kept:
            filtered[qid] = kept
    return filtered


# ═══════════════════════════════════════════════════════════════════════
# Retrievers
# ═══════════════════════════════════════════════════════════════════════

class BM25Retriever:
    """BM25 retriever matching search.py implementation."""

    def __init__(self, corpus: dict[str, dict[str, str]], k1: float = 1.5, b: float = 0.75):
        self.corpus = corpus
        self.doc_ids = list(corpus.keys())
        self.k1 = k1
        self.b = b
        self.index: dict[str, dict] = {}
        self.doc_freq: Counter = Counter()
        self._build_index()

    def _doc_text(self, doc: dict[str, str]) -> str:
        title = doc.get("title", "")
        text = doc.get("text", "")
        return f"{title}\n{text}" if title else text

    def _build_index(self) -> None:
        total_length = 0
        for doc_id in self.doc_ids:
            doc = self.corpus[doc_id]
            tokens = [_stem(t) for t in _tokenize(self._doc_text(doc))]
            if not tokens:
                continue
            freqs = Counter(tokens)
            self.index[doc_id] = {
                "tokens": tokens,
                "freqs": freqs,
                "length": len(tokens),
            }
            total_length += len(tokens)
            self.doc_freq.update(set(freqs.keys()))

        self.avg_dl = total_length / len(self.index) if self.index else 1

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        query_terms = [_stem(t) for t in _tokenize(query)]
        if not query_terms or not self.index:
            return []

        num_docs = len(self.index)
        scores: list[tuple[str, float]] = []

        for doc_id, idx in self.index.items():
            score = 0.0
            dl = idx["length"]
            for term in query_terms:
                f = idx["freqs"].get(term, 0)
                if f == 0:
                    continue
                df = self.doc_freq.get(term, 0)
                idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg_dl))
            if score > 0:
                scores.append((doc_id, score))

        scores.sort(key=lambda x: -x[1])
        return scores[:limit]


def _get_embeddings_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Generate embeddings for a batch of texts using the configured provider."""
    from generate_embeddings import get_embeddings_config
    cfg = get_embeddings_config()
    mode = cfg.get("mode", "local")

    if mode == "api":
        return _get_embeddings_batch_api(texts, cfg)
    else:
        return _get_embeddings_batch_local(texts, cfg)


def _get_embeddings_batch_api(texts: list[str], config: dict) -> list[Optional[list[float]]]:
    """Batch API embedding (OpenAI-compatible)."""
    import requests

    api_url = config.get("api_url", "")
    api_key = config.get("api_key", "")
    api_model = config.get("api_model") or config.get("model") or "text-embedding-3-small"

    if not api_url:
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
            resp = requests.post(api_url, headers=headers, json={"model": api_model, "input": texts}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("data", [])
        # Sort by index to maintain order
        embeddings.sort(key=lambda x: x.get("index", 0))
        return [e.get("embedding") for e in embeddings]
    except Exception as e:
        print(f"  Batch embedding error: {e}", file=sys.stderr)
        # Fall back to single requests
        from generate_embeddings import get_embedding
        return [get_embedding(t) for t in texts]


def _get_embeddings_batch_local(texts: list[str], config: dict) -> list[Optional[list[float]]]:
    """Batch local embedding using SentenceTransformer (much faster than per-text)."""
    try:
        from generate_embeddings import _load_local_model
        model_name = config.get("model", "Qwen/Qwen3-Embedding-8B")
        model = _load_local_model(model_name, config)
        batch_size = int(config.get("batch_size", 16))
        embeddings = model.encode(
            texts,
            show_progress_bar=False,
            batch_size=batch_size,
        )
        return [emb.tolist() if hasattr(emb, 'tolist') else list(emb) for emb in embeddings]
    except ImportError:
        from generate_embeddings import get_embedding
        return [get_embedding(t) for t in texts]


class DenseRetriever:
    """Semantic retriever using the project's configured embedding model.

    For BEIR text-only benchmarks, defaults to local mode with
    all-MiniLM-L6-v2 for optimal text retrieval. Pass embedding_mode
    and embedding_model to override.
    """

    def __init__(
        self,
        corpus: dict[str, dict[str, str]],
        embedding_mode: str | None = None,
        embedding_model: str | None = DEFAULT_BENCHMARK_EMBEDDING_MODEL,
    ):
        self.corpus = corpus
        self.doc_ids = list(corpus.keys())
        self.embeddings: dict[str, list[float]] = {}
        self.embedding_mode = embedding_mode
        self.embedding_model = embedding_model
        self._model: Any = None  # cached SentenceTransformer
        self._model_config: dict = {}  # cached embedding config for loading

    def _get_model(self):
        """Lazy-load and cache the embedding model with config-aware loading."""
        if self._model is None:
            from generate_embeddings import get_embeddings_config, _load_local_model

            cfg = get_embeddings_config()
            if self.embedding_model:
                cfg = dict(cfg)
                cfg["model"] = self.embedding_model
            model_name = self.embedding_model or cfg.get("model", "Qwen/Qwen3-Embedding-8B")
            self._model = _load_local_model(model_name, cfg)
            self._model_config = cfg
        return self._model

    def _encode_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Encode texts using cached local model."""
        try:
            model = self._get_model()
            batch_size = int(self._model_config.get("batch_size", 16))
            embeddings = model.encode(
                texts,
                show_progress_bar=False,
                batch_size=batch_size,
            )
            return [emb.tolist() if hasattr(emb, 'tolist') else list(emb) for emb in embeddings]
        except Exception as e:
            print(f"  Local embedding error: {e}", file=sys.stderr)
            return [None] * len(texts)

    def _doc_text(self, doc: dict[str, str]) -> str:
        title = doc.get("title", "")
        text = doc.get("text", "")
        return f"{title}\n{text}" if title else text

    def index_corpus(self, batch_size: int = 32, show_progress: bool = True) -> None:
        """Generate embeddings for all corpus documents using batch API/local."""
        from generate_embeddings import get_embeddings_config

        cfg = get_embeddings_config()
        mode = self.embedding_mode or cfg.get("mode", "local")
        if self.embedding_model:
            cfg = dict(cfg)
            cfg["model"] = self.embedding_model
        model = cfg.get("api_model") if mode == "api" else cfg.get("model", "local")
        print(f"  Embedding mode: {mode}, model: {model}", file=sys.stderr)
        print(f"  Indexing {len(self.doc_ids)} documents (batch_size={batch_size})...", file=sys.stderr)

        total = len(self.doc_ids)
        for i in range(0, total, batch_size):
            batch_ids = self.doc_ids[i:i + batch_size]
            texts = [self._doc_text(self.corpus[did])[:3000] for did in batch_ids]
            if mode == "api" and not self.embedding_model:
                embeddings = _get_embeddings_batch_api(texts, cfg)
            else:
                embeddings = self._encode_batch(texts)
            for doc_id, emb in zip(batch_ids, embeddings):
                if emb:
                    self.embeddings[doc_id] = emb
            if show_progress:
                done = min(i + batch_size, total)
                print(f"    {done}/{total} ({done * 100 // total}%)", file=sys.stderr)

        print(f"  Indexed {len(self.embeddings)}/{total} docs", file=sys.stderr)

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Search with same embedding model as corpus indexing."""
        if self.embedding_model or self.embedding_mode == "local":
            query_embs = self._encode_batch([query])
            query_emb = query_embs[0] if query_embs else None
        else:
            from generate_embeddings import get_embedding
            query_emb = get_embedding(query)

        if not query_emb or not self.embeddings:
            return []

        results: list[tuple[str, float]] = []
        for doc_id, emb in self.embeddings.items():
            if emb:
                sim = _cosine_similarity(query_emb, emb)
                if sim > 0:
                    results.append((doc_id, sim))

        results.sort(key=lambda x: -x[1])
        return results[:limit]


class HybridRetriever:
    """RRF fusion of BM25 and Dense retrievers."""

    def __init__(self, bm25: BM25Retriever, dense: DenseRetriever):
        self.bm25 = bm25
        self.dense = dense

    def search(self, query: str, limit: int = 10, rrf_k: int = 60) -> list[tuple[str, float]]:
        bm25_results = self.bm25.search(query, limit=limit * 2)
        dense_results = self.dense.search(query, limit=limit * 2)

        # RRF fusion
        fused: dict[str, dict] = {}
        for rank, (doc_id, score) in enumerate(bm25_results, 1):
            fused[doc_id] = {"rrf": 1.0 / (rrf_k + rank), "bm25_score": score}
        for rank, (doc_id, score) in enumerate(dense_results, 1):
            if doc_id in fused:
                fused[doc_id]["rrf"] += 1.0 / (rrf_k + rank)
                fused[doc_id]["dense_score"] = score
            else:
                fused[doc_id] = {"rrf": 1.0 / (rrf_k + rank), "dense_score": score}

        sorted_results = sorted(fused.items(), key=lambda x: -x[1]["rrf"])
        return [(doc_id, info["rrf"]) for doc_id, info in sorted_results[:limit]]


class LLMWikiRetriever:
    """BEIR adapter that evaluates the actual llm-wiki pipeline end-to-end.

    Full pipeline (--compile, default):
      BEIR corpus → source files → compile_v2 (LLM entity extraction)
      → generate_embeddings → search_wiki → evaluate

    Fast path (--no-compile):
      BEIR corpus → wiki pages directly → generate_embeddings → search_wiki
    """

    def __init__(
        self,
        dataset_key: str,
        corpus: dict[str, dict[str, str]],
        streams: str,
        embedding_mode: str = "local",
        embedding_model: str | None = DEFAULT_BENCHMARK_EMBEDDING_MODEL,
        use_compile: bool = True,
        force_recompile: bool = False,
        compiled_wiki_dir: Path | None = None,
    ):
        self.streams = streams
        self.embedding_mode = embedding_mode
        self.embedding_model = embedding_model
        self.use_compile = use_compile
        self.compiled_manifest: dict[str, Any] = {}

        if compiled_wiki_dir is not None:
            self.wiki_dir, self.page_to_doc_map, self.compiled_manifest = (
                _load_compiled_wiki_cache(compiled_wiki_dir)
            )
        else:
            self.wiki_dir, self.page_to_doc_map = _ensure_beir_wiki(
                dataset_key, corpus,
                use_compile=use_compile,
                force_recompile=force_recompile,
            )
        self.search_wiki = self._load_search_wiki()

    def _load_search_wiki(self):
        os.environ["LLM_WIKI_DIR"] = str(self.wiki_dir)
        import config

        config.reset_config()
        # search.py and query.py keep WIKI_DIR/PAGES_DIR as module globals.
        # Reloading after LLM_WIKI_DIR is set makes the benchmark use the
        # materialized BEIR wiki instead of the user's current project wiki.
        for module_name in ("search", "query"):
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            else:
                importlib.import_module(module_name)
        return sys.modules["query"].search_wiki

    def build_vector_indexes(self, batch_size: int = 64) -> dict[str, Any]:
        """Build vector indexes required by the configured llm-wiki streams."""
        requested = {stream.strip() for stream in self.streams.split(",") if stream.strip()}
        if not requested.intersection({"vector", "chunk_vector"}):
            return {}

        import config

        os.environ["LLM_WIKI_DIR"] = str(self.wiki_dir)
        os.environ["EMBEDDING_MODE"] = self.embedding_mode
        if self.embedding_model:
            os.environ["EMBEDDING_MODEL"] = self.embedding_model
        if self.embedding_mode == "local":
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        config.reset_config()
        if "generate_embeddings" in sys.modules:
            ge = importlib.reload(sys.modules["generate_embeddings"])
        else:
            ge = importlib.import_module("generate_embeddings")
        if "search" in sys.modules:
            importlib.reload(sys.modules["search"])

        built: dict[str, Any] = {}
        if "vector" in requested:
            t0 = time.time()
            built["pages"] = ge.generate_all(force=False, batch_size=batch_size)
            built["pages"]["time_sec"] = round(time.time() - t0, 1)
            if built["pages"].get("total_embeddings", 0) == 0:
                raise RuntimeError("vector stream requested but page embedding index has zero items")
        if "chunk_vector" in requested:
            t0 = time.time()
            built["chunks"] = ge.generate_chunks(force=False, batch_size=batch_size)
            built["chunks"]["time_sec"] = round(time.time() - t0, 1)
            if built["chunks"].get("total_embeddings", 0) == 0:
                raise RuntimeError("chunk_vector stream requested but chunk embedding index has zero items")
        return built

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Search via the full llm-wiki query pipeline, mapping results to BEIR doc IDs."""
        old_streams = os.environ.get("LLM_WIKI_SEARCH_STREAMS")
        old_embedding_mode = os.environ.get("EMBEDDING_MODE")
        old_embedding_model = os.environ.get("EMBEDDING_MODEL")
        old_hf_offline = os.environ.get("HF_HUB_OFFLINE")
        old_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
        os.environ["LLM_WIKI_SEARCH_STREAMS"] = self.streams
        os.environ["EMBEDDING_MODE"] = self.embedding_mode
        if self.embedding_model:
            os.environ["EMBEDDING_MODEL"] = self.embedding_model
        if self.embedding_mode == "local":
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            results = self.search_wiki(query, limit=limit)
        finally:
            if old_streams is None:
                os.environ.pop("LLM_WIKI_SEARCH_STREAMS", None)
            else:
                os.environ["LLM_WIKI_SEARCH_STREAMS"] = old_streams
            if old_embedding_mode is None:
                os.environ.pop("EMBEDDING_MODE", None)
            else:
                os.environ["EMBEDDING_MODE"] = old_embedding_mode
            if old_embedding_model is None:
                os.environ.pop("EMBEDDING_MODEL", None)
            else:
                os.environ["EMBEDDING_MODEL"] = old_embedding_model
            if old_hf_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = old_hf_offline
            if old_transformers_offline is None:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
            else:
                os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline

        converted: list[tuple[str, float]] = []
        seen_docs: set[str] = set()
        for result in results:
            page_id = result.get("id") or result.get("file") or Path(result.get("path", "")).stem
            # Try page_to_doc_map first (compile mode), fall back to legacy slug match
            doc_id = self.page_to_doc_map.get(str(page_id))
            if doc_id and doc_id not in seen_docs:
                seen_docs.add(doc_id)
                converted.append((doc_id, float(result.get("score", 0.0))))
        return converted[:limit]


# ═══════════════════════════════════════════════════════════════════════
# Metrics (NDCG, Recall, MRR — matching BEIR implementation)
# ═══════════════════════════════════════════════════════════════════════

def _dcg_at_k(scores: list[float], k: int) -> float:
    return sum(score / math.log2(i + 2) for i, score in enumerate(scores[:k]))


def _ndcg_at_k(retrieved: list[str], qrels: dict[str, int], k: int) -> float:
    ideal = sorted(qrels.values(), reverse=True)
    dcg = _dcg_at_k([qrels.get(doc_id, 0) for doc_id in retrieved[:k]], k)
    idcg = _dcg_at_k(ideal, k)
    return dcg / idcg if idcg > 0 else 0.0


def _recall_at_k(retrieved: list[str], qrels: dict[str, int], k: int) -> float:
    if not qrels:
        return 0.0
    hits = sum(1 for doc_id in retrieved[:k] if doc_id in qrels)
    return hits / len(qrels)


def _mrr_at_k(retrieved: list[str], qrels: dict[str, int], k: int) -> float:
    for i, doc_id in enumerate(retrieved[:k], 1):
        if doc_id in qrels:
            return 1.0 / i
    return 0.0


def _precision_at_k(retrieved: list[str], qrels: dict[str, int], k: int) -> float:
    if not retrieved[:k]:
        return 0.0
    return sum(1 for doc_id in retrieved[:k] if doc_id in qrels) / k


def evaluate_retrieval(
    retriever,
    queries: dict[str, str],
    qrels: dict[str, dict[str, int]],
    k_values: list[int] = [1, 5, 10],
    method_name: str = "retrieval",
    show_progress: bool = True,
    max_queries: int | None = None,
    allowed_doc_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Evaluate retriever against BEIR qrels."""
    metrics: dict[str, dict[str, float]] = {f"NDCG@{k}": {} for k in k_values}
    metrics.update({f"Recall@{k}": {} for k in k_values})
    metrics.update({f"MRR@{k}": {} for k in k_values})
    metrics.update({f"Precision@{k}": {} for k in k_values})

    all_ndcg: dict[int, list[float]] = {k: [] for k in k_values}
    all_recall: dict[int, list[float]] = {k: [] for k in k_values}
    all_mrr: dict[int, list[float]] = {k: [] for k in k_values}
    all_precision: dict[int, list[float]] = {k: [] for k in k_values}

    original_qrels_count = len(qrels)
    if allowed_doc_ids is not None:
        qrels = _filter_qrels_to_docs(qrels, allowed_doc_ids)

    eval_queries = {qid: qtext for qid, qtext in queries.items() if qid in qrels}
    if max_queries is not None:
        eval_queries = dict(list(eval_queries.items())[:max_queries])
    total = len(eval_queries)

    for idx, (qid, qtext) in enumerate(eval_queries.items()):
        results = retriever.search(qtext, limit=max(k_values))
        retrieved_ids = [doc_id for doc_id, _ in results]

        for k in k_values:
            all_ndcg[k].append(_ndcg_at_k(retrieved_ids, qrels[qid], k))
            all_recall[k].append(_recall_at_k(retrieved_ids, qrels[qid], k))
            all_mrr[k].append(_mrr_at_k(retrieved_ids, qrels[qid], k))
            all_precision[k].append(_precision_at_k(retrieved_ids, qrels[qid], k))

        if show_progress and (idx + 1) % 100 == 0:
            print(f"    {idx + 1}/{total} queries", file=sys.stderr)

    result = {
        "method": method_name,
        "queries_evaluated": total,
        "qrels_queries_total": original_qrels_count,
    }
    if allowed_doc_ids is not None:
        result["qrels_queries_covered"] = len(qrels)
        result["coverage_mode"] = "compiled-docs-only"
    for k in k_values:
        result[f"NDCG@{k}"] = round(float(np.mean(all_ndcg[k])), 4)
        result[f"Recall@{k}"] = round(float(np.mean(all_recall[k])), 4)
        result[f"MRR@{k}"] = round(float(np.mean(all_mrr[k])), 4)
        result[f"Precision@{k}"] = round(float(np.mean(all_precision[k])), 4)

    return result


# ═══════════════════════════════════════════════════════════════════════
# Main Benchmark Runner
# ═══════════════════════════════════════════════════════════════════════

def run_beir_benchmark(
    dataset_key: str,
    methods: list[str] | None = None,
    k_values: list[int] | None = None,
    llm_wiki_streams: str = "bm25",
    max_queries: int | None = None,
    max_docs: int | None = None,
    embedding_batch_size: int = 64,
    embedding_mode: str = "local",
    embedding_model: str | None = DEFAULT_BENCHMARK_EMBEDDING_MODEL,
    use_compile: bool = True,
    force_recompile: bool = False,
    compiled_wiki_dir: Path | None = None,
) -> dict[str, Any]:
    """Run full BEIR benchmark on one dataset.

    Args:
        use_compile: If True (default), run full compile_v2 pipeline.
                     If False, use legacy fast path (no LLM extraction).
        force_recompile: If True, clear compile cache and re-run.
        max_docs: Limit corpus to first N documents (for quick testing).
    """
    if methods is None:
        methods = ["llm-wiki", "bm25"]
    if k_values is None:
        k_values = [1, 5, 10]
    primary_k = _metric_k(k_values)

    info = BEIR_DATASETS[dataset_key]
    if compiled_wiki_dir is not None:
        pipeline_mode = "compiled-cache → search"
    else:
        pipeline_mode = "compile_v2 → embed → search" if use_compile else "fast (no compile)"
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  BEIR Benchmark: {info['name']}", file=sys.stderr)
    print(f"  Domain: {info['domain']}", file=sys.stderr)
    print(f"  Corpus: {info['corpus_size']:,} docs, Queries: {info['queries']:,}", file=sys.stderr)
    print(f"  Pipeline: {pipeline_mode}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load data
    t0 = time.time()
    corpus, queries, qrels = load_beir(dataset_key)
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s — {len(corpus)} corpus, {len(queries)} queries, {len(qrels)} qrels", file=sys.stderr)

    # Limit corpus if max_docs specified
    if max_docs is not None and max_docs < len(corpus):
        corpus = dict(list(corpus.items())[:max_docs])
        # Filter qrels to only include docs still in corpus
        corpus_ids = set(corpus.keys())
        qrels = {
            qid: {did: score for did, score in doc_scores.items() if did in corpus_ids}
            for qid, doc_scores in qrels.items()
        }
        qrels = {qid: scores for qid, scores in qrels.items() if scores}
        print(f"  Limited to {max_docs} docs, {len(qrels)} qrels with remaining relevant docs", file=sys.stderr)

    if not qrels:
        raise ValueError(
            f"BEIR dataset '{dataset_key}' has no positive qrels loaded; "
            "cannot compute retrieval metrics fairly."
        )

    output: dict[str, Any] = {
        "dataset": info["name"],
        "dataset_key": dataset_key,
        "corpus_size": len(corpus),
        "queries_total": len(queries),
        "queries_evaluated": min(len(qrels), max_queries) if max_queries is not None else len(qrels),
        "qrels_total": len(qrels),
        "load_time_sec": round(load_time, 1),
        "pipeline_mode": pipeline_mode,
        "methods": [],
        "baselines": PUBLISHED_BASELINES.get(dataset_key, {}),
    }

    bm25_retriever: BM25Retriever | None = None
    dense_retriever: DenseRetriever | None = None
    llm_wiki_retriever: LLMWikiRetriever | None = None
    llm_wiki_allowed_docs: set[str] | None = None

    # Real llm-wiki pipeline (compile → embed → search)
    if "llm-wiki" in methods:
        t0 = time.time()
        llm_wiki_retriever = LLMWikiRetriever(
            dataset_key,
            corpus,
            streams=llm_wiki_streams,
            embedding_mode=embedding_mode,
            embedding_model=embedding_model,
            use_compile=use_compile,
            force_recompile=force_recompile,
            compiled_wiki_dir=compiled_wiki_dir,
        )
        compile_time = time.time() - t0
        llm_wiki_allowed_docs = set(llm_wiki_retriever.page_to_doc_map.values())
        covered_qrels = _filter_qrels_to_docs(qrels, llm_wiki_allowed_docs)
        compile_mode = (
            "compiled_cache"
            if compiled_wiki_dir is not None
            else ("compile_v2" if use_compile else "beir_corpus_to_wiki_pages")
        )
        output["llm_wiki_dir"] = str(llm_wiki_retriever.wiki_dir)
        output["llm_wiki_compile"] = {
            "mode": compile_mode,
            "corpus_docs": len(corpus),
            "wiki_pages": len(llm_wiki_retriever.page_to_doc_map),
            "mapped_beir_docs": len(llm_wiki_allowed_docs),
            "qrels_queries_total": len(qrels),
            "qrels_queries_covered": len(covered_qrels),
            "qrels_coverage": round(len(covered_qrels) / len(qrels), 4) if qrels else 0.0,
            "streams": llm_wiki_streams,
            "embedding_mode": embedding_mode,
            "embedding_model": embedding_model or "",
            "compile_time_sec": round(compile_time, 1),
            "manifest": llm_wiki_retriever.compiled_manifest,
        }
        vector_indexes = llm_wiki_retriever.build_vector_indexes(batch_size=embedding_batch_size)
        if vector_indexes:
            output["llm_wiki_vector_indexes"] = vector_indexes
            print(f"  llm-wiki vector indexes: {json.dumps(vector_indexes, ensure_ascii=False)}", file=sys.stderr)
        print(
            f"  llm-wiki compile/materialize built {len(corpus)} docs → "
            f"{len(llm_wiki_retriever.page_to_doc_map)} wiki pages in "
            f"{compile_time:.1f}s at {llm_wiki_retriever.wiki_dir}",
            file=sys.stderr,
        )
        if compiled_wiki_dir is not None:
            print(
                f"  compiled cache coverage: {len(llm_wiki_allowed_docs)} BEIR docs, "
                f"{len(covered_qrels)}/{len(qrels)} qrels queries",
                file=sys.stderr,
            )
        print(f"  llm-wiki search streams: {llm_wiki_streams}", file=sys.stderr)

    # BM25
    if "bm25" in methods or "hybrid" in methods:
        t0 = time.time()
        bm25_retriever = BM25Retriever(corpus)
        index_time = time.time() - t0
        print(f"  BM25 index built in {index_time:.1f}s ({len(bm25_retriever.index)} docs)", file=sys.stderr)

    # Dense
    if "dense" in methods or "hybrid" in methods:
        t0 = time.time()
        # Use config defaults unless overridden
        dense_retriever = DenseRetriever(corpus)
        dense_retriever.index_corpus()
        index_time = time.time() - t0
        print(f"  Dense index built in {index_time:.1f}s", file=sys.stderr)

    # Evaluate BM25
    if "llm-wiki" in methods and llm_wiki_retriever:
        eval_qrels = (
            _filter_qrels_to_docs(qrels, llm_wiki_allowed_docs)
            if compiled_wiki_dir is not None and llm_wiki_allowed_docs is not None
            else qrels
        )
        eval_count = min(len(eval_qrels), max_queries) if max_queries is not None else len(eval_qrels)
        print(f"\n  Running llm-wiki pipeline on {eval_count} queries...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_retrieval(
            llm_wiki_retriever,
            queries,
            qrels,
            k_values=k_values,
            method_name="llm-wiki",
            max_queries=max_queries,
            allowed_doc_ids=llm_wiki_allowed_docs if compiled_wiki_dir is not None else None,
        )
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(
            f"  llm-wiki NDCG@{primary_k}={_get_metric(result, 'NDCG', k_values)}, "
            f"Recall@{primary_k}={_get_metric(result, 'Recall', k_values)}, "
            f"MRR@{primary_k}={_get_metric(result, 'MRR', k_values)}",
            file=sys.stderr,
        )

    if "bm25" in methods and bm25_retriever:
        eval_count = min(len(qrels), max_queries) if max_queries is not None else len(qrels)
        print(f"\n  Running BM25 on {eval_count} queries...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_retrieval(
            bm25_retriever,
            queries,
            qrels,
            k_values=k_values,
            method_name="bm25",
            max_queries=max_queries,
        )
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(
            f"  BM25 NDCG@{primary_k}={_get_metric(result, 'NDCG', k_values)}, "
            f"Recall@{primary_k}={_get_metric(result, 'Recall', k_values)}, "
            f"MRR@{primary_k}={_get_metric(result, 'MRR', k_values)}",
            file=sys.stderr,
        )

    # Evaluate Dense
    if "dense" in methods and dense_retriever:
        eval_count = min(len(qrels), max_queries) if max_queries is not None else len(qrels)
        print(f"\n  Running Dense on {eval_count} queries...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_retrieval(
            dense_retriever,
            queries,
            qrels,
            k_values=k_values,
            method_name="dense",
            max_queries=max_queries,
        )
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(
            f"  Dense NDCG@{primary_k}={_get_metric(result, 'NDCG', k_values)}, "
            f"Recall@{primary_k}={_get_metric(result, 'Recall', k_values)}, "
            f"MRR@{primary_k}={_get_metric(result, 'MRR', k_values)}",
            file=sys.stderr,
        )

    # Evaluate Hybrid
    if "hybrid" in methods and bm25_retriever and dense_retriever:
        eval_count = min(len(qrels), max_queries) if max_queries is not None else len(qrels)
        print(f"\n  Running Hybrid (BM25+Dense RRF) on {eval_count} queries...", file=sys.stderr)
        hybrid = HybridRetriever(bm25_retriever, dense_retriever)
        t0 = time.time()
        result = evaluate_retrieval(
            hybrid,
            queries,
            qrels,
            k_values=k_values,
            method_name="hybrid",
            max_queries=max_queries,
        )
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(
            f"  Hybrid NDCG@{primary_k}={_get_metric(result, 'NDCG', k_values)}, "
            f"Recall@{primary_k}={_get_metric(result, 'Recall', k_values)}, "
            f"MRR@{primary_k}={_get_metric(result, 'MRR', k_values)}",
            file=sys.stderr,
        )

    return output


def generate_markdown_report(all_results: list[dict], primary_k: int = 10) -> str:
    """Generate a markdown comparison report."""
    lines = [
        "# BEIR Retrieval Benchmark Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Summary",
        "",
        "The table below compares this system's retrieval performance against",
        "published baselines on standard BEIR datasets.",
        "",
        f"| Dataset | Method | NDCG@{primary_k} | Recall@{primary_k} | MRR@{primary_k} | vs BM25 Baseline | vs SOTA |",
        "|---------|--------|---------|-----------|--------|-----------------|---------|",
    ]

    for result in all_results:
        ds_name = result["dataset"]
        baselines = result.get("baselines", {})
        bm25_base = baselines.get("BM25 (BEIR)", {})
        baseline_metric = f"NDCG@{primary_k}"
        bm25_base_ndcg = bm25_base.get(baseline_metric, 0)
        sota = baselines.get("SOTA (MTEB best)", {})
        sota_ndcg = sota.get(baseline_metric, 0)

        for method in result["methods"]:
            name = method["method"]
            if method.get("coverage_mode") == "compiled-docs-only":
                covered = method.get("qrels_queries_covered", method.get("queries_evaluated", 0))
                total = method.get("qrels_queries_total", 0)
                name = f"{name} (compiled subset {covered}/{total})"
            ndcg = method.get(f"NDCG@{primary_k}", 0)
            recall = method.get(f"Recall@{primary_k}", 0)
            mrr = method.get(f"MRR@{primary_k}", 0)

            vs_bm25 = ""
            subset_only = method.get("coverage_mode") == "compiled-docs-only" and (
                method.get("qrels_queries_covered") != method.get("qrels_queries_total")
            )
            if subset_only:
                vs_bm25 = "n/a (subset)"
            elif bm25_base_ndcg > 0 and name != "bm25":
                delta = (ndcg - bm25_base_ndcg) / bm25_base_ndcg * 100
                vs_bm25 = f"{delta:+.1f}%"

            vs_sota = ""
            if subset_only:
                vs_sota = "n/a (subset)"
            elif sota_ndcg > 0:
                delta = (ndcg - sota_ndcg) / sota_ndcg * 100
                vs_sota = f"{delta:+.1f}%"

            lines.append(
                f"| {ds_name} | **{name}** | {ndcg:.4f} | {recall:.4f} | {mrr:.4f} | {vs_bm25} | {vs_sota} |"
            )

        # Add baseline rows for comparison
        for baseline_name, baseline_scores in baselines.items():
            b_ndcg = baseline_scores.get(f"NDCG@{primary_k}", 0)
            b_recall = baseline_scores.get(f"Recall@{primary_k}", 0)
            b_mrr = baseline_scores.get(f"MRR@{primary_k}", 0)
            if not any((b_ndcg, b_recall, b_mrr)):
                continue
            lines.append(
                f"| {ds_name} | _{baseline_name}_ | {b_ndcg:.4f} | {b_recall:.4f} | {b_mrr:.4f} | — | — |"
            )
        lines.append("")  # blank line between datasets

    if primary_k != 10:
        lines.extend([
            "",
            "> Published comparison rows are shown only when matching published metrics exist. "
            "Use `-k 10` for the built-in BEIR/MTEB baseline comparison.",
        ])

    lines.extend([
        "",
        "## Interpretation",
        "",
        f"- **NDCG@{primary_k}**: Normalized Discounted Cumulative Gain — measures ranking quality (higher = better ranking).",
        f"- **Recall@{primary_k}**: Fraction of relevant documents found in top {primary_k} results.",
        f"- **MRR@{primary_k}**: Mean Reciprocal Rank — average position of the first relevant document.",
        "- **llm-wiki**: The project's real `query.search_wiki` pipeline over BEIR corpus converted to wiki pages.",
        "- **BM25 baseline**: Independent pure keyword search (sparse retrieval).",
        "- **Dense-BGE**: Semantic search using BGE embedding models.",
        "- **Hybrid**: BM25 + Dense fused via Reciprocal Rank Fusion.",
        "- **SOTA**: Best published result on MTEB leaderboard for this dataset.",
        "",
        "## Data Sources",
        "",
        "- BEIR paper: Thakur et al., 2021 ([arxiv.org/abs/2104.08663](https://arxiv.org/abs/2104.08663))",
        "- BGE paper: Xiao et al., 2023 ([arxiv.org/abs/2309.07597](https://arxiv.org/abs/2309.07597))",
        "- MTEB Leaderboard: [huggingface.co/spaces/mteb/leaderboard](https://huggingface.co/spaces/mteb/leaderboard)",
        "",
        "## System Configuration",
        "",
        f"- Embedding model: {all_results[0].get('llm_wiki_compile', {}).get('embedding_model', 'n/a') if all_results else 'n/a'}",
        f"- Embedding mode: {all_results[0].get('llm_wiki_compile', {}).get('embedding_mode', 'n/a') if all_results else 'n/a'}",
        f"- llm-wiki streams: {all_results[0].get('llm_wiki_compile', {}).get('streams', 'n/a') if all_results else 'n/a'}",
        f"- BM25: k1=1.5, b=0.75, Porter stemming + jieba for CJK",
        f"- Hybrid: RRF fusion (k=60)",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    global DOWNLOAD_ENABLED

    parser = argparse.ArgumentParser(
        description="BEIR retrieval benchmark with industry baseline comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""Available datasets:
  scifact   — SciFact (5,183 docs, 1,109 queries)
  nfcorpus  — NFCorpus (3,633 docs, 323 queries)
  fiqa      — FiQA-2018 (57,638 docs, 648 queries)

Examples:
  %(prog)s scifact
  %(prog)s --all
  %(prog)s nfcorpus --methods bm25,dense
  %(prog)s --all --report BENCHMARK.md
  %(prog)s --all -o .wiki/benchmark/beir_results.json""",
    )
    parser.add_argument(
        "dataset", nargs="?", choices=list(BEIR_DATASETS.keys()),
        help="BEIR dataset key",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all available BEIR datasets",
    )
    parser.add_argument(
        "--methods", default="llm-wiki,bm25",
        help="Comma-separated methods: llm-wiki,bm25,dense,hybrid (default: llm-wiki,bm25)",
    )
    parser.add_argument(
        "-k", "--top-k", type=int, nargs="+", default=[1, 5, 10],
        help="Evaluation k values (default: 1 5 10)",
    )
    parser.add_argument(
        "--llm-wiki-streams",
        default="bm25",
        help="Retrieval streams for llm-wiki method (default: bm25)",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="Evaluate only the first N qrels queries for quick tuning runs",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=64,
        help="Batch size when llm-wiki vector streams need embeddings",
    )
    parser.add_argument(
        "--embedding-mode",
        choices=["local", "api"],
        default="local",
        help="Embedding mode for llm-wiki vector streams (default: local)",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_BENCHMARK_EMBEDDING_MODEL,
        help=f"Embedding model for llm-wiki vector streams (default: {DEFAULT_BENCHMARK_EMBEDDING_MODEL})",
    )
    parser.add_argument(
        "-o", "--output",
        help="Write JSON results to file",
    )
    parser.add_argument(
        "--report",
        help="Write Markdown report to file",
    )
    parser.add_argument(
        "--no-download", action="store_true",
        help="Skip download (use cached datasets)",
    )
    parser.add_argument(
        "--no-compile", action="store_true",
        help="Skip LLM compile — write BEIR docs as wiki pages directly (fast, but not full pipeline)",
    )
    parser.add_argument(
        "--recompile", action="store_true",
        help="Force re-compile even if cache exists (ignored with --no-compile)",
    )
    parser.add_argument(
        "--compiled-wiki-dir",
        type=Path,
        default=None,
        help="Evaluate an existing compiled .wiki cache directly without compiling or rewriting it",
    )
    parser.add_argument(
        "--max-docs", type=int, default=None,
        help="Limit corpus to first N documents (for quick testing)",
    )

    args = parser.parse_args()
    DOWNLOAD_ENABLED = not args.no_download

    if not args.dataset and not args.all:
        parser.print_help()
        sys.exit(1)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    valid_methods = {"llm-wiki", "bm25", "dense", "hybrid"}
    unknown_methods = sorted(set(methods) - valid_methods)
    if unknown_methods:
        parser.error(f"unknown method(s): {', '.join(unknown_methods)}")
    primary_k = _metric_k(args.top_k)

    if args.all:
        dataset_keys = list(BEIR_DATASETS.keys())
    else:
        dataset_keys = [args.dataset]

    all_results = []
    failures = 0
    for dk in dataset_keys:
        try:
            result = run_beir_benchmark(
                dk,
                methods=methods,
                k_values=args.top_k,
                llm_wiki_streams=args.llm_wiki_streams,
                max_queries=args.max_queries,
                max_docs=args.max_docs,
                embedding_batch_size=args.embedding_batch_size,
                embedding_mode=args.embedding_mode,
                embedding_model=args.embedding_model,
                use_compile=not args.no_compile,
                force_recompile=args.recompile,
                compiled_wiki_dir=args.compiled_wiki_dir,
            )
            all_results.append(result)
        except Exception as e:
            failures += 1
            print(f"ERROR on {dk}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    # Print summary
    print("\n" + "=" * 60)
    print("  BEIR BENCHMARK SUMMARY")
    print("=" * 60)
    for result in all_results:
        method_query_counts = [
            method.get("queries_evaluated")
            for method in result.get("methods", [])
            if method.get("queries_evaluated") is not None
        ]
        shown_queries = max(method_query_counts) if method_query_counts else result["queries_evaluated"]
        print(f"\n  {result['dataset']} ({shown_queries} evaluated queries):")
        for method in result["methods"]:
            print(
                f"    {method['method']:8s}  "
                f"NDCG@{primary_k}={method.get(f'NDCG@{primary_k}', 0):.4f}  "
                f"Recall@{primary_k}={method.get(f'Recall@{primary_k}', 0):.4f}  "
                f"MRR@{primary_k}={method.get(f'MRR@{primary_k}', 0):.4f}"
            )

    # Output JSON
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON results → {out_path}", file=sys.stderr)

    # Generate Markdown report
    if args.report:
        report = generate_markdown_report(all_results, primary_k=primary_k)
        report_path = Path(args.report)
        report_path.write_text(report, encoding="utf-8")
        print(f"Markdown report → {report_path}", file=sys.stderr)
    else:
        # Always print the report to stdout
        print(generate_markdown_report(all_results, primary_k=primary_k))

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
