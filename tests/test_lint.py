"""Tests for lint.py — wiki quality linter."""

import json
import os
from pathlib import Path

import pytest

import lint


class TestFindOrphans:
    def test_detects_pages_without_edges(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            entity = Path(".wiki") / "pages" / "entities" / "lonely-page.md"
            entity.parent.mkdir(parents=True, exist_ok=True)
            entity.write_text("---\nid: lonely-page\ntype: project\nname: Lonely\n---\n\n# Lonely\n")

            graph_dir = Path(".wiki") / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "entities.json").write_text(json.dumps({
                "lonely-page": {"id": "lonely-page", "type": "project", "name": "Lonely"}
            }))
            (graph_dir / "edges.json").write_text(json.dumps({"edges": []}))

            orphans = lint.find_orphans()
            assert len(orphans) > 0
        finally:
            os.chdir(old)


class TestFindBrokenLinks:
    def test_detects_broken_wikilinks(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            page = Path(".wiki") / "pages" / "entities" / "test.md"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text("---\nid: test\n---\n\nLink to [[nonexistent-page]]")

            graph_dir = Path(".wiki") / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "entities.json").write_text(json.dumps({
                "test": {"id": "test", "type": "project", "name": "Test"}
            }))
            (graph_dir / "edges.json").write_text(json.dumps({"edges": []}))

            broken = lint.find_broken_links()
            assert len(broken) > 0
            assert broken[0]["target"] == "nonexistent-page"
        finally:
            os.chdir(old)


class TestFindStaleClaims:
    def test_detects_old_content(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            graph_dir = Path(".wiki") / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "entities.json").write_text(json.dumps({
                "old-project": {
                    "id": "old-project", "type": "project", "name": "Old Project",
                    "last_confirmed": "2020-01-01T00:00:00Z"
                }
            }))
            (graph_dir / "edges.json").write_text(json.dumps({"edges": []}))

            stale = lint.find_stale_claims()
            assert len(stale) > 0
            assert stale[0]["retention"] < 0.5
        finally:
            os.chdir(old)


class TestFindContradictions:
    def test_detects_confidence_mismatch(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            graph_dir = Path(".wiki") / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "entities.json").write_text(json.dumps({
                "redis-cache-1": {"id": "redis-cache-1", "type": "library", "name": "Redis", "confidence": 0.9},
                "redis-cache-2": {"id": "redis-cache-2", "type": "library", "name": "Redis", "confidence": 0.3},
            }))
            (graph_dir / "edges.json").write_text(json.dumps({"edges": []}))

            contradictions = lint.find_contradictions()
            assert len(contradictions) > 0
        finally:
            os.chdir(old)


class TestGenerateReport:
    def test_produces_markdown_report(self):
        issues = {
            "orphans": [{"entity_id": "test", "name": "Test", "type": "project"}],
            "stale": [],
            "broken_links": [],
            "contradictions": [],
        }
        report = lint.generate_report(issues, [])
        assert "# Wiki Health Report" in report
        assert "Test" in report
        assert "orphans" in report.lower()
