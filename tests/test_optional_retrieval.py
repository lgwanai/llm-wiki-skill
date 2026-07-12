"""Tests for optional semantic retrieval and reranking fallbacks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.rerank as rerank
import scripts.zvec_backend as zvec_backend


def test_zvec_disabled_is_dependency_free(tmp_path):
    assert zvec_backend.vector_search(
        "query", tmp_path / "pages", tmp_path, {"enabled": False}
    ) == []


def test_flag_reranker_orders_candidates(monkeypatch):
    class FakeModel:
        def compute_score(self, pairs, normalize=True):
            assert normalize is True
            return [0.1, 0.9]

    monkeypatch.setattr(rerank, "_flag_model", lambda _name: FakeModel())
    results = [
        {"id": "a", "text": "first", "score": 0.1},
        {"id": "b", "text": "second", "score": 0.1},
    ]

    ranked = rerank.rerank(
        "query",
        results,
        {"enabled": True, "backend": "flagembedding", "model": "fake"},
        2,
    )

    assert [item["id"] for item in ranked] == ["b", "a"]


def test_zvec_preserves_nested_okf_concept_id(monkeypatch, tmp_path):
    pytest.importorskip("zvec")
    page = tmp_path / "pages" / "legal" / "policy.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ntype: Regulation\ntitle: Policy\n---\n# Policy\n\nApproval threshold 10000.",
        encoding="utf-8",
    )

    class FakeEmbedding:
        dimension = 4

        def embed(self, text):
            return [1.0, 0.5, 0.25, min(len(text) / 1000, 1.0)]

    monkeypatch.setattr(zvec_backend, "_embedding", lambda _source: FakeEmbedding())
    config = {
        "enabled": True,
        "backend": "zvec",
        "model_source": "fake",
        "dimension": 4,
        "index_path": "graph/zvec",
    }

    results = zvec_backend.vector_search(
        "approval", tmp_path / "pages", tmp_path, config, limit=3
    )

    assert results[0]["file"] == "legal/policy"
