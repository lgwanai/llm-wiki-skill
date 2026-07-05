"""Tests for search.py — wiki-native hybrid search and RRF fusion."""

import json
import os
from pathlib import Path

import search


def test_normalize_date_handles_formats_and_rejects_invalid():
    import datetime as _dt

    assert search._normalize_date("2024-01-15") == "2024-01-15"
    assert search._normalize_date("2024/1/5") == "2024-01-05"
    assert search._normalize_date("2024-12") == "2024-12"
    assert search._normalize_date("2024-01-15T10:30:00") == "2024-01-15"
    assert search._normalize_date(_dt.date(2024, 3, 9)) == "2024-03-09"
    assert search._normalize_date(_dt.datetime(2024, 3, 9, 12, 0)) == "2024-03-09"
    # Out-of-range / garbage → "" (no crash, no invalid date indexed).
    assert search._normalize_date("2024-13-45") == ""
    assert search._normalize_date("2024-00-00") == ""
    assert search._normalize_date("") == ""
    assert search._normalize_date(None) == ""
    assert search._normalize_date("not a date") == ""


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

    def test_links_entity_alias_inside_natural_language_query(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        graph_dir = wiki / "graph"
        page_dir = wiki / "pages" / "concepts"
        graph_dir.mkdir(parents=True)
        page_dir.mkdir(parents=True)
        page = page_dir / "llm-wiki.md"
        page.write_text("# LLM Wiki\n\nCompiled knowledge base.", encoding="utf-8")
        (graph_dir / "entities.json").write_text(
            json.dumps({
                "llm-wiki": {
                    "id": "llm-wiki",
                    "type": "concept",
                    "name": "LLM Wiki",
                    "aliases": ["个人知识库", "LLM维基"],
                    "confidence": 0.95,
                    "page": "pages/concepts/llm-wiki.md",
                }
            }),
            encoding="utf-8",
        )
        (graph_dir / "edges.json").write_text('{"edges":[]}', encoding="utf-8")
        monkeypatch.setattr(search, "_cache_marker", None)

        results = search.graph_search("个人知识库如何避免传统RAG问题", str(graph_dir), limit=5)

        assert results
        assert results[0]["entity_id"] == "llm-wiki"
        assert results[0]["path"] == str(page)

    def test_relationship_query_adds_connected_entity_candidates(self, wiki_dir, sample_entities):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            results = search.graph_search(
                "Auth Service 和 Redis 的关系是什么",
                str(Path(".wiki") / "graph"),
                limit=5,
            )
        finally:
            os.chdir(old)

        result_ids = [r["entity_id"] for r in results]
        assert "auth-service" in result_ids
        assert "redis-caching" in result_ids


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
        results_b = [{"file": "same.md", "score": 0.8, "stream": "graph"}]
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
        monkeypatch.setattr(
            search, "_METADATA_CACHE_FILE", wiki / "graph" / ".metadata_index.json"
        )
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
        monkeypatch.setattr(
            search, "_METADATA_CACHE_FILE", wiki / "graph" / ".metadata_index.json"
        )
        monkeypatch.setattr(search, "_cache_marker", None)

        result = search.search_doctor(wiki)

        assert result["metadata_items"] == 1


class TestSearchDoctor:
    def test_doctor_reports_missing_pages(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        (wiki / "graph").mkdir(parents=True)
        (wiki / "graph" / "entities.json").write_text("{}", encoding="utf-8")
        (wiki / "graph" / "edges.json").write_text('{"edges":[]}', encoding="utf-8")
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "_cache_marker", None)

        result = search.search_doctor(wiki)

        assert result["pages"] == 0
        assert "no wiki pages found" in result["issues"]


class TestEvalRetrieval:
    def test_eval_retrieval_hits_expected_page(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "approval-flow.md").write_text(
            "# Approval Flow\n\nThreshold 10000 requires director approval.",
            encoding="utf-8",
        )
        (wiki / "graph").mkdir(parents=True)
        (wiki / "graph" / "entities.json").write_text("{}", encoding="utf-8")
        (wiki / "graph" / "edges.json").write_text('{"edges":[]}', encoding="utf-8")
        eval_file = tmp_path / "retrieval.jsonl"
        eval_file.write_text(
            json.dumps({"query": "threshold 10000", "expected_pages": ["approval-flow"]}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "WIKI_DIR", wiki)
        monkeypatch.setattr(search, "PAGES_DIR", wiki / "pages")
        monkeypatch.setattr(search, "GRAPH_DIR", wiki / "graph")
        monkeypatch.setattr(search, "_BM25_CACHE_FILE", wiki / "graph" / ".bm25_index.json")
        monkeypatch.setattr(search, "_METADATA_CACHE_FILE", wiki / "graph" / ".metadata_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)
        monkeypatch.setattr(search, "_bm25_index", None)
        monkeypatch.setattr(search, "_entities_cache", None)
        monkeypatch.setattr(search, "_edges_cache", None)

        result = search.eval_retrieval(eval_file, limit=5)

        assert result["status"] == "ok"
        assert result["recall_at_k"] == 1.0


class TestTableSearch:
    def test_returns_empty_when_no_ledger_db(self, tmp_path):
        wiki = str(tmp_path / ".wiki")
        results = search.table_search("test", wiki, limit=5)
        assert results == []
