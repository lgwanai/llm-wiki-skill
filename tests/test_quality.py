"""Tests for _quality.py — search quality assessment."""

import pytest


class TestAssessQuality:
    def test_empty_queries_returns_keep(self):
        from scripts._quality import assess_quality
        r = assess_quality([], {}, {}, [])
        assert r.recommendation == "keep" and r.overall_score == 0

    def test_no_test_queries_returns_keep(self):
        from scripts._quality import assess_quality
        r = assess_quality([], {}, {}, [])
        assert r.recommendation == "keep"


class TestRunSearchBaseline:
    def test_returns_dict_for_nonexistent_query(self):
        from scripts._quality import run_search_baseline
        from scripts.config import get_wiki_dir
        results = run_search_baseline(["xyzzy_nonexistent_query_42"], get_wiki_dir())
        assert isinstance(results, dict)


class TestCollectTestQueries:
    def test_returns_list(self):
        from scripts._quality import collect_test_queries
        from scripts.config import get_wiki_dir
        queries = collect_test_queries(3, get_wiki_dir())
        assert isinstance(queries, list)
