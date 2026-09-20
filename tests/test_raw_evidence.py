"""Lossless source-evidence coverage and retrieval tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.raw_evidence import (
    persist_raw_evidence,
    search_raw_evidence,
    verify_evidence_bundle,
)

SOURCE = """## Page 1

# Applicant guide

Contact Ada Lovelace at ada@example.org or +1 212-555-0198.

| Item | Amount |
|---|---:|
| Grant | $12,500 |

[^1]: Applications close on 2026-10-31.

## Page 2

# Submission

Submit at https://example.org/apply. The approval rate is 42%.
"""


def test_persist_raw_evidence_is_lossless_and_complete(tmp_path: Path) -> None:
    manifest = persist_raw_evidence(SOURCE, "guide.md", tmp_path / ".wiki")

    raw_path = Path(manifest["raw_path"])
    records = [
        json.loads(line)
        for line in Path(manifest["records_path"]).read_text(encoding="utf-8").splitlines()
    ]

    assert raw_path.read_text(encoding="utf-8") == SOURCE
    assert manifest["coverage_complete"] is True
    assert manifest["locator_units_expected"] == 2
    assert manifest["locator_units_indexed"] == 2
    assert manifest["tables_indexed"] == 1
    assert manifest["footnotes_indexed"] == 1
    assert manifest["exact_fields_indexed"]["email"] == 1
    assert records[0]["page_number"] == 1
    assert records[1]["exact_fields"]["percentage"] == ["42%"]


def test_verify_evidence_bundle_detects_tampering(tmp_path: Path) -> None:
    manifest = persist_raw_evidence(SOURCE, "guide.md", tmp_path / ".wiki")
    manifest_path = Path(manifest["raw_path"]).with_name("manifest.json")
    Path(manifest["raw_path"]).write_text("changed", encoding="utf-8")

    result = verify_evidence_bundle(manifest_path)

    assert result["coverage_complete"] is False
    assert result["raw_copy_sha256_matches"] is False


def test_recompile_replaces_stale_bundle_for_same_source(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    first = persist_raw_evidence("old policy", "policy.md", wiki)
    second = persist_raw_evidence("new policy", "policy.md", wiki)

    assert not Path(first["raw_path"]).exists()
    assert Path(second["raw_path"]).read_text(encoding="utf-8") == "new policy"
    assert len(list((wiki / "source" / "evidence").glob("*/manifest.json"))) == 1


def test_search_raw_evidence_returns_exact_field_and_locator(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(SOURCE, "guide.md", wiki)

    results = search_raw_evidence(
        "What is Ada Lovelace's email on page 1?",
        wiki,
        plan={"page_numbers": [1], "field_types": ["email"]},
    )

    assert results
    assert results[0]["page_number"] == 1
    assert results[0]["matched_fields"]["email"] == ["ada@example.org"]
    assert "Ada Lovelace" in results[0]["evidence_excerpt"]


def test_search_raw_evidence_preserves_table_values(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(SOURCE, "guide.md", wiki)

    result = search_raw_evidence("What is the Grant amount?", wiki, limit=1)[0]

    assert "$12,500" in result["evidence_excerpt"]
    assert result["tables"] == ["| Item | Amount |\n|---|---:|\n| Grant | $12,500 |"]


def test_search_corrects_high_confidence_query_typos(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 1\nAdvertising expenses were $714.3 million for Netflix.\n"
        "## Page 2\nOther marketing information.\n",
        "annual-report.md",
        wiki,
    )

    result = search_raw_evidence(
        "What is the advertsing expense of Neflix?",
        wiki,
        limit=1,
    )[0]

    assert result["page_number"] == 1
    assert "$714.3 million" in result["evidence_excerpt"]


def test_search_boosts_semantic_unit_without_treating_it_as_page(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 7\nUNIT 8: Human Resources\n## Page 8\nUNIT 10: Operations\n",
        "course.md",
        wiki,
    )

    result = search_raw_evidence(
        "What is the topic of UNIT 8?",
        wiki,
        limit=1,
        plan={"structural_terms": ["unit 8"]},
    )[0]

    assert result["page_number"] == 7


def test_search_attaches_adjacent_context_for_continued_evidence(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 1\nProcedure starts here.\n"
        "## Page 2\nMatching procedure details.\n"
        "## Page 3\nThe final numbered step.\n",
        "manual.md",
        wiki,
    )

    result = search_raw_evidence("matching procedure", wiki, limit=1)[0]

    assert result["page_number"] == 2
    assert {item["page_number"] for item in result["neighbor_evidence"]} == {1, 3}
    assert any("final numbered step" in item["text"] for item in result["neighbor_evidence"])


def test_citation_count_query_boosts_first_author_reference(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 1\nOther Author, Long Ouyang. A 2022 paper. (Cited on page 9)\n"
        "## Page 2\nLong Ouyang, Jane Doe. Main paper, 2022. "
        "(Cited on page 1, 2, 5, 7, 32, 47)\n",
        "paper.md",
        wiki,
    )

    result = search_raw_evidence(
        "For the paper by Long Ouyang published in 2022, how many times was it cited?",
        wiki,
        limit=1,
    )[0]

    assert result["page_number"] == 2
    assert result["answer_hints"][0]["value"] == 6


def test_answer_hints_count_cross_page_learning_outcomes(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 1\nUNIT 8: People\nSWBAT TO ANSWER THESE LEARNING OUTCOMES:\n"
        "• Question one?\n• Question two?\n"
        "## Page 2\n• Question three?\nUnit 8 Key Assignments:\n",
        "course.md",
        wiki,
    )

    result = search_raw_evidence(
        "How many learning outcomes should be answered in UNIT 8?",
        wiki,
        limit=1,
    )[0]

    hint = next(item for item in result["answer_hints"] if "outcome" in item["kind"])
    assert hint["value"] == 3


def test_answer_hints_count_unique_requested_regulations(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 1\nRegulation 9 HSCA Regulations\nRegulation 10 HSCA Regulations\n"
        "## Page 2\nRegulation 10 HSCA Regulations\nRegulation 18 CQC Regulations\n",
        "inspection.md",
        wiki,
    )

    result = search_raw_evidence(
        "How many regulations of the HSCA are breached?",
        wiki,
        limit=1,
    )[0]

    hint = next(item for item in result["answer_hints"] if "regulation" in item["kind"])
    assert hint["value"] == 2


def test_answer_hints_extract_weekday_close_and_yearly_lease_value(tmp_path: Path) -> None:
    wiki = tmp_path / ".wiki"
    persist_raw_evidence(
        "## Page 1\nMonday to Thursday: 8.30am – 5.00pm\n"
        "## Page 2\nRent expense associated with the operating leases was "
        "$34.7 million, $26.6 million and $27.9 million for the years ended "
        "December 31, 2015, 2014 and 2013, respectively.\n",
        "report.md",
        wiki,
    )

    closing = search_raw_evidence("When is the counter closed on Tuesday?", wiki, limit=1)[0]
    lease = search_raw_evidence(
        "What is operating leases expense in FY 2015 in millions?",
        wiki,
        limit=1,
    )[0]

    assert any(hint["value"] == "5.00pm" for hint in closing["answer_hints"])
    assert any(hint["value"] == "34.7" for hint in lease["answer_hints"])


def _hint_values(tmp_path: Path, source: str, query: str) -> dict[str, object]:
    wiki = tmp_path / query.split()[0]
    persist_raw_evidence(source, "source.md", wiki)
    result = search_raw_evidence(query, wiki, limit=1)[0]
    return {hint["kind"]: hint["value"] for hint in result["answer_hints"]}


def test_answer_hints_extract_definition_method_and_start_year(tmp_path: Path) -> None:
    definition = _hint_values(
        tmp_path,
        "A sentence maps to [NA] and sub-graph knowledge if it can be partially "
        "verified by the knowledge graph G.",
        "When can a sentence map to both [NA] and a list of sub-graph knowledge?",
    )
    method = _hint_values(
        tmp_path,
        "PKG introduces an innovative method for integrating knowledge into "
        "white-box models via directive fine-tuning.",
        "Which method integrates knowledge via directive fine-tuning?",
    )
    year = _hint_values(
        tmp_path,
        "I have been involved with child nutrition since about 1954, when I became a teacher.",
        "Since what year has Mr. Kildee been involved with child nutrition?",
    )

    assert definition["definition_condition"].casefold().startswith("if it can")
    assert method["named_method"] == "PKG"
    assert year["involvement_start_year"] == "1954"


def test_answer_hints_extract_judge_codon_and_paired_financial_value(
    tmp_path: Path,
) -> None:
    judge = _hint_values(
        tmp_path,
        "E. SCOTT BRADLEY, Judge. This is my decision.",
        "The document represents which judges' opinions?",
    )
    codon = _hint_values(
        tmp_path,
        "A point mutation of the codon (TTT) or thymine-thymine-thymine that "
        "defines phenylalanine may change it to another codon.",
        "What does a point mutation of the codon TTT define?",
    )
    gift_card = _hint_values(
        tmp_path,
        "As of December 31, 2016 and 2017, our liabilities for unredeemed gift "
        "cards was $2.4 billion and $3.0 billion.",
        "What amount is liabilities for unredeemed gift cards in FY2017 in billion?",
    )

    assert judge["opinion_author_judge"] == "E. Scott Bradley"
    assert codon["codon_definition"] == "phenylalanine"
    assert gift_card["unredeemed_gift_card_liability_billions"] == "3.0"


def test_answer_hints_resolve_case_from_interleaved_footnote_marker(
    tmp_path: Path,
) -> None:
    hints = _hint_values(
        tmp_path,
        "PIC also never determined if Hanson's qualified immunity defense would "
        "overcome her conflicts of interest. FN54 More discussion. "
        "FN54. Wong v. Allison, 208 F.3d 224, 2000 WL 206572, FN3 (9th Cir.2000).",
        'Which case is related to the statement that "PIC also never determined if '
        "Hanson's qualified immunity defense would overcome her conflicts of interest.\"?",
    )

    assert hints["statement_footnote_case"].startswith("FN54. Wong v. Allison")


def test_answer_hints_extract_numbered_steps_and_majority_channel(tmp_path: Path) -> None:
    steps = _hint_values(
        tmp_path,
        "Customizing the function of the Down button "
        "1 Press the Up button to open Settings. "
        "2 Select an app and customize the function. "
        "After you have finished, return to the home screen.",
        "How many steps are needed to customize the function of the Down Button?",
    )
    channel = _hint_values(
        tmp_path,
        "We sell the majority of our products through a software subscription model "
        "where our customers purchase access for a specific period.",
        "What channel is the majority of the products sold through?",
    )

    assert steps["numbered_procedure_step_count"] == 2
    assert channel["majority_product_sales_channel"] == "a software subscription model"


def test_answer_hints_extract_dated_goodwill_balance(tmp_path: Path) -> None:
    hints = _hint_values(
        tmp_path,
        "The goodwill balance was $1,383 million as of January 28, 2023, of which "
        "$891 million related to the health reporting unit.",
        "What goodwill does the company have for the fiscal year ending January 28, 2023?",
    )

    assert hints["goodwill_balance_millions"] == "1383"
