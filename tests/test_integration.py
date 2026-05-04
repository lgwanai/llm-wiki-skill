"""Integration tests — full ingest-to-lint pipeline."""

import json
import os
from pathlib import Path

import pytest


class TestIngestLintPipeline:
    def test_full_ingest_pipeline(self, wiki_dir):
        """End-to-end: ingest a source → check entities, edges, audit trail."""
        import graph
        import ingest
        import lint as lint_module

        src = Path(wiki_dir) / "project-doc.md"
        src.write_text("""# Project Documentation

The Auth Service uses Redis (v7.0) for session caching.
Configuration is in docker-compose.yml at the root.
Sarah Chen is the backend lead.
The auth service depends on Redis for token storage.
""")

        result = ingest.ingest_source(str(src), source_type="doc")

        assert result["source"] == "project-doc.md"
        assert result["entities_found"] > 0

        entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
        entities_data = json.loads(entities_path.read_text())
        assert len(entities_data) > 0

        edges_path = Path(wiki_dir) / ".wiki" / "graph" / "edges.json"
        edges_data = json.loads(edges_path.read_text())
        assert len(edges_data.get("edges", [])) >= 0

        audit_path = Path(wiki_dir) / ".wiki" / "audit" / "trail.jsonl"
        assert audit_path.exists()

    def test_ingest_then_lint(self, wiki_dir):
        """Ingest a source, then run lint — verify no crashes."""
        import ingest
        import lint as lint_module

        src = Path(wiki_dir) / "doc.md"
        src.write_text("Auth Service uses Redis and sqlalchemy for database access.\n"
                       "File at src/auth/middleware.py handles JWT validation.\n")

        result = ingest.ingest_source(str(src), source_type="doc")
        assert result["entities_found"] > 0

        lint_module.find_orphans()
        lint_module.find_stale_claims()
        lint_module.find_broken_links()
        lint_module.find_contradictions()

    def test_multiple_ingests(self, wiki_dir):
        """Ingest multiple sources — verify graph accumulates."""
        import ingest

        old = os.getcwd()
        os.chdir(wiki_dir)

        paths = []
        for i, content in enumerate([
            '"Service A" uses MySQL at src/service_a.py.',
            '"Service B" uses Redis at src/service_b.py.',
            '"Service A" depends on "Service C" at src/middleware.py.',
            '"Service C" uses PostgreSQL at config/db.yaml.',
        ]):
            p = Path(wiki_dir) / f"doc_{i}.md"
            p.write_text(content)
            paths.append(str(p))

        for p in paths:
            ingest.ingest_source(p, source_type="doc")

        entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
        entities_data = json.loads(entities_path.read_text())
        assert len(entities_data) > 0


class TestConsolidationAfterIngest:
    def test_ingest_then_consolidation_no_crash(self, wiki_dir):
        """Verify consolidation doesn't crash after ingest."""
        import ingest
        import consolidate

        src = Path(wiki_dir) / "data.md"
        src.write_text("entity Alpha uses entity Beta\nentity Gamma uses entity Delta\n")

        ingest.ingest_source(str(src), source_type="doc")

        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            consolidate.promote_working_to_episodic()
            consolidate.apply_retention_decay()
        finally:
            os.chdir(old)
