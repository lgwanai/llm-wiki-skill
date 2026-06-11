"""Tests for benchmark.py and search.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.benchmark as benchmark
import scripts.search as search


def test_retrieval_metrics_hit(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "search_wiki",
        lambda query, limit=5: [
            {"id": "page-a", "path": "x", "score": 1.0},
            {"id": "page-b", "path": "y", "score": 0.5},
        ],
    )
    cases = [{"query": "q", "expected_pages": ["page-b"]}]

    result = benchmark.run_retrieval_benchmark(cases, k=2)

    assert result["metrics"]["hit_rate_at_k"] == 1.0
    assert result["metrics"]["recall_at_k"] == 1.0
    assert result["metrics"]["mrr_at_k"] == 0.5


def test_ragas_lite_metrics(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "search_wiki",
        lambda query, limit=5: [{"id": "page-a", "path": "x", "text": "Budget threshold is 10000."}],
    )
    monkeypatch.setattr(
        benchmark,
        "read_page_content",
        lambda path: "Budget threshold is 10000.",
    )
    cases = [{
        "query": "budget threshold",
        "expected_pages": ["page-a"],
        "reference_answer": "Budget threshold is 10000.",
        "must_contain": ["10000"],
    }]

    result = benchmark.run_ragas_lite_benchmark(cases, k=1)

    assert result["metrics"]["context_precision"] == 1.0
    assert result["metrics"]["context_recall"] == 1.0
    assert result["metrics"]["faithfulness"] == 1.0
    assert result["details"][0]["must_contain_coverage"] == 1.0


def test_rrf_preserves_stream_ranks_and_scores():
    fused = search.reciprocal_rank_fusion([
        [{"file": "doc-a", "score": 10, "stream": "bm25"}],
        [
            {"file": "doc-b", "score": 0.9, "stream": "graph"},
            {"file": "doc-a", "score": 0.8, "stream": "graph"},
        ],
    ])

    doc_a = next(item for item in fused if item["file"] == "doc-a")
    assert doc_a["stream_ranks"]["bm25"] == 1
    assert doc_a["stream_ranks"]["graph"] == 2
    assert doc_a["stream_scores"]["bm25"] == 10
