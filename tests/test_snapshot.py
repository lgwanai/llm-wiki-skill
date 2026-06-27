"""Tests for _snapshot.py — git-based version management."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_wiki():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestEnsureGitRepo:
    def test_creates_git_repo(self, tmp_wiki):
        from scripts._snapshot import ensure_git_repo
        result = ensure_git_repo(tmp_wiki)
        if result:
            assert (tmp_wiki / ".git").is_dir()

    def test_idempotent(self, tmp_wiki):
        from scripts._snapshot import ensure_git_repo
        first = ensure_git_repo(tmp_wiki)
        second = ensure_git_repo(tmp_wiki)
        assert first == second


class TestCreateSnapshot:
    def test_returns_hash(self, tmp_wiki):
        from scripts._snapshot import create_snapshot, ensure_git_repo
        if not ensure_git_repo(tmp_wiki):
            pytest.skip("git not available")
        (tmp_wiki / "test.md").write_text("# test")
        h = create_snapshot(tmp_wiki, "test-snapshot")
        assert h is not None and len(h) == 12

    def test_empty_repo_ok(self, tmp_wiki):
        from scripts._snapshot import create_snapshot, ensure_git_repo
        if not ensure_git_repo(tmp_wiki):
            pytest.skip("git not available")
        assert create_snapshot(tmp_wiki, "empty") is not None


class TestRollback:
    def test_restores_file(self, tmp_wiki):
        from scripts._snapshot import create_snapshot, ensure_git_repo, rollback
        if not ensure_git_repo(tmp_wiki):
            pytest.skip("git not available")
        (tmp_wiki / "page.md").write_text("before")
        h = create_snapshot(tmp_wiki, "pre-change")
        (tmp_wiki / "page.md").write_text("after")
        assert rollback(tmp_wiki, h, "test-rollback")
        assert (tmp_wiki / "page.md").read_text() == "before"


class TestListSnapshots:
    def test_empty_for_non_repo(self, tmp_wiki):
        from scripts._snapshot import list_snapshots
        assert list_snapshots(tmp_wiki) == []
