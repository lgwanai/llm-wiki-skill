"""Tests for compile_v2.py — source compilation and sensitive data filtering."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import compile_v2 as ingest
import pytest


class TestFilterSensitive:
    def test_redacts_api_keys(self):
        content = "My API key is sk-abc123def456ghi789jkl012mno345pqr678stu"
        filtered = ingest.strip_sensitive(content)
        assert "sk-" not in filtered
        assert "REDACTED" in filtered

    def test_redacts_github_tokens(self):
        content = "Token: ghp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        filtered = ingest.strip_sensitive(content)
        assert "ghp_" not in filtered
        assert "REDACTED" in filtered

    def test_redacts_passwords(self):
        content = "database password=supersecret123 connection"
        filtered = ingest.strip_sensitive(content)
        assert "supersecret123" not in filtered

    def test_redacts_emails(self):
        content = "Contact alice@example.com or bob@company.co.uk"
        filtered = ingest.strip_sensitive(content)
        assert "alice@example.com" not in filtered
        assert "bob@company.co.uk" not in filtered

    def test_redacts_private_keys(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIICXAIBAAKBgQC...\n-----END RSA PRIVATE KEY-----"
        filtered = ingest.strip_sensitive(content)
        assert "PRIVATE KEY" not in filtered

    def test_preserves_harmless_content(self):
        content = "The Redis version is 7.0 and runs on port 6379."
        filtered = ingest.strip_sensitive(content)
        assert "Redis" in filtered
        assert "7.0" in filtered


class TestIngestSource:
    @patch("compile_v2.call_llm")
    def test_ingests_text_file(self, mock_call_llm, wiki_dir):
        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "source.txt"
        src.write_text("Project uses Redis for caching. File at src/auth.py.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            # Need to update paths in compile_v2 temporarily for the test to use wiki_dir
            ingest.WIKI_DIR = Path(wiki_dir) / ".wiki"
            ingest.PAGES_DIR = ingest.WIKI_DIR / "pages"
            ingest.ENTITIES_DIR = ingest.PAGES_DIR / "entities"
            ingest.CONCEPTS_DIR = ingest.PAGES_DIR / "concepts"
            ingest.INDEX_FILE = ingest.PAGES_DIR / "index.md"

            result = ingest.compile_source(str(src))
            assert result["source"] == "source.txt"
            assert result["pages_created"] >= 0
        finally:
            os.chdir(old_cwd)

    def test_handles_missing_file(self, wiki_dir):
        with pytest.raises(FileNotFoundError):
            ingest.compile_source("/nonexistent/path.txt")

    @patch("compile_v2.call_llm")
    def test_updates_entities_json(self, mock_call_llm, wiki_dir):
        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "readme.md"
        src.write_text("# Auth Service\n")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            ingest.WIKI_DIR = Path(wiki_dir) / ".wiki"
            ingest.PAGES_DIR = ingest.WIKI_DIR / "pages"
            ingest.ENTITIES_DIR = ingest.PAGES_DIR / "entities"
            ingest.CONCEPTS_DIR = ingest.PAGES_DIR / "concepts"
            ingest.INDEX_FILE = ingest.PAGES_DIR / "index.md"

            result = ingest.compile_source(str(src))

            entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
            data = json.loads(entities_path.read_text())
            assert isinstance(data, dict)
            assert len(data) > 0
        finally:
            os.chdir(old_cwd)

    @patch("compile_v2.call_llm")
    def test_logs_to_audit_trail(self, mock_call_llm, wiki_dir):
        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "notes.txt"
        src.write_text("Important: Redis config for auth service.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            ingest.WIKI_DIR = Path(wiki_dir) / ".wiki"
            ingest.PAGES_DIR = ingest.WIKI_DIR / "pages"
            ingest.ENTITIES_DIR = ingest.PAGES_DIR / "entities"
            ingest.CONCEPTS_DIR = ingest.PAGES_DIR / "concepts"
            ingest.INDEX_FILE = ingest.PAGES_DIR / "index.md"

            result = ingest.compile_source(str(src))

            audit_path = Path(wiki_dir) / ".wiki" / "audit.json"
            assert audit_path.exists()
            entries = json.loads(audit_path.read_text())
            assert len(entries) > 0
            assert entries[-1]["operation"] == "compile"
        finally:
            os.chdir(old_cwd)
