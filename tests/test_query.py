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


def test_search_wiki_debug_returns_trace(monkeypatch):
    monkeypatch.setattr(query, "PAGES_DIR", Path("/nonexistent/pages"))
    monkeypatch.setattr(query, "WIKI_DIR", Path("/nonexistent/.wiki"))

    results, trace = query.search_wiki("nothing", debug=True)

    assert results == []
    assert trace["query"] == "nothing"
    assert "plan" in trace
    assert "query_variants" in trace
    assert "streams" in trace
