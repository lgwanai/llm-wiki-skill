"""Tests for search.py — hybrid search and RRF fusion."""

import os
import json
from pathlib import Path

import search


class TestBM25Search:
    def test_returns_results_for_matching_query(self, wiki_dir, sample_entities):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            pages_dir = str(Path(".wiki") / "pages")
            results = search.bm25_search("auth service redis", pages_dir, limit=5)
            assert len(results) >= 0
            for r in results:
                assert "file" in r
                assert "score" in r
                assert r["stream"] == "bm25"
        finally:
            os.chdir(old)

    def test_returns_empty_for_no_match(self, wiki_dir, sample_entities):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            pages_dir = str(Path(".wiki") / "pages")
            results = search.bm25_search("zzzxyznonexistentterm", pages_dir, limit=5)
            assert results == []
        finally:
            os.chdir(old)


class TestGraphSearch:
    def test_finds_entity_by_name(self, wiki_dir, sample_entities):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            results = search.graph_search("auth", str(Path(".wiki") / "graph"), limit=5)
            assert len(results) > 0
        finally:
            os.chdir(old)

    def test_returns_empty_for_no_match(self, wiki_dir, sample_entities):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            results = search.graph_search("zzzxyz", str(Path(".wiki") / "graph"), limit=5)
            assert results == []
        finally:
            os.chdir(old)


class TestReciprocalRankFusion:
    def test_fuses_multiple_streams(self):
        results_a = [
            {"file": "page1.md", "score": 0.9, "stream": "bm25"},
            {"file": "page2.md", "score": 0.5, "stream": "bm25"},
        ]
        results_b = [
            {"file": "page2.md", "score": 0.8, "stream": "graph"},
            {"file": "page3.md", "score": 0.7, "stream": "graph"},
        ]
        fused = search.reciprocal_rank_fusion([results_a, results_b], k=60)
        assert len(fused) == 3
        for item in fused:
            assert "rrf_score" in item
            assert "streams" in item
            assert isinstance(item["streams"], list)

    def test_deduplicates_across_streams(self):
        results_a = [{"file": "same.md", "score": 0.9, "stream": "bm25"}]
        results_b = [{"file": "same.md", "score": 0.8, "stream": "vector"}]
        fused = search.reciprocal_rank_fusion([results_a, results_b])
        assert len(fused) == 1
        assert len(fused[0]["streams"]) == 2

    def test_higher_rank_gets_higher_score(self):
        results = [[
            {"file": "top.md", "score": 1.0, "stream": "bm25"},
            {"file": "mid.md", "score": 0.5, "stream": "bm25"},
        ]]
        fused = search.reciprocal_rank_fusion(results)
        first = fused[0]
        assert first["rrf_score"] > 0


