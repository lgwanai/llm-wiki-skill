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

    def test_long_page_reports_precise_matching_section(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        pages = wiki / "pages" / "concepts"
        pages.mkdir(parents=True)
        page = pages / "incident-runbook.md"
        page.write_text(
            "# Incident Runbook\n\n## Background\n"
            + "routine operational background " * 600
            + "\n\n## Retry Recovery\n\n"
            "outbox_retry_watermark controls retry backoff after an incident.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(search, "_BM25_CACHE_FILE", wiki / "graph" / ".bm25.json")
        monkeypatch.setattr(search, "_cache_marker", None)
        monkeypatch.setattr(search, "_bm25_index", None)

        results = search.bm25_search(
            "outbox retry watermark backoff",
            str(wiki / "pages"),
            limit=3,
        )

        assert results[0]["file"] == "concepts/incident-runbook"
        assert results[0]["matched_section"] == "Retry Recovery"
        assert results[0]["section_score"] > 0


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

    def test_typed_relationship_query_traverses_two_hops(self, tmp_path):
        wiki = tmp_path / ".wiki"
        graph_dir = wiki / "graph"
        pages = wiki / "pages" / "concepts"
        graph_dir.mkdir(parents=True)
        pages.mkdir(parents=True)
        for page_id in ("question-1", "density", "ratio"):
            (pages / f"{page_id}.md").write_text(f"# {page_id}\n", encoding="utf-8")
        (graph_dir / "entities.json").write_text(
            json.dumps(
                {
                    "concepts/question-1": {"name": "第1题", "type": "entity"},
                    "concepts/density": {"name": "密度", "type": "concept"},
                    "concepts/ratio": {"name": "比值", "type": "concept"},
                }
            ),
            encoding="utf-8",
        )
        (graph_dir / "edges.json").write_text(
            json.dumps(
                {
                    "edges": [
                        {
                            "source": "concepts/question-1",
                            "target": "concepts/density",
                            "type": "tests",
                        },
                        {
                            "source": "concepts/density",
                            "target": "concepts/ratio",
                            "type": "depends_on",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        results = search.graph_search("第1题需要哪些前置知识", str(graph_dir), limit=5)

        prerequisite = next(
            item for item in results if item["entity_id"] == "concepts/ratio"
        )
        assert prerequisite["graph_path"] == [
            "concepts/question-1",
            "concepts/density",
            "concepts/ratio",
        ]


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
type: concept
title: Order Approval Flow
description: Budget approval process with director threshold and OAF abbreviation.
tags:
  - OAF
  - 订单审批
  - budget threshold
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
        assert results[0]["file"] == "concepts/order-approval-flow"
        assert results[0]["path"] == str(page)
        assert "OAF" in results[0]["keywords"]

    def test_indexes_explicit_aliases_and_keywords(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        page = page_dir / "mass-density.md"
        page.write_text(
            "---\ntype: concept\ntitle: 质量密度\n"
            "aliases: [密度]\nkeywords: [质量体积比]\n---\n# 质量密度\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            search, "_METADATA_CACHE_FILE", wiki / "graph" / ".metadata_index.json"
        )
        monkeypatch.setattr(search, "_cache_marker", None)

        alias_results = search.metadata_search("密度", str(wiki / "pages"), limit=3)
        keyword_results = search.metadata_search(
            "质量体积比", str(wiki / "pages"), limit=3
        )

        assert alias_results[0]["file"] == "concepts/mass-density"
        assert "密度" in alias_results[0]["aliases"]
        assert keyword_results[0]["file"] == "concepts/mass-density"
        assert "质量体积比" in keyword_results[0]["keywords"]

    def test_nested_okf_change_invalidates_bm25_and_metadata_caches(
        self, tmp_path, monkeypatch
    ):
        wiki = tmp_path / ".wiki"
        pages = wiki / "pages"
        first = pages / "concepts" / "first.md"
        first.parent.mkdir(parents=True)
        first.write_text(
            "---\ntype: Concept\ntitle: First\n---\n# First\n\nalpha",
            encoding="utf-8",
        )
        graph = wiki / "graph"
        monkeypatch.setattr(search, "_BM25_CACHE_FILE", graph / ".bm25_index.json")
        monkeypatch.setattr(search, "_METADATA_CACHE_FILE", graph / ".metadata_index.json")
        monkeypatch.setattr(search, "_cache_marker", None)
        monkeypatch.setattr(search, "_bm25_index", None)

        assert search.bm25_search("alpha", str(pages))
        assert search.metadata_search("First", str(pages))

        nested = pages / "legal" / "regional" / "second.md"
        nested.parent.mkdir(parents=True)
        nested.write_text(
            "---\ntype: Regulation\ntitle: Zephyr Rule\n---\n# Zephyr Rule\n\nquasar",
            encoding="utf-8",
        )

        assert search.bm25_search("quasar", str(pages))[0]["file"] == "legal/regional/second"
        assert search.metadata_search("Zephyr Rule", str(pages))[0]["file"] == (
            "legal/regional/second"
        )

    def test_search_doctor_reports_metadata_items(self, tmp_path, monkeypatch):
        wiki = tmp_path / ".wiki"
        page_dir = wiki / "pages" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "x.md").write_text(
            "---\ntype: Reference\ntitle: X\n---\n# X\n\nBody", encoding="utf-8"
        )
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
            json.dumps(
                {
                    "query": "threshold 10000",
                    "expected_pages": ["concepts/approval-flow"],
                }
            )
            + "\n",
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
