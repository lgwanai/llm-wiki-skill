"""Tests for query planning and debug search plumbing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.query as query


def test_plan_query_detects_ledger_intent():
    plan = query.plan_query("预算超过40万的进行中项目")

    assert plan["intent"] == "ledger_filter"
    assert plan["preferred_streams"][0] == "ledger"
    assert "metadata" in plan["preferred_streams"]


def test_rewrite_query_adds_hyphen_variant():
    plan = query.plan_query("order approval")

    variants = query.rewrite_query("order approval", plan)

    assert "order approval" in variants
    assert "order-approval" in variants


def test_rerank_prefers_planned_stream():
    plan = {"preferred_streams": ["ledger", "chunk", "bm25"]}
    results = [
        {"id": "a", "score": 0.1, "stream": "bm25", "text": ""},
        {"id": "b", "score": 0.1, "stream": "ledger", "text": ""},
    ]

    ranked = query.rerank_results("预算", results, plan)

    assert ranked[0]["id"] == "b"
    assert "rerank_score" in ranked[0]


def test_rerank_hybrid_uses_dense_rank_signal(monkeypatch):
    monkeypatch.setenv("LLM_WIKI_DENSE_RERANK_WEIGHT", "2.0")
    plan = {"preferred_streams": ["bm25", "vector"]}
    results = [
        {
            "id": "lexical",
            "score": 0.1,
            "stream": "bm25",
            "stream_ranks": {"bm25": 1},
            "stream_scores": {"bm25": 20},
        },
        {
            "id": "semantic",
            "score": 0.1,
            "stream": "vector",
            "stream_ranks": {"vector": 1, "bm25": 8},
            "stream_scores": {"vector": 0.8, "bm25": 1},
        },
    ]

    ranked = query.rerank_results("semantic query", results, plan)

    assert ranked[0]["id"] == "semantic"


def test_filter_by_allowed_scopes_reads_frontmatter(tmp_path):
    public_page = tmp_path / "public.md"
    private_page = tmp_path / "private.md"
    public_page.write_text("---\nid: public\nscope: public\n---\n# Public\n")
    private_page.write_text("---\nid: private\nscope: confidential\n---\n# Private\n")

    results = query._filter_by_allowed_scopes(
        [
            {"id": "public", "path": str(public_page)},
            {"id": "private", "path": str(private_page)},
        ],
        {"public"},
    )

    assert [r["id"] for r in results] == ["public"]


def test_filter_by_excluded_statuses_reads_frontmatter(tmp_path):
    current_page = tmp_path / "current.md"
    old_page = tmp_path / "old.md"
    current_page.write_text("---\nid: current\nstatus: current\n---\n# Current\n")
    old_page.write_text("---\nid: old\nstatus: superseded\n---\n# Old\n")

    results = query._filter_by_excluded_statuses(
        [
            {"id": "current", "path": str(current_page)},
            {"id": "old", "path": str(old_page)},
        ],
        {"superseded"},
    )

    assert [r["id"] for r in results] == ["current"]


def test_search_wiki_debug_returns_trace(monkeypatch):
    monkeypatch.setattr(query, "PAGES_DIR", Path("/nonexistent/pages"))
    monkeypatch.setattr(query, "WIKI_DIR", Path("/nonexistent/.wiki"))
    monkeypatch.setattr(query, "enabled_search_streams", lambda: set())

    results, trace = query.search_wiki("nothing", debug=True)

    assert results == []
    assert trace["query"] == "nothing"
    assert "plan" in trace
    assert "query_variants" in trace
    assert "streams" in trace