class TestCosineSimilarity:
    def test_identical_vectors(self):
        sim = search._cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert abs(sim - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        sim = search._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 0.001

    def test_empty_vectors(self):
        sim = search._cosine_similarity([], [])
        assert sim == 0.0


class TestChunkSearch:
    def test_finds_heading_local_chunk(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        page = page_dir / "approval-flow.md"
        page.write_text(
            """---
id: approval-flow
type: concept
---

# Approval Flow

## Budget Threshold

Amount 12000 CNY is compared against threshold 10000.
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "_CHUNK_CACHE_FILE", wiki / "graph" / ".chunk_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)

        results = search.chunk_search("threshold 10000", str(wiki / "pages"), limit=5)

        assert results
        assert results[0]["file"] == "approval-flow"
        assert results[0]["path"] == str(page)
        assert "Budget Threshold" in results[0]["heading_path"]

    def test_search_doctor_reports_embedding_status(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "x.md").write_text("# X\n\nBody", encoding="utf-8")
        (wiki / "graph").mkdir(parents=True)
        (wiki / "graph" / "entities.json").write_text("{}", encoding="utf-8")
        (wiki / "graph" / "edges.json").write_text('{"edges":[]}', encoding="utf-8")
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "_CHUNK_CACHE_FILE", wiki / "graph" / ".chunk_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)

        result = search.search_doctor(wiki)

        assert result["pages"] == 1
        assert result["chunks"] >= 1
        assert "embedding" in result

    def test_eval_retrieval_hits_expected_page(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "approval-flow.md").write_text(
            "# Approval Flow\n\nThreshold 10000 requires director approval.",
            encoding="utf-8",
        )
        (wiki / "graph").mkdir(parents=True)
        eval_file = tmp_path / "retrieval.jsonl"
        eval_file.write_text(
            json.dumps({"query": "threshold 10000", "expected_pages": ["approval-flow"]}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "GRAPH_DIR", wiki / "graph")
        monkeypatch.setattr(search, "_CHUNK_CACHE_FILE", wiki / "graph" / ".chunk_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)

        result = search.eval_retrieval(eval_file, limit=5)

        assert result["status"] == "ok"
        assert result["recall_at_k"] == 1.0


class TestMetadataSearch:
    def test_finds_alias_from_frontmatter(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        page = page_dir / "order-approval-flow.md"
        page.write_text(
            """---
id: order-approval-flow
type: concept
name: Order Approval Flow
summary: Budget approval process with director threshold.
aliases:
  - OAF
  - 订单审批
keywords:
  - budget threshold
questions:
  - When is director approval required?
---

# Order Approval Flow
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "_METADATA_CACHE_FILE", wiki / "graph" / ".metadata_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)

        results = search.metadata_search("OAF", str(wiki / "pages"), limit=5)

        assert results
        assert results[0]["file"] == "order-approval-flow"
        assert results[0]["path"] == str(page)
        assert "OAF" in results[0]["aliases"]

    def test_search_doctor_reports_metadata_items(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "x.md").write_text("---\nid: x\n---\n# X\n\nBody", encoding="utf-8")
        (wiki / "graph").mkdir(parents=True)
        (wiki / "graph" / "entities.json").write_text("{}", encoding="utf-8")
        (wiki / "graph" / "edges.json").write_text('{"edges":[]}', encoding="utf-8")
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "_CHUNK_CACHE_FILE", wiki / "graph" / ".chunk_index.json")
        monkeypatch.setattr(search, "_METADATA_CACHE_FILE", wiki / "graph" / ".metadata_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)

        result = search.search_doctor(wiki)

        assert result["metadata_items"] == 1

    def test_search_doctor_flags_empty_embedding_index(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "x.md").write_text("---\nid: x\n---\n# X\n\nBody", encoding="utf-8")
        graph_dir = wiki / "graph"
        graph_dir.mkdir(parents=True)
        (graph_dir / "entities.json").write_text("{}", encoding="utf-8")
        (graph_dir / "edges.json").write_text('{"edges":[]}', encoding="utf-8")
        (graph_dir / "embeddings.json").write_text(
            json.dumps({
                "_meta": {
                    "schema_version": 2,
                    "mode": "local",
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "dimension": 384,
                },
                "items": {},
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "_CHUNK_CACHE_FILE", graph_dir / ".chunk_index.json")
        monkeypatch.setattr(search, "_METADATA_CACHE_FILE", graph_dir / ".metadata_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)

        result = search.search_doctor(wiki)

        assert result["healthy"] is False
        assert "embedding index has no items" in result["issues"]
        assert result["embedding_coverage_pct"] == 0.0

    def test_vector_chunk_search_uses_chunk_embedding_index(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        graph_dir = wiki / "graph"
        graph_dir.mkdir(parents=True)
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        page = page_dir / "approval-flow.md"
        page.write_text("# Approval Flow\n\nDirector threshold.", encoding="utf-8")
        (graph_dir / "chunk_embeddings.json").write_text(
            json.dumps({
                "_meta": {
                    "schema_version": 2,
                    "mode": "local",
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "dimension": 2,
                },
                "items": {
                    "approval-flow#chunk-1": {
                        "embedding": [1.0, 0.0],
                        "page_id": "approval-flow",
                        "path": str(page),
                        "heading_path": ["Approval Flow"],
                        "text": "Director threshold.",
                    }
                },
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "WIKI_DIR", wiki)

        import generate_embeddings

        monkeypatch.setattr(
            generate_embeddings,
            "get_embeddings_config",
            lambda: {
                "mode": "local",
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "dimension": 2,
                "backend": "faiss",
            },
        )
        monkeypatch.setattr(generate_embeddings, "get_embedding", lambda text: [1.0, 0.0])

        results = search.vector_chunk_search("director", str(wiki / "pages"), limit=5)

        assert results
        assert results[0]["stream"] == "chunk_vector"
        assert results[0]["chunk_id"] == "approval-flow#chunk-1"
