from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.benchmark_pageindex import (
    case_key,
    corpus_fingerprint,
    ensure_document_evidence,
    extract_json_object,
    load_dataset,
    load_official_judge_prompt,
    metrics,
    recover_compile_records,
    runtime_fingerprint,
    select_cases,
    wiki_cache_dir,
)


def _dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    (root / "documents").mkdir(parents=True)
    (root / "documents" / "a.pdf").write_bytes(b"a")
    (root / "documents" / "b.pdf").write_bytes(b"b")
    questions = [
        {"doc_id": "a.pdf", "question": "A1", "answer": "1", "answer_format": "Int"},
        {"doc_id": "a.pdf", "question": "A2", "answer": "2", "answer_format": "Int"},
        {"doc_id": "b.pdf", "question": "B1", "answer": "3", "answer_format": "Int"},
    ]
    documents = [{"doc_id": "a.pdf", "pages": 1}, {"doc_id": "b.pdf", "pages": 1}]
    (root / "questions.json").write_text(json.dumps(questions), encoding="utf-8")
    (root / "documents.json").write_text(json.dumps(documents), encoding="utf-8")
    return root


def test_load_and_select_preserve_document_boundary(tmp_path: Path) -> None:
    questions, documents = load_dataset(_dataset(tmp_path))
    assert len(documents) == 2
    assert [row["question"] for row in select_cases(questions, 1, None)] == ["A1", "A2"]
    assert [row["question"] for row in select_cases(questions, None, 2)] == ["A1", "A2"]


def test_load_dataset_rejects_missing_document(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    (root / "documents" / "b.pdf").unlink()
    with pytest.raises(ValueError, match="missing documents"):
        load_dataset(root)


def test_wiki_cache_key_changes_with_revision_and_model(tmp_path: Path) -> None:
    document = tmp_path / "a.pdf"
    document.write_bytes(b"document")
    first = wiki_cache_dir(tmp_path, document, "abc123", {"model": "one"})
    second = wiki_cache_dir(tmp_path, document, "def456", {"model": "one"})
    third = wiki_cache_dir(tmp_path, document, "abc123", {"model": "two"})
    assert len({first, second, third}) == 3


def test_corpus_fingerprint_is_stable_and_filterable(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "b.pdf").write_bytes(b"b")
    (documents / "a.pdf").write_bytes(b"a")
    assert corpus_fingerprint(documents) == corpus_fingerprint(documents)
    assert corpus_fingerprint(documents, {"a.pdf"}) != corpus_fingerprint(documents)


def test_runtime_fingerprint_is_sha256() -> None:
    assert len(runtime_fingerprint()) == 64
    int(runtime_fingerprint(), 16)


def test_recover_compile_records_uses_newest_success(tmp_path: Path) -> None:
    old = tmp_path / "wikis" / "old" / "benchmark_compile.json"
    new = tmp_path / "wikis" / "new" / "benchmark_compile.json"
    failed = tmp_path / "wikis" / "failed" / "benchmark_compile.json"
    for path in (old, new, failed):
        path.parent.mkdir(parents=True)
    old.write_text('{"source":"a.pdf","status":"ok","pages_created":1}')
    new.write_text('{"source":"a.pdf","status":"ok","pages_created":2}')
    failed.write_text('{"source":"b.pdf","status":"failed"}')
    old.touch()
    new.touch()
    old_time = old.stat().st_mtime - 10
    os.utime(old, (old_time, old_time))

    records = recover_compile_records(tmp_path, {"a.pdf", "b.pdf"})

    assert len(records) == 1
    assert records[0]["pages_created"] == 2


def test_ensure_document_evidence_backfills_then_reuses(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text(
        "## Page 1\nContact test@example.org.\n\n## Page 2\nSecond page.\n",
        encoding="utf-8",
    )
    wiki = tmp_path / ".wiki"

    first = ensure_document_evidence(document, wiki)
    second = ensure_document_evidence(document, wiki)

    assert first["cached"] is False
    assert first["coverage_complete"] is True
    assert first["locator_units_indexed"] == 2
    assert second["cached"] is True
    assert second["manifest"] == first["manifest"]


def test_extract_json_object_accepts_fenced_and_wrapped_json() -> None:
    assert extract_json_object('```json\n{"equivalent": true}\n```')["equivalent"] is True
    assert extract_json_object('result: {"equivalent": false}')["equivalent"] is False


def test_load_official_judge_prompt_without_executing_module(tmp_path: Path) -> None:
    judge = tmp_path / "judge.py"
    judge.write_text(
        'PROMPT = "Q={question} A={answer} F={answer_format} R={response}"\n'
        'raise RuntimeError("must not execute")\n',
        encoding="utf-8",
    )
    prompt = load_official_judge_prompt(judge)
    assert prompt.startswith("Q={question}")


def test_metrics_reports_accuracy_and_latency() -> None:
    rows = [
        {
            "doc_id": "a.pdf",
            "question": " A   question ",
            "doc_type": "financial_report",
            "query_seconds": 1.0,
            "llm_judge": {"equivalent": True},
        },
        {
            "doc_id": "b.pdf",
            "question": "B",
            "doc_type": "manual",
            "query_seconds": 3.0,
            "llm_judge": {"equivalent": False},
        },
    ]
    result = metrics(
        rows,
        {
            "compile": [
                {"source": "a.pdf", "seconds": 2, "pages_created": 3, "cached": False},
                {"source": "b.pdf", "seconds": 4, "pages_created": 5, "cached": True},
            ]
        },
    )
    assert result["accuracy"] == 0.5
    assert result["query_latency_seconds"]["mean"] == 2.0
    assert result["indexing"]["seconds_total"] == 6
    assert result["indexing"]["knowledge_pages"] == 8
    assert case_key(rows[0]) == ("a.pdf", "A question")
