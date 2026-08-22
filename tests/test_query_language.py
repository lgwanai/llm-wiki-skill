"""Tests for no-model cross-language retrieval expansion."""

from __future__ import annotations

from pathlib import Path

from scripts import query_language


def test_builtin_bridge_translates_operational_subgoal(tmp_path: Path) -> None:
    variants = query_language.cross_language_variants(
        "给出事故恢复的重试水位标记",
        tmp_path / "pages",
    )

    assert any("incident recovery" in variant for variant in variants)
    assert any("retry" in variant and "watermark" in variant for variant in variants)


def test_bridge_learns_bilingual_aliases_from_canonical_page(tmp_path: Path) -> None:
    pages = tmp_path / ".wiki" / "pages" / "concepts"
    pages.mkdir(parents=True)
    (pages / "incident-runbook.md").write_text(
        "---\ntype: concept\ntitle: Incident Runbook\n"
        "aliases: [事故运行手册]\n---\n# Incident Runbook\n",
        encoding="utf-8",
    )

    variants = query_language.cross_language_variants(
        "事故运行手册中的恢复步骤",
        pages.parent,
    )

    assert any("Incident Runbook" in variant for variant in variants)


def test_custom_wiki_glossary_extends_bridge(tmp_path: Path) -> None:
    pages = tmp_path / ".wiki" / "pages"
    pages.mkdir(parents=True)
    glossary = tmp_path / ".wiki" / "query_lexicon.yaml"
    glossary.write_text(
        "terms:\n  熔断窗口: circuit breaker window\n",
        encoding="utf-8",
    )

    variants = query_language.cross_language_variants(
        "熔断窗口是多少",
        pages,
        glossary,
    )

    assert any("circuit breaker window" in variant for variant in variants)
