"""Tests for ingest.py — source ingestion and sensitive data filtering."""

import json
import os
from pathlib import Path

import pytest

import ingest


class TestFilterSensitive:
    def test_redacts_api_keys(self):
        content = "My API key is sk-abc123def456ghi789jkl012mno345pqr678stu"
        filtered, log = ingest.filter_sensitive(content)
        assert "sk-" not in filtered
        assert "REDACTED" in filtered
        assert len(log) > 0

    def test_redacts_github_tokens(self):
        content = "Token: ghp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        filtered, log = ingest.filter_sensitive(content)
        assert "ghp_" not in filtered
        assert "REDACTED" in filtered

    def test_redacts_passwords(self):
        content = "database password=supersecret123 connection"
        filtered, _ = ingest.filter_sensitive(content)
        assert "supersecret123" not in filtered

    def test_redacts_emails(self):
        content = "Contact alice@example.com or bob@company.co.uk"
        filtered, _ = ingest.filter_sensitive(content)
        assert "alice@example.com" not in filtered
        assert "bob@company.co.uk" not in filtered

    def test_redacts_private_keys(self):
        content = """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQC...
-----END RSA PRIVATE KEY-----"""
        filtered, _ = ingest.filter_sensitive(content)
        assert "PRIVATE KEY" not in filtered

    def test_preserves_harmless_content(self):
        content = "The Redis version is 7.0 and runs on port 6379."
        filtered, _ = ingest.filter_sensitive(content)
        assert "Redis" in filtered
        assert "7.0" in filtered

    def test_returns_filter_log(self):
        content = "key: sk-abc123def456ghi789jkl012mno345pqr678stu\nemail: test@example.com"
        _, log = ingest.filter_sensitive(content)
        assert len(log) >= 2


class TestIngestSource:
    def test_ingests_text_file(self, wiki_dir):
        src = Path(wiki_dir) / "source.txt"
        src.write_text("Project uses Redis for caching. File at src/auth.py.")

        result = ingest.ingest_source(str(src), source_type="code")
        assert result["source"] == "source.txt"
        assert result["entities_found"] >= 0
        assert "filtered_items" in result

    def test_handles_missing_file(self, wiki_dir):
        with pytest.raises(FileNotFoundError):
            ingest.ingest_source("/nonexistent/path.txt")

    def test_updates_entities_json(self, wiki_dir):
        src = Path(wiki_dir) / "readme.md"
        src.write_text("# Auth Service\n\nUses Redis for session caching.\n"
                       "Configuration in docker-compose.yml.\n"
                       "Import redis from redis-py.\n")

        result = ingest.ingest_source(str(src), source_type="doc")

        entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
        data = json.loads(entities_path.read_text())
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_logs_to_audit_trail(self, wiki_dir):
        src = Path(wiki_dir) / "notes.txt"
        src.write_text("Important: Redis config for auth service.")

        result = ingest.ingest_source(str(src), source_type="article")

        audit_path = Path(wiki_dir) / ".wiki" / "audit" / "trail.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text().strip().split('\n')
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["op"] == "ingest"
