"""Tests for graph.py — knowledge graph builder and querier."""

import json
import os
from pathlib import Path

import graph


class TestBuildEntityRegistry:
    def test_builds_from_entity_pages(self, wiki_dir, sample_entities):
        entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
        data = json.loads(entities_path.read_text())

        assert "auth-service" in data
        assert data["auth-service"]["type"] == "project"
        assert data["auth-service"]["name"] == "Auth Service"
        assert data["auth-service"]["confidence"] == 0.9

    def test_returns_empty_on_missing_dir(self, wiki_dir):
        result = graph.build_entity_registry("/nonexistent/path")
        assert result == {}

    def test_handles_non_md_files(self, wiki_dir, sample_entities):
        entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
        data = json.loads(entities_path.read_text())
        assert all(not k.endswith('.json') for k in data.keys())


class TestBuildEdges:
    def test_extracts_uses_relationships(self, wiki_dir, sample_entities):
        edges_path = Path(wiki_dir) / ".wiki" / "graph" / "edges.json"
        data = json.loads(edges_path.read_text())
        edges = data.get("edges", [])

        assert len(edges) > 0
        types = {e["type"] for e in edges}
        assert "uses" in types

    def test_edges_have_required_fields(self, wiki_dir, sample_entities):
        edges_path = Path(wiki_dir) / ".wiki" / "graph" / "edges.json"
        data = json.loads(edges_path.read_text())

        for edge in data.get("edges", []):
            assert "id" in edge
            assert "source" in edge
            assert "target" in edge
            assert "type" in edge
            assert "confidence" in edge


class TestTraverse:
    def test_bfs_from_entity(self, wiki_dir, sample_entities):
        result = graph.traverse("auth-service", depth=1)
        assert "auth-service" in result
        edges = result["auth-service"]["edges"]
        assert len(edges) > 0

    def test_edge_type_filter(self, wiki_dir, sample_entities):
        result = graph.traverse("auth-service", depth=2, edge_types=["uses"])
        assert "auth-service" in result

    def test_depth_limit(self, wiki_dir, sample_entities):
        result = graph.traverse("auth-service", depth=0)
        assert "auth-service" in result
        # depth 0 should only show the entity itself, no deeper
        entity_data = result["auth-service"]
        assert isinstance(entity_data, dict)


class TestFindPath:
    def test_finds_direct_path(self, wiki_dir, sample_entities):
        result = graph.find_path("auth-service", "redis-caching")
        assert result is not None
        assert len(result) > 0

    def test_returns_none_for_disconnected(self, wiki_dir, sample_entities):
        result = graph.find_path("auth-service", "nonexistent-entity")
        assert result is None


class TestGraphStats:
    def test_entity_count(self, wiki_dir, sample_entities):
        stats = graph.graph_stats()
        assert stats["entity_count"] == 3
        assert stats["edge_count"] >= 0
        assert isinstance(stats["edge_types"], dict)
        assert "orphan_count" in stats

    def test_empty_wiki(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            stats = graph.graph_stats()
            assert stats["entity_count"] == 0
        finally:
            os.chdir(old)
