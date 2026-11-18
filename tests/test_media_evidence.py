"""Regression coverage for evidence lost by rendered-text-only ingestion."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from scripts.chart_evidence import chart_calculation_context, exact_displayed_count
from scripts.native_document import pdf_sections, read_pptx
from scripts.raw_evidence import (
    attach_reviewed_visual_evidence,
    persist_raw_evidence,
    search_raw_evidence,
    verify_evidence_bundle,
)

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "media_workflows" / "fixtures"


def test_editable_deck_preserves_branch_direction_and_native_cells() -> None:
    content, fallback = read_pptx(FIXTURES / "northstar-release.pptx")
    assert not fallback
    assert re.findall(r"^## Slide (\d+)$", content, re.M) == [str(i) for i in range(1, 9)]
    assert "Approved? → Canary deploy [Yes]" in content
    assert "Policy Engine → Metrics Store" in content
    assert "Service Lead → Support Team" in content
    assert "| SEV-B | 36 | Identity |" in content
    assert "Migration | W2–W3" in content
    assert "| Sep | 36 |" in content
    assert "| Platform | 54 | 54% |" in content


def test_mixed_slide_retains_native_chart_with_same_slide_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import compile_v2

    modified = tmp_path / "mixed.pptx"
    with (
        zipfile.ZipFile(FIXTURES / "northstar-release.pptx") as original,
        zipfile.ZipFile(modified, "w") as copy,
    ):
        for name in original.namelist():
            data = original.read(name)
            if name == "ppt/slides/slide7.xml":
                ns = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
                slide = ET.fromstring(data)
                tree = slide.find(f"./{ns}cSld/{ns}spTree")
                assert tree is not None
                ET.SubElement(tree, ns + "pic")
                data = ET.tostring(slide)
            copy.writestr(name, data)
    _, needs_vision = read_pptx(modified)
    assert needs_vision == [7]
    optical = "## Page 7\n\nPrinted chart note\n\n## Page 8\nPie note"

    def render_slides(source: Path) -> str:
        assert source == modified
        return optical

    monkeypatch.delenv("LLM_WIKI_PPTX_OCR", raising=False)
    monkeypatch.setattr(compile_v2, "_read_paginated_document_optically", render_slides)
    merged, _ = compile_v2.read_source_content(modified)
    slide7 = merged.split("## Slide 7", 1)[1].split("## Slide 8", 1)[0]
    assert "| Sep | 36 |" in slide7
    assert "Printed chart note" in slide7
    assert "Pie note" not in slide7

    monkeypatch.setenv("LLM_WIKI_PPTX_OCR", "1")
    assert compile_v2.read_source_content(modified)[0] == optical


def test_pdf_continuation_retains_all_rows_and_code_scope() -> None:
    pytest.importorskip("fitz")
    pages = dict(pdf_sections(FIXTURES / "harbor-capacity.pdf"))
    for page in (1, 2, 3):
        assert "| Region | Workers | Cost (USD) |" in pages[page]
    assert "| Maple | 24 | 840 |" in pages[2]
    assert "| Birch | 42 | 1470 |" in pages[3]
    assert "\n        return min(64, 2 ** attempt)\n" in pages[1]
    assert "\n    if status == 503 and attempt < 3:\n        return 5" in pages[2]
    assert pages[4].count("### PDF table:") == 4
    assert "| Export | Parker |" in pages[4]
    assert "| June | 75 |" in pages[5]


def test_reviewed_observations_are_searchable_and_original_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import query

    raw = "## Page 1\n\nOCR heading only\n\n## Page 2\nOther heading"
    manifest = persist_raw_evidence(raw, "image.jpg", tmp_path)
    path = Path(manifest["raw_path"])
    manifest_path = path.with_name("manifest.json")
    assert search_raw_evidence("Gateway Router", tmp_path) == []
    attach_reviewed_visual_evidence(manifest_path, "## Page 1\nGateway → Router", tmp_path)
    assert path.read_text() == raw
    assert verify_evidence_bundle(manifest_path)["coverage_complete"]
    monkeypatch.setenv("LLM_WIKI_SEARCH_STREAMS", "raw")
    monkeypatch.setattr(query, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(query, "PAGES_DIR", tmp_path / "pages")
    hits = query.search_wiki("What follows Gateway in the architecture?")
    assert hits[0]["locator"] == "Page 1"
    assert "Gateway → Router" in query._format_page_context(hits[0], 1)
    with pytest.raises(ValueError, match="existing source pages"):
        attach_reviewed_visual_evidence(manifest_path, "## Page 9\nUnverified", tmp_path)


def test_ocr_table_is_projected_without_rewriting_html(tmp_path: Path) -> None:
    raw = (
        "## Page 1\n\n<table><tr><td>Queue</td><td>Owner</td><td></td></tr>"
        "<tr><td>Ingest</td><td colspan='2'>Marin</td></tr></table>"
    )
    manifest = persist_raw_evidence(raw, "queues.jpg", tmp_path)
    result = search_raw_evidence("Ingest owner", tmp_path)[0]
    assert Path(manifest["raw_path"]).read_text() == raw
    assert re.search(r"\| Ingest \| Marin \|", result["tables"][0])


def test_chart_calculation_uses_values_from_the_same_series() -> None:
    deck, _ = read_pptx(FIXTURES / "northstar-release.pptx")
    result = chart_calculation_context("What share of the total was in October?", deck)
    assert "24 + 36 + 60 = 120" in result
    assert "Oct: 50%" in result
    assert "54 + 27 + 19" not in result


def test_displayed_count_abstains_when_two_series_fit() -> None:
    deck, _ = read_pptx(FIXTURES / "northstar-release.pptx")
    chart = deck.split("## Slide 7", 1)[1].split("## Slide 8", 1)[0]
    page = {"type": "source_evidence", "id": "source/one", "locator": "Slide 7", "text": chart}
    question = "How many incidents closed across all three displayed months?"
    answer = exact_displayed_count(question, [page])
    assert "**120**" in answer and "(/source/one.md)" in answer
    from scripts.query import verify_answer_evidence

    assert verify_answer_evidence(answer, [page], question)["status"] == "pass"
    assert not exact_displayed_count(question, [page, {**page, "id": "source/two"}])
    assert not exact_displayed_count(
        "How many incidents closed across all four displayed months?", [page]
    )


@pytest.mark.parametrize("mode", ["agent", "llm"])
def test_native_chart_total_passes_wiki_writeback_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    from scripts import query

    deck, _ = read_pptx(FIXTURES / "northstar-release.pptx")
    chart = deck.split("## Slide 7", 1)[1].split("## Slide 8", 1)[0]
    persist_raw_evidence("## Slide 7" + chart, "northstar-release.pptx", tmp_path)
    monkeypatch.setenv("LLM_WIKI_SEARCH_STREAMS", "raw")
    monkeypatch.setattr(query, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(query, "PAGES_DIR", tmp_path / "pages")
    monkeypatch.setattr(query, "call_llm", lambda *_a, **_k: pytest.fail("Chart is calculable"))
    question = "How many incidents closed across all three displayed months?"
    result = query.query_wiki(question, mode=mode, file_back=True, multi_hop=False)
    if mode == "agent":
        task = Path(result["answer_task"])
        try:
            assert result["file_back_skipped"] == "pending_agent_verification"
            answer = exact_displayed_count(question, query.search_wiki(question))
            wrong = answer.replace("**120**", "**121**")
            rejected = query.verify_agent_answer(task, wrong)
            assert rejected["file_back_skipped"] == "verification_failed"
            assert not (tmp_path / "pages").exists()
            result = query.verify_agent_answer(task, answer)
        finally:
            task.unlink(missing_ok=True)
    assert result["verification"]["status"] == "pass"
    assert "**120**" in Path(result["filed"]).read_text(encoding="utf-8")
