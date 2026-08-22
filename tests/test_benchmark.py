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
    cases = [
        {
            "query": "q",
            "expected_pages": ["page-b"],
            "forbidden_pages": ["page-z"],
            "scenario": "exact",
        }
    ]

    result = benchmark.run_retrieval_benchmark(cases, k=2)

    assert result["metrics"]["hit_rate_at_k"] == 1.0
    assert result["metrics"]["recall_at_k"] == 1.0
    assert result["metrics"]["mrr_at_k"] == 0.5
    assert result["metrics"]["complete_recall_rate"] == 1.0
    assert result["metrics"]["forbidden_leakage_rate"] == 0.0
    assert result["metrics"]["latency_p95_ms"] >= 0
    assert result["scenario_metrics"]["exact"]["hit_rate"] == 1.0


def test_multihop_benchmark_measures_subgoal_coverage_and_drift(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "multi_hop_search",
        lambda query, limit=5, **_kwargs: [
            {"id": "alpha", "path": "a", "score": 1.0, "retrieval_hop": 1},
            {"id": "beta", "path": "b", "score": 0.8, "retrieval_hop": 2},
            {"id": "off-topic", "path": "c", "score": 0.2, "retrieval_hop": 2},
        ],
    )
    cases = [
        {
            "query": "compare alpha and beta",
            "multi_hop": True,
            "expected_pages": ["alpha", "beta"],
            "expected_groups": [["alpha"], ["beta"]],
            "strict_relevant_pages": ["alpha", "beta"],
            "scenario": "multi_hop",
        }
    ]

    result = benchmark.run_retrieval_benchmark(cases, k=3)

    assert result["metrics"]["subgoal_coverage"] == 1.0
    assert result["metrics"]["complete_subgoal_coverage_rate"] == 1.0
    assert result["metrics"]["topic_drift_rate"] == 0.3333
    assert result["details"][0]["retrieval_hops"] == 2


def test_ragas_lite_metrics(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "search_wiki",
        lambda query, limit=5: [
            {"id": "page-a", "path": "x", "text": "Budget threshold is 10000."}
        ],
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
