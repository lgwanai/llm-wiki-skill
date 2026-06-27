"""Tests for _experience.py — experience accumulation with dedup."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def store():
    from scripts._experience import ExperienceStore
    with tempfile.TemporaryDirectory() as d:
        wiki_dir = Path(d)
        (wiki_dir / "dream").mkdir(parents=True)
        yield ExperienceStore(wiki_dir)


class TestExperienceAdd:
    def test_add_new_returns_true(self, store):
        from scripts._experience import Experience
        exp = Experience(
            category="merge", phase=3, context="Test", outcome="success",
            lesson="Test lesson: always validate before merging.",
        )
        assert store.add(exp) is True

    def test_duplicate_returns_false(self, store):
        from scripts._experience import Experience
        e1 = Experience(category="merge", phase=3, context="C1",
                        outcome="rollback", lesson="Same dedup text.")
        e2 = Experience(category="merge", phase=3, context="C2",
                        outcome="rollback", lesson="Same dedup text.")
        assert store.add(e1) is True
        assert store.add(e2) is False

    def test_whitespace_normalized(self, store):
        from scripts._experience import Experience
        e1 = Experience(category="merge", phase=3, context="C", outcome="success",
                        lesson="  Test   lesson  with  spaces.  ")
        e2 = Experience(category="merge", phase=3, context="C", outcome="success",
                        lesson="test lesson with spaces")
        store.add(e1)
        assert store.add(e2) is False


class TestLoadForPhase:
    def test_filters_by_phase(self, store):
        from scripts._experience import Experience
        store.add(Experience(category="merge", phase=3, context="C",
                             outcome="success", lesson="Phase 3 lesson."))
        store.add(Experience(category="enrich", phase=4, context="C",
                             outcome="success", lesson="Phase 4 lesson."))
        assert any(e.phase == 3 for e in store.load_for_phase(3))


class TestToContext:
    def test_returns_string_with_rollback(self, store):
        from scripts._experience import Experience
        store.add(Experience(category="merge", phase=3, context="C",
                             outcome="rollback", lesson="Test context."))
        ctx = store.to_context(3)
        assert isinstance(ctx, str) and "ROLLBACK" in ctx
