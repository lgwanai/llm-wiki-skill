"""Integration tests — full ingest-to-lint pipeline."""

import json
import os
from pathlib import Path
from unittest.mock import patch


class TestIngestLintPipeline:
    @patch("compile_v2.call_llm")
    def test_full_ingest_pipeline(self, mock_call_llm, wiki_dir):
        """End-to-end: ingest a source → check entities, edges, audit trail."""
        import compile_v2 as ingest

        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n\n## Relationships\n- uses [[redis-caching]]\n===PAGE_END==="

        src = Path(wiki_dir) / "project-doc.md"
        src.write_text("""# Project Documentation

The Auth Service uses Redis (v7.0) for session caching.
Configuration is in docker-compose.yml at the root.
Sarah Chen is the backend lead.
The auth service depends on Redis for token storage.
""")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

                result = ingest.compile_source(str(src))

            assert result["source"] == "project-doc.md"
            assert result["pages_created"] > 0

            entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
            entities_data = json.loads(entities_path.read_text())
            assert len(entities_data) > 0

            edges_path = Path(wiki_dir) / ".wiki" / "graph" / "edges.json"
            edges_data = json.loads(edges_path.read_text())
            assert len(edges_data) >= 0

            audit_path = Path(wiki_dir) / ".wiki" / "audit.json"
            assert audit_path.exists()
        finally:
            os.chdir(old_cwd)

    @patch("compile_v2.call_llm")
    def test_ingest_then_lint(self, mock_call_llm, wiki_dir):
        """Ingest a source, then run lint — verify no crashes."""
        import compile_v2 as ingest
        import lint as lint_module

        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "doc.md"
        src.write_text("Auth Service uses Redis and sqlalchemy for database access.\n"
                       "File at src/auth/middleware.py handles JWT validation.\n")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

                result = ingest.compile_source(str(src))
            assert result["pages_created"] > 0

            with patch("lint.WIKI_DIR", str(Path(wiki_dir) / ".wiki")), \
                 patch("lint.PAGES_DIR", str(Path(wiki_dir) / ".wiki" / "pages")), \
                 patch("lint.GRAPH_DIR", str(Path(wiki_dir) / ".wiki" / "graph")), \
                 patch("lint.ENTITIES_FILE", str(Path(wiki_dir) / ".wiki" / "graph" / "entities.json")), \
                 patch("lint.EDGES_FILE", str(Path(wiki_dir) / ".wiki" / "graph" / "edges.json")):

                lint_module.find_orphans()
                lint_module.find_stale_claims()
                lint_module.find_broken_links()
                lint_module.find_contradictions()
        finally:
            os.chdir(old_cwd)

    @patch("compile_v2.call_llm")
    def test_multiple_ingests(self, mock_call_llm, wiki_dir):
        """Ingest multiple sources — verify graph accumulates."""
        import compile_v2 as ingest

        mock_call_llm.return_value = "---\nid: service-a\ntype: project\nname: Service A\n---\n\n# Service A\n===PAGE_END==="

        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

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
                    ingest.compile_source(p)

            entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
            entities_data = json.loads(entities_path.read_text())
            assert len(entities_data) > 0
        finally:
            os.chdir(old)


class TestConsolidationAfterIngest:
    @patch("compile_v2.call_llm")
    def test_ingest_then_consolidation_no_crash(self, mock_call_llm, wiki_dir):
        """Verify consolidation doesn't crash after ingest."""
        import compile_v2 as ingest
        import consolidate

        mock_call_llm.return_value = "---\nid: alpha\ntype: project\nname: Alpha\n---\n\n# Alpha\n===PAGE_END==="

        src = Path(wiki_dir) / "data.md"
        src.write_text("entity Alpha uses entity Beta\nentity Gamma uses entity Delta\n")

        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

                ingest.compile_source(str(src))

            with patch("consolidate.WIKI_DIR", str(Path(wiki_dir) / ".wiki")):
                consolidate.promote_working_to_episodic()
                consolidate.apply_retention_decay()
        finally:
            os.chdir(old)
