#!/usr/bin/env python3
"""benchmark.py — RAG/knowledge-base benchmark runner.

Implements two mainstream evaluation methods:

1. BEIR/MTEB-style retrieval metrics:
   HitRate@K, Precision@K, Recall@K, MRR@K, NDCG@K.

2. RAGAS-style lightweight end-to-end metrics:
   Context Precision, Context Recall, Answer Relevancy, Faithfulness.

The RAGAS-style implementation is deterministic and dependency-free. It is a
practical local approximation for regression tests, not a replacement for
LLM-as-judge RAGAS in final model evaluations.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from query import multi_hop_search, read_page_content, search_wiki


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[\w\u4e00-\u9fff]+", text)
        if len(token.strip()) >= 2
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
        if not case.get("query"):
            raise ValueError(f"{path}:{line_no}: missing query")
        cases.append(case)
    return cases


def _dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def _retrieved_ids(results: list[dict]) -> list[str]:
    return [r.get("id") or r.get("file") or Path(r.get("path", "")).stem for r in results]


def _id_matches(actual: str, expected: str) -> bool:
    """Match canonical Concept IDs while accepting legacy filename-only qrels."""
    return actual == expected or actual.endswith(f"/{expected}")


def _matches_any(actual: str, expected: set[str]) -> bool:
    return any(_id_matches(actual, item) for item in expected)


def _search_case(case: dict[str, Any], k: int) -> list[dict]:
    kwargs: dict[str, Any] = {"limit": k}
    if case.get("allowed_scopes"):
        kwargs["allowed_scopes"] = case["allowed_scopes"]
    if case.get("exclude_statuses"):
        kwargs["exclude_statuses"] = case["exclude_statuses"]
    if case.get("multi_hop"):
        return multi_hop_search(
            case["query"],
            max_hops=int(case.get("max_hops", 3)),
            **kwargs,
        )
    return search_wiki(case["query"], **kwargs)


def _percentile(values: list[float], percentile: float) -> float:
    """Return a deterministic nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def run_retrieval_benchmark(cases: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """Run BEIR/MTEB-style retrieval benchmark."""
    details = []
    hit_rates = []
    precisions = []
    recalls = []
    mrrs = []
    ndcgs = []
    complete_recalls = []
    leakage_rates = []
    subgoal_coverages = []
    complete_subgoal_coverages = []
    topic_drift_rates = []
    latencies_ms = []
    scenarios: dict[str, list[dict[str, float]]] = {}

    for case in cases:
        query_text = case["query"]
        expected = set(case.get("expected_pages", []))
        started = time.perf_counter()
        results = _search_case(case, k)
        latency_ms = (time.perf_counter() - started) * 1000
        retrieved = _retrieved_ids(results)
        relevant = [1 if _matches_any(rid, expected) else 0 for rid in retrieved[:k]]
        forbidden = set(case.get("forbidden_pages", []))
        leaked = {rid for rid in retrieved[:k] if _matches_any(rid, forbidden)}
        expected_groups = [
            set(group)
            for group in case.get(
                "expected_groups",
                [[page] for page in case.get("expected_pages", [])],
            )
            if group
        ]
        covered_groups = sum(
            1
            for group in expected_groups
            if any(_matches_any(page, group) for page in retrieved[:k])
        )
        subgoal_coverage = (
            covered_groups / len(expected_groups) if expected_groups else 1.0
        )
        complete_subgoal_coverage = 1.0 if subgoal_coverage == 1.0 else 0.0
        strict_relevance = set(case.get("strict_relevant_pages", []))
        drift = (
            len(
                [
                    page
                    for page in retrieved[:k]
                    if not _matches_any(page, strict_relevance)
                ]
            )
            / len(retrieved[:k])
            if strict_relevance and retrieved[:k]
            else 0.0
        )

        hit = 1.0 if any(relevant) else 0.0
        precision = sum(relevant) / k if k else 0.0
        recall = sum(relevant) / len(expected) if expected else 0.0
        first_rank = next((i + 1 for i, rel in enumerate(relevant) if rel), None)
        mrr = 1.0 / first_rank if first_rank else 0.0
        ideal_rels = [1] * min(len(expected), k)
        ndcg = _dcg(relevant) / _dcg(ideal_rels) if ideal_rels else 0.0
        complete_recall = (
            1.0
            if expected
            and all(
                any(_id_matches(actual, target) for actual in retrieved[:k])
                for target in expected
            )
            else 0.0
        )
        leakage = len(leaked) / len(forbidden) if forbidden else 0.0

        hit_rates.append(hit)
        precisions.append(precision)
        recalls.append(recall)
        mrrs.append(mrr)
        ndcgs.append(ndcg)
        complete_recalls.append(complete_recall)
        leakage_rates.append(leakage)
        subgoal_coverages.append(subgoal_coverage)
        complete_subgoal_coverages.append(complete_subgoal_coverage)
        if strict_relevance:
            topic_drift_rates.append(drift)
        latencies_ms.append(latency_ms)
        scenario = str(case.get("scenario", "unspecified"))
        scenarios.setdefault(scenario, []).append(
            {"hit": hit, "recall": recall, "mrr": mrr, "leakage": leakage}
        )

        details.append({
            "query": query_text,
            "expected_pages": sorted(expected),
            "retrieved": retrieved[:k],
            "hit": bool(hit),
            "first_rank": first_rank,
            "precision_at_k": round(precision, 4),
            "recall_at_k": round(recall, 4),
            "mrr_at_k": round(mrr, 4),
            "ndcg_at_k": round(ndcg, 4),
            "complete_recall": bool(complete_recall),
            "subgoal_coverage": round(subgoal_coverage, 4),
            "complete_subgoal_coverage": bool(complete_subgoal_coverage),
            "topic_drift_rate": round(drift, 4),
            "retrieval_hops": max(
                (int(item.get("retrieval_hop", 1)) for item in results),
                default=1,
            ),
            "forbidden_leaks": sorted(leaked),
            "latency_ms": round(latency_ms, 3),
            "scenario": scenario,
        })

    return {
        "method": "beir_mteb_retrieval",
        "k": k,
        "cases": len(cases),
        "metrics": {
            "hit_rate_at_k": round(mean(hit_rates), 4) if hit_rates else 0.0,
            "precision_at_k": round(mean(precisions), 4) if precisions else 0.0,
            "recall_at_k": round(mean(recalls), 4) if recalls else 0.0,
            "mrr_at_k": round(mean(mrrs), 4) if mrrs else 0.0,
            "ndcg_at_k": round(mean(ndcgs), 4) if ndcgs else 0.0,
            "complete_recall_rate": (
                round(mean(complete_recalls), 4) if complete_recalls else 0.0
            ),
            "subgoal_coverage": (
                round(mean(subgoal_coverages), 4) if subgoal_coverages else 0.0
            ),
            "complete_subgoal_coverage_rate": (
                round(mean(complete_subgoal_coverages), 4)
                if complete_subgoal_coverages
                else 0.0
            ),
            "topic_drift_rate": (
                round(mean(topic_drift_rates), 4) if topic_drift_rates else 0.0
            ),
            "forbidden_leakage_rate": (
                round(mean(leakage_rates), 4) if leakage_rates else 0.0
            ),
            "latency_p50_ms": round(_percentile(latencies_ms, 0.50), 3),
            "latency_p95_ms": round(_percentile(latencies_ms, 0.95), 3),
        },
        "scenario_metrics": {
            name: {
                "cases": len(values),
                "hit_rate": round(mean(v["hit"] for v in values), 4),
                "recall_at_k": round(mean(v["recall"] for v in values), 4),
                "mrr_at_k": round(mean(v["mrr"] for v in values), 4),
                "forbidden_leakage_rate": round(
                    mean(v["leakage"] for v in values), 4
                ),
            }
            for name, values in sorted(scenarios.items())
        },
        "details": details,
    }


def _context_text(results: list[dict]) -> str:
    parts = []
    for result in results:
        page_text = read_page_content(result.get("path", ""))
        text = page_text or result.get("text", "")
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extractive_answer(query_text: str, context: str, reference_answer: str = "") -> str:
    """Create a deterministic local answer for RAGAS-style smoke tests."""
    query_terms = _tokens(query_text) | _tokens(reference_answer)
    sentences = re.split(r"(?<=[。.!?])\s+|\n+", context)
    scored = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 8:
            continue
        overlap = len(_tokens(sentence) & query_terms)
        if overlap:
            scored.append((overlap, sentence))
    scored.sort(key=lambda x: -x[0])
    selected = [s for _, s in scored[:3]]
    return " ".join(selected) if selected else context[:500]


def _coverage_score(text: str, required_terms: list[str]) -> float:
    if not required_terms:
        return 1.0
    text_lower = text.lower()
    hits = sum(1 for term in required_terms if str(term).lower() in text_lower)
    return hits / len(required_terms)


def run_ragas_lite_benchmark(cases: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """Run dependency-free RAGAS-style benchmark."""
    details = []
    context_precisions = []
    context_recalls = []
    answer_relevancies = []
    faithfulnesses = []

    for case in cases:
        query_text = case["query"]
        expected = set(case.get("expected_pages", []))
        reference_answer = case.get("reference_answer", "")
        must_contain = [str(t) for t in case.get("must_contain", [])]

        results = _search_case(case, k)
        retrieved = _retrieved_ids(results)
        contexts = _context_text(results)
        answer = case.get("answer") or _extractive_answer(query_text, contexts, reference_answer)

        relevant_count = sum(1 for rid in retrieved[:k] if _matches_any(rid, expected))
        context_precision = relevant_count / len(retrieved[:k]) if retrieved else 0.0
        context_recall = relevant_count / len(expected) if expected else 0.0

        answer_terms = _tokens(answer)
        query_ref_terms = _tokens(query_text) | _tokens(reference_answer)
        answer_relevancy = (
            len(answer_terms & query_ref_terms) / len(query_ref_terms)
            if query_ref_terms else 0.0
        )

        context_terms = _tokens(contexts)
        answer_content_terms = answer_terms - _tokens(query_text)
        faithfulness = (
            len(answer_content_terms & context_terms) / len(answer_content_terms)
            if answer_content_terms else 1.0
        )
        required_term_coverage = _coverage_score(answer + "\n" + contexts, must_contain)

        context_precisions.append(context_precision)
        context_recalls.append(context_recall)
        answer_relevancies.append(answer_relevancy)
        faithfulnesses.append(faithfulness)

        details.append({
            "query": query_text,
            "expected_pages": sorted(expected),
            "retrieved": retrieved[:k],
            "answer": answer[:1000],
            "context_precision": round(context_precision, 4),
            "context_recall": round(context_recall, 4),
            "answer_relevancy": round(answer_relevancy, 4),
            "faithfulness": round(faithfulness, 4),
            "must_contain_coverage": round(required_term_coverage, 4),
        })

    ragas_score_values = [
        mean(values)
        for values in zip(context_precisions, context_recalls, answer_relevancies, faithfulnesses)
    ]

    return {
        "method": "ragas_lite",
        "k": k,
        "cases": len(cases),
        "metrics": {
            "context_precision": round(mean(context_precisions), 4) if context_precisions else 0.0,
            "context_recall": round(mean(context_recalls), 4) if context_recalls else 0.0,
            "answer_relevancy": round(mean(answer_relevancies), 4) if answer_relevancies else 0.0,
            "faithfulness": round(mean(faithfulnesses), 4) if faithfulnesses else 0.0,
            "ragas_lite_score": round(mean(ragas_score_values), 4) if ragas_score_values else 0.0,
        },
        "details": details,
    }


def run_benchmark(eval_file: Path, method: str, k: int) -> dict[str, Any]:
    cases = _load_cases(eval_file)
    output: dict[str, Any] = {
        "eval_file": str(eval_file),
        "methods": [],
    }
    if method in ("retrieval", "both"):
        output["methods"].append(run_retrieval_benchmark(cases, k=k))
    if method in ("ragas-lite", "both"):
        output["methods"].append(run_ragas_lite_benchmark(cases, k=k))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG/knowledge-base benchmark")
    parser.add_argument("eval_file", help="JSONL eval cases")
    parser.add_argument(
        "--method",
        choices=["retrieval", "ragas-lite", "both"],
        default="both",
        help="Benchmark method",
    )
    parser.add_argument("-k", "--top-k", type=int, default=5, help="Top-k retrieval cutoff")
    parser.add_argument("-o", "--output", help="Write benchmark result JSON")
    args = parser.parse_args()

    result = run_benchmark(Path(args.eval_file), method=args.method, k=args.top_k)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
