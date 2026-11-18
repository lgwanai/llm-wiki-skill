"""Run the media evidence benchmark from the repository root.

Baseline inputs are the exact raw artifacts produced by the prior version's
Paddle agent ingest. --baseline-repo points to the prior revision for indexing
and search. No attached report excerpts are sent to an external answer model.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from questions import CASES

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
REPO = HERE.parents[1]
NAMES = {"ppt": "northstar-release.pptx", "pdf": "harbor-capacity.pdf", "jpg": "orion-runbook.jpg"}
REFUSAL = (
    r"不足|没有|未(?:提供|说明|标注|给出|披露)|无法|"
    r"not (?:specified|provided|contain|indicated|stated)|insufficient|"
    r"does not (?:name|specify|identify|provide|say)"
)


def normalized(value: str) -> str:
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    return re.sub(r"\s+", " ", value).casefold()


def supports(case: dict[str, Any], results: list[dict[str, Any]]) -> bool:
    for number, fragments in case["support"].items():
        candidates = []
        for result in results:
            if result["source_name"] != case["name"]:
                continue
            if result["page_number"] == number:
                candidates.append(
                    " ".join(
                        [
                            result["text"],
                            result.get("reviewed_visual", ""),
                            *result.get("tables", []),
                        ]
                    )
                )
            candidates.extend(
                n["text"] for n in result.get("neighbor_evidence", []) if n["page_number"] == number
            )
        if not any(
            all(normalized(fragment) in normalized(body) for fragment in fragments)
            for body in candidates
        ):
            return False
    return bool(case["support"])


def score_answer(answer: str, patterns: tuple[str, ...]) -> bool:
    body = re.sub(r"\[[^\]]*\]\([^)]*\)", "", answer)
    return all(
        re.search(r"(?<!\d)(?<!\d\.)(?:" + pattern + r")(?!\d|\.\d)", body, re.I)
        for pattern in patterns or (REFUSAL,)
    )


def p95(values: list[float]) -> float:
    return sorted(values)[min(len(values) - 1, int(0.95 * len(values)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--ppt-ocr", type=Path, default=HERE / "baselines" / "ppt-ocr.md")
    parser.add_argument("--jpg-ocr", type=Path, default=HERE / "baselines" / "jpg-ocr.md")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--reviewed-image", action="store_true")
    args = parser.parse_args()
    root = args.baseline_repo.resolve() if args.baseline_repo else REPO
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(root / "scripts"), str(root)]
    os.environ["LLM_WIKI_DIR"] = str(workspace / "wiki")
    os.environ["LLM_WIKI_SEARCH_STREAMS"] = "raw"
    os.environ["LLM_WIKI_PDF_TEXT_LAYER"] = "1"
    os.environ.pop("LLM_WIKI_PPTX_OCR", None)
    from compile_v2 import read_source_content
    from raw_evidence import persist_raw_evidence, search_raw_evidence

    query_module = importlib.import_module("query")
    times = {}
    documents = dict(NAMES)
    if args.report:
        documents["report"] = args.report.name
    for doc, name in documents.items():
        start = time.perf_counter()
        if doc == "jpg":
            raw = args.jpg_ocr.read_text()
        elif doc == "ppt" and args.baseline_repo:
            raw = args.ppt_ocr.read_text()
        elif doc in {"pdf", "report"} and not args.baseline_repo:
            # Measure the native evidence layer separately from production
            # OCR and Agent routing, as in the historical benchmark.
            from native_document import pdf_sections

            source = args.report if doc == "report" else FIXTURES / name
            raw = "\n\n".join(f"## Page {n}\n\n{body}" for n, body in pdf_sections(source))
        else:
            raw, _ = read_source_content(args.report if doc == "report" else FIXTURES / name)
        extracted = time.perf_counter()
        manifest = persist_raw_evidence(raw, name, workspace / "wiki")
        if doc == "jpg" and args.reviewed_image:
            from raw_evidence import attach_reviewed_visual_evidence

            manifest = attach_reviewed_visual_evidence(
                Path(manifest["raw_path"]).with_name("manifest.json"),
                (FIXTURES / "orion-reviewed.md").read_text(),
                workspace / "wiki",
            )
        times[doc] = {
            "read_ms": round((extracted - start) * 1000, 2),
            "index_ms": round((time.perf_counter() - extracted) * 1000, 2),
            "pages": manifest["locator_units_indexed"],
            "tables": manifest["tables_indexed"],
        }
    cases = [{**c, "name": documents[c["doc"]]} for c in CASES if c["doc"] in documents]
    cold_start = time.perf_counter()
    search_raw_evidence(cases[0]["question"], workspace / "wiki", limit=5)
    cold = (time.perf_counter() - cold_start) * 1000
    rows = []
    answer_jobs = []
    for case in cases:
        question = case["question"]
        tick = time.perf_counter()
        results = query_module.search_wiki(question, limit=5)
        elapsed = (time.perf_counter() - tick) * 1000
        expected = set(case["support"])
        row = {
            "id": case["id"],
            "doc": case["doc"],
            "category": case["category"],
            "question": question,
            "top": [[item["source_name"], item["page_number"]] for item in results],
            "hit1": (
                bool(
                    results
                    and results[0]["source_name"] == case["name"]
                    and results[0]["page_number"] in expected
                )
                if expected
                else None
            ),
            "all_pages_top5": (
                all(
                    any(r["source_name"] == case["name"] and r["page_number"] == n for r in results)
                    for n in expected
                )
                if expected
                else None
            ),
            "complete_evidence": supports(case, results) if expected else None,
            "retrieval_ms": round(elapsed, 3),
        }
        rows.append(row)
        if args.answers and case["doc"] != "report":
            safe_results = [
                result for result in results if result["source_name"] != documents.get("report")
            ]
            answer_jobs.append((row, case, safe_results))

    if answer_jobs:

        def answer_one(job: tuple) -> None:
            row, case, results = job
            tick = time.perf_counter()
            try:
                answer = query_module.synthesize_answer(case["question"], results)
                row.update(
                    answer=answer,
                    answer_pass=score_answer(answer, case["answer"]),
                    synthesis_ms=round((time.perf_counter() - tick) * 1000, 2),
                    cited=bool(re.search(r"\]\(/?source/evidence/", answer)),
                )
            except Exception as exc:
                row["answer_error"] = type(exc).__name__ + ": " + str(exc)[:150]
            print(row["id"], row.get("answer_pass"), row.get("synthesis_ms"), flush=True)

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(answer_one, answer_jobs))

    grouped = {}
    for doc in documents:
        group = [row for row in rows if row["doc"] == doc]
        positives = [row for row in group if row["hit1"] is not None]
        measured = [row for row in group if "answer_pass" in row]
        grouped[doc] = {
            "questions": len(group),
            "with_evidence": len(positives),
            **{
                key: sum(bool(row[key]) for row in positives)
                for key in ("hit1", "all_pages_top5", "complete_evidence")
            },
            "answer_count": len(measured),
            "answer_pass": sum(row["answer_pass"] for row in measured),
        }
    durations = [row["retrieval_ms"] for row in rows]
    output = {
        "ingest": times,
        "retrieval_p50_ms": statistics.median(durations),
        "retrieval_p95_ms": p95(durations),
        "cold_raw_ms": round(cold, 3),
        "summary": grouped,
        "cases": rows,
    }
    (workspace / "results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in output.items() if k != "cases"}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
