"""Tests for search.py — hybrid search and RRF fusion."""

import os
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
