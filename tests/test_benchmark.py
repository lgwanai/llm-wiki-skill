"""Tests for benchmark.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.benchmark as benchmark
import scripts.benchmark_beir as benchmark_beir
import scripts.benchmark_matrix as benchmark_matrix
import scripts.benchmark_multidim as benchmark_multidim
import scripts.benchmark_private_kb as benchmark_private_kb
import scripts.generate_embeddings as generate_embeddings
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


def test_beir_bm25_supports_top_k_without_10(monkeypatch):
    monkeypatch.setitem(
        benchmark_beir.BEIR_DATASETS,
        "tiny",
        {"name": "Tiny", "corpus_size": 2, "queries": 1, "domain": "test"},
    )
    monkeypatch.setattr(
        benchmark_beir,
        "load_beir",
        lambda dataset_key: (
            {
                "doc-a": {"title": "Budget", "text": "Budget threshold is 10000."},
                "doc-b": {"title": "Schedule", "text": "The launch happens Friday."},
            },
            {"q1": "budget threshold"},
            {"q1": {"doc-a": 1}},
        ),
    )

    result = benchmark_beir.run_beir_benchmark("tiny", methods=["bm25"], k_values=[1, 5])

    method = result["methods"][0]
    assert method["method"] == "bm25"
    assert "NDCG@1" in method
    assert "NDCG@5" in method
    assert "NDCG@10" not in method


def test_beir_report_uses_primary_k():
    report = benchmark_beir.generate_markdown_report(
        [{
            "dataset": "Tiny",
            "baselines": {},
            "methods": [{"method": "bm25", "NDCG@5": 1.0, "Recall@5": 1.0, "MRR@5": 1.0}],
        }],
        primary_k=5,
    )

    assert "NDCG@5" in report
    assert "Recall@5" in report
    assert "llm-wiki" in report


def test_beir_evaluation_filters_to_compiled_docs():
    class DummyRetriever:
        def search(self, query, limit=10):
            return [("doc-a", 1.0), ("doc-b", 0.5)]

    result = benchmark_beir.evaluate_retrieval(
        DummyRetriever(),
        {
            "q1": "covered query",
            "q2": "uncovered query",
        },
        {
            "q1": {"doc-a": 1},
            "q2": {"doc-z": 1},
        },
        k_values=[1],
        allowed_doc_ids={"doc-a"},
        show_progress=False,
    )

    assert result["queries_evaluated"] == 1
    assert result["qrels_queries_total"] == 2
    assert result["qrels_queries_covered"] == 1
    assert result["coverage_mode"] == "compiled-docs-only"
    assert result["NDCG@1"] == 1.0


def test_beir_benchmark_rejects_empty_qrels(monkeypatch):
    monkeypatch.setitem(
        benchmark_beir.BEIR_DATASETS,
        "emptyqrels",
        {"name": "Empty", "corpus_size": 1, "queries": 1, "domain": "test"},
    )
    monkeypatch.setattr(
        benchmark_beir,
        "load_beir",
        lambda dataset_key: (
            {"doc-a": {"title": "A", "text": "alpha"}},
            {"q1": "alpha"},
            {},
        ),
    )

    import pytest

    with pytest.raises(ValueError, match="no positive qrels"):
        benchmark_beir.run_beir_benchmark("emptyqrels", methods=["bm25"])


def test_llm_wiki_retriever_uses_real_query_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_beir, "BEIR_WIKI_CACHE_DIR", tmp_path)
    corpus = {
        "doc-a": {"title": "Budget", "text": "Budget threshold is 10000."},
        "doc-b": {"title": "Schedule", "text": "The launch happens Friday."},
    }

    retriever = benchmark_beir.LLMWikiRetriever(
        "tiny", corpus, streams="metadata,chunk,bm25", use_compile=False,
    )
    results = retriever.search("budget threshold", limit=2)

    assert results
    assert results[0][0] == "doc-a"


def test_embedding_model_override_drops_stale_dimension(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODE", "local")
    monkeypatch.setenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setattr(
        generate_embeddings,
        "get_config",
        lambda: {
            "embeddings": {
                "mode": "api",
                "model": "sentence-transformers/Qwen3-Embedding-4B-4bit-DWQ",
                "dimension": 2560,
                "backend": "faiss",
            }
        },
    )

    config = generate_embeddings.get_embeddings_config()

    assert config["mode"] == "local"
    assert config["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert "dimension" not in config


def test_rrf_preserves_stream_ranks_and_scores():
    fused = search.reciprocal_rank_fusion([
        [{"file": "doc-a", "score": 10, "stream": "bm25"}],
        [
            {"file": "doc-b", "score": 0.9, "stream": "vector"},
            {"file": "doc-a", "score": 0.8, "stream": "vector"},
        ],
    ])

    doc_a = next(item for item in fused if item["file"] == "doc-a")
    assert doc_a["stream_ranks"]["bm25"] == 1
    assert doc_a["stream_ranks"]["vector"] == 2
    assert doc_a["stream_scores"]["bm25"] == 10


def test_multidim_index_health_reads_meta_schema(tmp_path):
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages" / "concepts"
    graph = wiki / "graph"
    pages.mkdir(parents=True)
    graph.mkdir(parents=True)
    (pages / "alpha.md").write_text("---\nid: alpha\ntype: concept\n---\n# Alpha\n")
    (graph / "embeddings.json").write_text(
        '{"_meta":{"model":"Qwen/Qwen3-Embedding-8B","dimension":4096,"mode":"local"},"items":{"alpha":{"embedding":[1,0]}}}'
    )

    health = benchmark_multidim.index_health(wiki)

    assert health["page_embedding"]["items"] == 1
    assert health["page_embedding"]["model"] == "Qwen/Qwen3-Embedding-8B"
    assert health["page_embedding"]["dimension"] == 4096


def test_multidim_original_bm25_uses_full_candidate_set():
    corpus = {
        "doc-a": {"title": "Budget", "text": "Budget threshold is 10000."},
        "doc-b": {"title": "Schedule", "text": "Budget appears here, but the answer is elsewhere."},
    }
    queries = {"q1": "budget threshold"}
    qrels = {"q1": {"doc-a": 1}}

    result = benchmark_multidim.run_original_bm25_subset(
        corpus,
        queries,
        qrels,
        candidate_doc_ids={"doc-a", "doc-b"},
    )

    assert result["candidate_docs"] == 2


def test_benchmark_matrix_private_status_detects_missing(tmp_path):
    status = benchmark_matrix.private_scenario_status(tmp_path)

    assert set(status) >= {"long_document", "table", "chinese"}
    assert status["long_document"]["ready"] is False


def test_private_kb_benchmark_runs_real_search(tmp_path, monkeypatch):
    wiki_dir = tmp_path / "private_kb" / ".wiki"
    benchmark_private_kb.build_private_wiki(wiki_dir, force=True)

    result = benchmark_private_kb.evaluate_private_kb(
        wiki_dir,
        streams="metadata,chunk,bm25",
        k=5,
    )

    assert result["cases"] == len(benchmark_private_kb.PRIVATE_CASES)
    assert result["by_scenario"]["long_document"]["hit_at_k"] == 1.0
    assert result["by_scenario"]["table"]["hit_at_k"] == 1.0
    assert "permission_filter" in result["by_scenario"]


def test_benchmark_matrix_reads_private_kb_metrics(tmp_path):
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "private_kb_benchmark.json").write_text(
        json.dumps({
            "by_scenario": {
                "long_document": {"hit_at_k": 1.0, "mrr_at_k": 1.0, "permission_leak_rate": 0.0}
            }
        })
    )

    status = benchmark_matrix.private_scenario_status(tmp_path)

    assert status["long_document"]["ready"] is True
    assert status["long_document"]["metrics"]["hit_at_k"] == 1.0
