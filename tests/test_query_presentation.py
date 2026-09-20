"""Regression: structured OKF evidence must survive CLI output and multi-hop ranking."""

import json
import sys
from pathlib import Path

import dream

from scripts import query, query_multihop, wiki
from scripts.query_display import exact_subject_match, query_subject, read_snippet, source_detail


def test_table_separator_never_becomes_snippet(tmp_path: Path) -> None:
    page = tmp_path / "theorem.md"
    page.write_text(
        "---\ntitle: 勾股定理\n"
        "description: 两直角边长的平方和等于斜边长的平方，即 a²+b²=c²。\n"
        "---\n# 勾股定理\n\n| 属性 | 值 |\n|------|-----|\n"
        "| 定理 | 两直角边长的平方和等于斜边长的平方 |\n"
    )
    snippet = read_snippet(str(page), "什么是勾股定理")
    assert "a²+b²=c²" in snippet
    assert "|---" not in snippet
    detail = source_detail({"id": "concepts/theorem", "path": str(page)}, "什么是勾股定理")
    assert detail["title"] == "勾股定理"
    assert detail["snippet"] == snippet


def test_table_values_are_readable_without_description(tmp_path: Path) -> None:
    page = tmp_path / "density.md"
    page.write_text(
        "# 密度\n\n| 属性 | 值 |\n| :--- | ---: |\n"
        "| 定义 | 密度是单位体积物质的质量 |\n\n"
        "```md\n这是不应该出现在摘要中的代码示例。\n```\n"
    )
    assert read_snippet(str(page), "什么是密度") == "定义：密度是单位体积物质的质量"


def test_subject_matches_whole_okf_title_and_legacy_alias(tmp_path: Path) -> None:
    page = tmp_path / "definition.md"
    history = tmp_path / "history.md"
    legacy = tmp_path / "legacy.md"
    page.write_text("---\ntitle: 勾股定理\n---\nDefinition")
    history.write_text("---\ntitle: 勾股定理史话\n---\nHistory")
    legacy.write_text("---\nname: Density\naliases: [Mass density]\n---\nDefinition")
    for question in ["什么是勾股定理", "勾股定理是什么？", "勾股定理的定义是什么？", "勾股定理"]:
        assert exact_subject_match(question, str(page))
        assert not exact_subject_match(question, str(history))
    assert exact_subject_match("What is mass density?", str(legacy))
    assert query_subject("勾股定理与逆定理的区别") == "勾股定理与逆定理的区别"


def test_multihop_uses_final_relevance_not_stale_rrf_score() -> None:
    candidates = [
        {"id": "definition", "path": "definition.md", "score": 0.0387, "rerank_score": 1.49},
        {"id": "history", "path": "history.md", "score": 0.0390, "rerank_score": 1.00},
    ]
    ranked = query_multihop.run_multi_hop(
        "什么是勾股定理",
        lambda *_: candidates,
        lambda _: "勾股定理指出直角三角形两直角边的平方和等于斜边的平方。",
        max_hops=1,
        limit=2,
    )
    assert ranked[0]["id"] == "definition"
    assert ranked[0]["single_hop_score"] == 1.49


def test_exact_subject_participates_in_ranking_without_registry(tmp_path: Path) -> None:
    page = tmp_path / "theorem.md"
    history = tmp_path / "history.md"
    page.write_text("---\ntitle: 勾股定理\n---\nDefinition")
    history.write_text("---\ntitle: 勾股定理史话\n---\nHistory")
    candidates = [
        {"id": "history", "path": str(history), "score": 0.04},
        {"id": "theorem", "path": str(page), "score": 0.035},
    ]
    ranked = query.rerank_results("什么是勾股定理", candidates, {"intent": "fact"})
    assert ranked[0]["id"] == "theorem"


def test_empty_search_has_structured_empty_sources(monkeypatch) -> None:
    monkeypatch.setattr(query, "search_wiki", lambda *a, **kw: [])
    monkeypatch.setattr(query, "get_query_config", lambda: {"multi_hop_enabled": False})
    result = query.query_wiki("no-matching-concept", synthesis=False)
    assert result["source_details"] == []
    assert result["format"] == "fast"
    assert "未找到相关知识页" in result["answer"]


def test_cli_json_keeps_progress_on_stderr(monkeypatch, capsys) -> None:
    def answer(*args, **kwargs) -> dict:
        print("Reading knowledge pages...")
        return {"success": True, "answer": "Readable answer", "source_details": []}

    monkeypatch.setattr(wiki, "cmd_query", answer)
    monkeypatch.setattr(dream, "cancel_active_dream", lambda *_: None)
    monkeypatch.setattr(dream, "log_query", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["wiki", "query", "question", "--json"])
    wiki.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out)["answer"] == "Readable answer"
    assert "Reading knowledge pages" in captured.err


def test_excerpt_preserves_math_operators_and_subscripts(tmp_path: Path) -> None:
    page = tmp_path / "formula.md"
    page.write_text("# Formula\n\n**Formula**: a*b = c_d; a < b > c.\n")
    snippet = read_snippet(str(page), "Formula")
    assert "a*b = c_d; a < b > c" in snippet
    assert "**" not in snippet


def test_explicit_llm_mode_generates_answer_with_legacy_synthesis_disabled(
    monkeypatch, tmp_path
) -> None:
    page = tmp_path / "concept.md"
    page.write_text("# Concept\n\nActual evidence supports an answer.")
    monkeypatch.setattr(
        query, "get_query_config", lambda: {"llm_synthesis": False, "multi_hop_enabled": False}
    )
    monkeypatch.setattr(
        query,
        "search_wiki",
        lambda *a, **kw: [{"id": "concept", "path": str(page), "type": "Concept", "score": 1}],
    )
    monkeypatch.setattr(query, "synthesize_answer", lambda *a, **kw: "Synthesized answer")
    result = query.query_wiki("question", mode="llm")
    assert result["answer_text"] == "Synthesized answer"
    assert result["format"] != "fast"
    assert result["source_details"]
    raw = query.query_wiki("question", mode="llm", synthesis=False)
    assert raw["format"] == "fast"


def test_structured_answer_excludes_automatic_source_gallery(monkeypatch, tmp_path) -> None:
    page = tmp_path / "concept.md"
    page.write_text("# Concept\n\nEvidence.")
    image = {"markdown": "![raw](/assets/raw.png)", "path": "/assets/raw.png"}
    monkeypatch.setattr(query, "get_query_config", lambda: {"multi_hop_enabled": False})
    monkeypatch.setattr(
        query,
        "search_wiki",
        lambda *a, **kw: [{"id": "concept", "path": str(page), "type": "Concept", "score": 1}],
    )
    monkeypatch.setattr(
        query, "_attach_page_images", lambda pages: [{**p, "images": [image]} for p in pages]
    )
    monkeypatch.setattr(query, "synthesize_answer", lambda *a, **kw: "Final answer")
    result = query.query_wiki("question", mode="llm")
    assert result["answer_text"] == "Final answer"
    assert "raw.png" in result["answer"]
    assert result["source_details"][0]["images"] == [image]
