"""Tests for non-blocking, query-driven dream maintenance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import dream


def _frontmatter(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    return yaml.safe_load(content.split("---", 2)[1])


def test_light_sleep_logs_query_and_optimizes_retrieved_page(wiki_dir, monkeypatch):
    wiki = Path(wiki_dir) / ".wiki"
    page = wiki / "pages" / "concepts" / "retrieval.md"
    page.write_text(
        "---\nid: retrieval\ntype: concept\nname: Retrieval\n---\n\n# Retrieval\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dream, "_today", lambda: "20260626")
    monkeypatch.setattr(dream, "_read_logs", lambda days=7: [  # patch multi-day reader
        {
            "timestamp": "2026-06-26T00:00:00Z",
            "question": "How does retrieval work?",
            "format": "markdown",
            "synthesis": True,
            "answer_chars": 100,
            "sources": [
                {"id": "retrieval", "name": "Retrieval", "path": str(page), "relevance": 0.9}
            ],
        }
    ])

    items = dream.phase_light_sleep()

    metadata = _frontmatter(page)
    assert len(items) == 1
    assert "How does retrieval work?" in metadata["questions"]
    assert "retrieval" in metadata["keywords"]
    assert metadata["dream_query_count"] == 1


def test_worker_writes_status_and_reports_without_query_history(wiki_dir, monkeypatch):
    wiki = Path(wiki_dir) / ".wiki"
    monkeypatch.setattr(dream, "_today", lambda: "20260626")
    monkeypatch.setattr(dream, "_read_logs", lambda days=7: [])

    result = dream.run_worker()

    status = json.loads((wiki / "dream" / "status.json").read_text(encoding="utf-8"))
    assert result == "Dream complete"
    assert status["state"] == "complete"
    # New phases produce these output files
    assert (wiki / "dream" / "20260626-light.json").exists()
    assert (wiki / "dream" / "20260626-audit.md").exists()
    assert (wiki / "dream" / "20260626-purify.md").exists()
    assert (wiki / "dream" / "20260626-enrich.md").exists()


def test_cancel_active_dream_marks_running_worker_cancelled(wiki_dir):
    wiki = Path(wiki_dir) / ".wiki"
    dream_dir = wiki / "dream"
    dream_dir.mkdir()
    (dream_dir / "status.json").write_text(
        json.dumps({"state": "running", "stage": "light", "pid": 999999, "started_at": "now"}),
        encoding="utf-8",
    )

    dream.cancel_active_dream("query started")

    status = json.loads((dream_dir / "status.json").read_text(encoding="utf-8"))
    assert (dream_dir / "cancel.flag").exists()
    assert status["state"] == "cancelled"


def test_phase_audit_produces_analysis_task(wiki_dir, monkeypatch):
    wiki = Path(wiki_dir) / ".wiki"
    monkeypatch.setattr(dream, "_today", lambda: "20260626")
    monkeypatch.setattr(dream, "_read_logs", lambda days=7: [
        {
            "timestamp": "2026-06-26T00:00:00Z",
            "question": "What is retrieval?",
            "format": "markdown",
            "synthesis": True,
            "answer_chars": 50,
            "sources": [],
        },
        {
            "timestamp": "2026-06-26T01:00:00Z",
            "question": "What is retrieval?",
            "format": "markdown",
            "synthesis": True,
            "answer_chars": 60,
            "sources": [],
        },
    ])

    output = dream.phase_audit([])

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "What is retrieval?" in content
    assert "Q1:" in content
    assert "2×" in content


def test_phase_purify_produces_report(wiki_dir, monkeypatch):
    wiki = Path(wiki_dir) / ".wiki"
    monkeypatch.setattr(dream, "_today", lambda: "20260626")
    monkeypatch.setattr(dream, "_read_logs", lambda days=7: [
        {
            "timestamp": "2026-06-26T00:00:00Z",
            "question": "How does retrieval work?",
            "format": "markdown",
            "synthesis": True,
            "answer_chars": 100,
            "sources": [],
        },
        {
            "timestamp": "2026-06-26T01:00:00Z",
            "question": "How does retrieval work?",
            "format": "markdown",
            "synthesis": True,
            "answer_chars": 120,
            "sources": [],
        },
    ])
    # Mock search to return empty results (no wiki pages)
    monkeypatch.setattr(dream, "_run_search", lambda q: {
        "query": q,
        "pages_searched": 0,
        "source_details": [],
    })

    output = dream.phase_purify()

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Dream Purify" in content


def test_phase_enrich_produces_report(wiki_dir, monkeypatch):
    wiki = Path(wiki_dir) / ".wiki"
    monkeypatch.setattr(dream, "_today", lambda: "20260626")
    monkeypatch.setattr(dream, "_read_logs", lambda days=7: [])

    output = dream.phase_enrich()

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Dream Enrich" in content
