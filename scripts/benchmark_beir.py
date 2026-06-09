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
import json
import math
import os
import re
import sys
import time
import urllib.request
import zipfile
import io
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


def download_beir(dataset_key: str) -> Path:
    """Download a BEIR dataset zip and extract to evals/beir/<key>/."""
    info = BEIR_DATASETS[dataset_key]
    target_dir = BEIR_CACHE_DIR / dataset_key
    if target_dir.exists() and (target_dir / "corpus.jsonl").exists():
        return target_dir

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
        from sentence_transformers import SentenceTransformer
        model_name = config.get("model", "sentence-transformers/all-MiniLM-L6-v2")
        model = SentenceTransformer(model_name)
        embeddings = model.encode(texts, show_progress_bar=False)
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
        embedding_model: str | None = None,
    ):
        self.corpus = corpus
        self.doc_ids = list(corpus.keys())
        self.embeddings: dict[str, list[float]] = {}
        self.embedding_mode = embedding_mode
        self.embedding_model = embedding_model
        self._model: Any = None  # cached SentenceTransformer

    def _get_model(self):
        """Lazy-load and cache the embedding model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            model_name = self.embedding_model or "sentence-transformers/all-MiniLM-L6-v2"
            self._model = SentenceTransformer(model_name)
        return self._model

    def _encode_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Encode texts using cached local model."""
        try:
            model = self._get_model()
            embeddings = model.encode(texts, show_progress_bar=False)
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

    eval_queries = {qid: qtext for qid, qtext in queries.items() if qid in qrels}
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

    result = {"method": method_name}
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
) -> dict[str, Any]:
    """Run full BEIR benchmark on one dataset."""
    if methods is None:
        methods = ["bm25", "dense", "hybrid"]
    if k_values is None:
        k_values = [1, 5, 10]

    info = BEIR_DATASETS[dataset_key]
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  BEIR Benchmark: {info['name']}", file=sys.stderr)
    print(f"  Domain: {info['domain']}", file=sys.stderr)
    print(f"  Corpus: {info['corpus_size']:,} docs, Queries: {info['queries']:,}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load data
    t0 = time.time()
    corpus, queries, qrels = load_beir(dataset_key)
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s — {len(corpus)} corpus, {len(queries)} queries, {len(qrels)} qrels", file=sys.stderr)

    output: dict[str, Any] = {
        "dataset": info["name"],
        "dataset_key": dataset_key,
        "corpus_size": len(corpus),
        "queries_total": len(queries),
        "queries_evaluated": len(qrels),
        "load_time_sec": round(load_time, 1),
        "methods": [],
        "baselines": PUBLISHED_BASELINES.get(dataset_key, {}),
    }

    bm25_retriever: BM25Retriever | None = None
    dense_retriever: DenseRetriever | None = None

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
    if "bm25" in methods and bm25_retriever:
        print(f"\n  Running BM25 on {len(qrels)} queries...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_retrieval(bm25_retriever, queries, qrels, k_values=k_values, method_name="bm25")
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(f"  BM25 NDCG@10={result['NDCG@10']}, Recall@10={result['Recall@10']}, MRR@10={result['MRR@10']}", file=sys.stderr)

    # Evaluate Dense
    if "dense" in methods and dense_retriever:
        print(f"\n  Running Dense on {len(qrels)} queries...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_retrieval(dense_retriever, queries, qrels, k_values=k_values, method_name="dense")
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(f"  Dense NDCG@10={result['NDCG@10']}, Recall@10={result['Recall@10']}, MRR@10={result['MRR@10']}", file=sys.stderr)

    # Evaluate Hybrid
    if "hybrid" in methods and bm25_retriever and dense_retriever:
        print(f"\n  Running Hybrid (BM25+Dense RRF) on {len(qrels)} queries...", file=sys.stderr)
        hybrid = HybridRetriever(bm25_retriever, dense_retriever)
        t0 = time.time()
        result = evaluate_retrieval(hybrid, queries, qrels, k_values=k_values, method_name="hybrid")
        result["eval_time_sec"] = round(time.time() - t0, 1)
        output["methods"].append(result)
        print(f"  Hybrid NDCG@10={result['NDCG@10']}, Recall@10={result['Recall@10']}, MRR@10={result['MRR@10']}", file=sys.stderr)

    return output


def generate_markdown_report(all_results: list[dict]) -> str:
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
        "| Dataset | Method | NDCG@10 | Recall@10 | MRR@10 | vs BM25 Baseline | vs SOTA |",
        "|---------|--------|---------|-----------|--------|-----------------|---------|",
    ]

    for result in all_results:
        ds_name = result["dataset"]
        baselines = result.get("baselines", {})
        bm25_base = baselines.get("BM25 (BEIR)", {})
        bm25_base_ndcg = bm25_base.get("NDCG@10", 0)
        sota = baselines.get("SOTA (MTEB best)", {})
        sota_ndcg = sota.get("NDCG@10", 0)

        for method in result["methods"]:
            name = method["method"]
            ndcg = method.get("NDCG@10", 0)
            recall = method.get("Recall@10", 0)
            mrr = method.get("MRR@10", 0)

            vs_bm25 = ""
            if bm25_base_ndcg > 0 and name != "bm25":
                delta = (ndcg - bm25_base_ndcg) / bm25_base_ndcg * 100
                vs_bm25 = f"{delta:+.1f}%"

            vs_sota = ""
            if sota_ndcg > 0:
                delta = (ndcg - sota_ndcg) / sota_ndcg * 100
                vs_sota = f"{delta:+.1f}%"

            lines.append(
                f"| {ds_name} | **{name}** | {ndcg:.4f} | {recall:.4f} | {mrr:.4f} | {vs_bm25} | {vs_sota} |"
            )

        # Add baseline rows for comparison
        for baseline_name, baseline_scores in baselines.items():
            b_ndcg = baseline_scores.get("NDCG@10", 0)
            b_recall = baseline_scores.get("Recall@10", 0)
            b_mrr = baseline_scores.get("MRR@10", 0)
            lines.append(
                f"| {ds_name} | _{baseline_name}_ | {b_ndcg:.4f} | {b_recall:.4f} | {b_mrr:.4f} | — | — |"
            )
        lines.append("")  # blank line between datasets

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- **NDCG@10**: Normalized Discounted Cumulative Gain — measures ranking quality (higher = better ranking).",
        "- **Recall@10**: Fraction of relevant documents found in top 10 results.",
        "- **MRR@10**: Mean Reciprocal Rank — average position of the first relevant document.",
        "- **BM25 baseline**: Pure keyword search (sparse retrieval).",
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
        f"- Embedding model: configured via `wiki_config.yaml` (embeddings section)",
        f"- BM25: k1=1.5, b=0.75, Porter stemming + jieba for CJK",
        f"- Hybrid: RRF fusion (k=60)",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
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
        "--methods", default="bm25,dense,hybrid",
        help="Comma-separated methods: bm25,dense,hybrid (default: all)",
    )
    parser.add_argument(
        "-k", "--top-k", type=int, nargs="+", default=[1, 5, 10],
        help="Evaluation k values (default: 1 5 10)",
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

    args = parser.parse_args()

    if not args.dataset and not args.all:
        parser.print_help()
        sys.exit(1)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]

    if args.all:
        dataset_keys = list(BEIR_DATASETS.keys())
    else:
        dataset_keys = [args.dataset]

    all_results = []
    for dk in dataset_keys:
        try:
            result = run_beir_benchmark(dk, methods=methods, k_values=args.top_k)
            all_results.append(result)
        except Exception as e:
            print(f"ERROR on {dk}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    # Print summary
    print("\n" + "=" * 60)
    print("  BEIR BENCHMARK SUMMARY")
    print("=" * 60)
    for result in all_results:
        print(f"\n  {result['dataset']} ({result['queries_evaluated']} queries):")
        for method in result["methods"]:
            print(f"    {method['method']:8s}  NDCG@10={method.get('NDCG@10', 0):.4f}  "
                  f"Recall@10={method.get('Recall@10', 0):.4f}  MRR@10={method.get('MRR@10', 0):.4f}")

    # Output JSON
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON results → {out_path}", file=sys.stderr)

    # Generate Markdown report
    if args.report:
        report = generate_markdown_report(all_results)
        report_path = Path(args.report)
        report_path.write_text(report, encoding="utf-8")
        print(f"Markdown report → {report_path}", file=sys.stderr)
    else:
        # Always print the report to stdout
        print(generate_markdown_report(all_results))


if __name__ == "__main__":
    main()
