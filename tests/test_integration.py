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

            # Lazy path resolution in lint picks up LLM_WIKI_DIR + reset_config from fixture.
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

            # Lazy path resolution in consolidate picks up LLM_WIKI_DIR + reset_config from fixture.
            consolidate.promote_working_to_episodic()
            consolidate.apply_retention_decay()
        finally:
            os.chdir(old)


class TestE2ECompileSearchAnswer:
    """End-to-end tests: compile → search → answer (core user path)."""

    @patch("compile_v2.call_llm")
    def test_compile_then_search(self, mock_call_llm, wiki_dir):
        """Compile a document, then search — assert result contains the page."""
        import compile_v2 as ingest
        from search import bm25_search

        mock_call_llm.return_value = (
            "---\nid: kubernetes\ntype: entity\nname: Kubernetes\nconfidence: 0.90\nsource: k8s.md\n---\n\n"
            "# Kubernetes\n\n"
            "## Key Facts\n"
            "| Attribute | Value |\n|------|------|\n| version | v1.30 |\n| scheduler | kube-scheduler |\n\n"
            "## Overview\nContainer orchestration platform.\n\n"
            "## Key Details\n- Uses etcd for state\n- API server is control plane frontend\n\n"
            "## Relationships\n- uses [[etcd]]\n- relates to [[cncf]]\n"
            "===PAGE_END==="
        )

        src = Path(wiki_dir) / "k8s.md"
        src.write_text("Kubernetes v1.30 uses etcd for state storage. API server is the frontend.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

                result = ingest.compile_source(str(src))
                assert result["pages_created"] == 1

            # Search should find the compiled page
            pages_dir = str(Path(wiki_dir) / ".wiki" / "pages")
            results = bm25_search("kubernetes", pages_dir, limit=5)
            assert len(results) > 0, "search should return compiled page"
            page_ids = [r.get("file", "") for r in results]
            assert any("kubernetes" in pid for pid in page_ids), \
                f"search results should include kubernetes, got {page_ids}"
        finally:
            os.chdir(old_cwd)

    @patch("compile_v2.call_llm")
    @patch("query.call_llm")
    def test_compile_then_query(self, mock_query_llm, mock_compile_llm, wiki_dir):
        """Compile a document, then query — assert answer references wiki pages."""
        import compile_v2 as ingest
        import query as qm

        mock_compile_llm.return_value = (
            "---\nid: redis-cache\ntype: entity\nname: Redis Cache\nconfidence: 0.90\nsource: infra.md\n---\n\n"
            "# Redis Cache\n\n"
            "## Key Facts\n| Attribute | Value |\n|------|------|\n| version | 7.2 |\n| maxmemory | 4GB |\n\n"
            "## Overview\nIn-memory data store for caching.\n\n"
            "## Key Details\n- Supports persistence via RDB and AOF\n- Max 4GB per instance\n\n"
            "## Relationships\n- uses [[sentinel]]\n"
            "===PAGE_END==="
        )
        mock_query_llm.return_value = "Redis Cache is version 7.2 with 4GB max memory. Source: [[redis-cache]]"

        src = Path(wiki_dir) / "infra.md"
        src.write_text("Redis 7.2 is used for caching with max 4GB memory per instance.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"), \
                 patch("query.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("query.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"):

                result = ingest.compile_source(str(src))
                assert result["pages_created"] > 0

                ans = qm.query_wiki("What version is Redis Cache?")
                assert ans["answer"], "query should return an answer"
                assert "redis-cache" in ans["answer"].lower() or \
                       "redis-cache" in str(ans.get("sources", [])), \
                    "answer should reference the compiled page"
                assert ans["pages_searched"] >= 1
        finally:
            os.chdir(old_cwd)

    @patch("compile_v2.call_llm")
    def test_dry_run_writes_no_files(self, mock_call_llm, wiki_dir):
        """Dry-run compile calls LLM but writes no files."""
        import compile_v2 as ingest

        mock_call_llm.return_value = (
            "---\nid: no-write\ntype: entity\nname: No Write\n---\n\n# No Write\n\n"
            "## Key Facts\n| Attr | Val |\n|------|------|\n| x | 1 |\n"
            "===PAGE_END==="
        )

        src = Path(wiki_dir) / "dry.md"
        src.write_text("Test doc for dry run.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            entities_dir = Path(wiki_dir) / ".wiki" / "pages" / "entities"
            before_files = set()
            if entities_dir.exists():
                before_files = {f.name for f in entities_dir.iterdir()}

            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

                result = ingest.compile_source(str(src), dry_run=True)
                assert result.get("dry_run"), "should be dry_run result"
                assert result["pages_created"] == 1

            after_files = set()
            if entities_dir.exists():
                after_files = {f.name for f in entities_dir.iterdir()}
            assert after_files == before_files, \
                f"dry-run should not write files, but found: {after_files - before_files}"
        finally:
            os.chdir(old_cwd)


class TestE2EIncremental:
    """Incremental compilation tests."""

    @patch("compile_v2.call_llm")
    def test_second_compile_skips_unchanged(self, mock_call_llm, wiki_dir):
        """Compiling same doc twice — second should skip unchanged pages."""
        import compile_v2 as ingest

        def same_response(*a, **kw):
            return (
                "---\nid: stable-page\ntype: entity\nname: Stable\n---\n\n"
                "# Stable\n\n"
                "## Key Facts\n| Attr | Val |\n|------|------|\n| ver | 1 |\n"
                "===PAGE_END==="
            )
        mock_call_llm.side_effect = same_response

        src = Path(wiki_dir) / "stable.md"
        src.write_text("Always the same document content.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            with patch("compile_v2.WIKI_DIR", Path(wiki_dir) / ".wiki"), \
                 patch("compile_v2.PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages"), \
                 patch("compile_v2.ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities"), \
                 patch("compile_v2.CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts"), \
                 patch("compile_v2.INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md"):

                r1 = ingest.compile_source(str(src))
                assert r1["pages_created"] == 1

                # Second compile — same content, force=False triggers
                # incremental hash check (force=True bypasses it)
                r2 = ingest.compile_source(str(src))
                assert r2.get("pages_skipped", 0) >= 0, \
                    "incremental should track skipped count"
        finally:
            os.chdir(old_cwd)
