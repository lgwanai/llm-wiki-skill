#!/usr/bin/env python3
"""Private knowledge-base retrieval benchmark.

This benchmark builds a deterministic local `.wiki` fixture and evaluates the
real search pipeline against product-style scenarios that BEIR does not cover:
long documents, tables, Chinese content, permission filtering, temporal facts,
and citation-bearing QA.

It does not call compile_v2 or an LLM. The goal is retrieval-only regression
coverage over already materialized wiki pages.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


PRIVATE_CASES: list[dict[str, Any]] = [
    {
        "id": "long-document-section",
        "scenario": "long_document",
        "query": "Which recovery marker controls retry backoff in the Q4 incident runbook?",
        "expected_pages": ["q4-incident-runbook"],
        "must_contain": ["outbox_retry_watermark"],
    },
    {
        "id": "table-plan-retention",
        "scenario": "table",
        "query": "APAC enterprise plan audit log retention days",
        "expected_pages": ["enterprise-pricing-2026"],
        "must_contain": ["730 days"],
    },
    {
        "id": "chinese-release-owner",
        "scenario": "chinese",
        "query": "中文灰度发布谁负责回滚审批",
        "expected_pages": ["zh-release-policy"],
        "must_contain": ["值班发布经理"],
    },
    {
        "id": "permission-public-user",
        "scenario": "permission_filter",
        "query": "Mercury launch budget approval",
        "expected_pages": ["mercury-public-status"],
        "forbidden_pages": ["mercury-confidential-budget"],
        "allowed_scopes": ["public"],
        "must_contain": ["public launch status"],
    },
    {
        "id": "temporal-current-limit",
        "scenario": "temporal",
        "query": "current API rate limit as of 2026 for partner ingestion",
        "expected_pages": ["partner-api-rate-limit-2026"],
        "forbidden_pages": ["partner-api-rate-limit-2024"],
        "exclude_statuses": ["superseded"],
        "must_contain": ["1200 requests per minute"],
    },
    {
        "id": "qa-citation-source",
        "scenario": "qa_citation",
        "query": "What citation supports the SOC2 evidence retention rule?",
        "expected_pages": ["soc2-evidence-retention"],
        "must_contain": ["policy-handbook.md#S3"],
    },
]


def _yaml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _page(
    page_id: str,
    name: str,
    body: str,
    *,
    page_type: str = "concept",
    scope: str = "public",
    status: str = "current",
    keywords: list[str] | None = None,
    questions: list[str] | None = None,
) -> str:
    keywords = keywords or []
    questions = questions or []
    return "\n".join([
        "---",
        f"id: {_yaml_string(page_id)}",
        f"type: {_yaml_string(page_type)}",
        f"name: {_yaml_string(name)}",
        f"scope: {_yaml_string(scope)}",
        f"status: {_yaml_string(status)}",
        f"keywords: {json.dumps(keywords, ensure_ascii=False)}",
        f"questions: {json.dumps(questions, ensure_ascii=False)}",
        "---",
        "",
        f"# {name}",
        "",
        body.strip(),
        "",
    ])


def build_private_wiki(wiki_dir: Path, force: bool = False) -> dict[str, Any]:
    """Build a deterministic wiki fixture used by the private KB benchmark."""
    if force and wiki_dir.exists():
        shutil.rmtree(wiki_dir)
    pages_dir = wiki_dir / "pages"
    concepts = pages_dir / "concepts"
    graph = wiki_dir / "graph"
    concepts.mkdir(parents=True, exist_ok=True)
    graph.mkdir(parents=True, exist_ok=True)
    for subdir in (
        "entities",
        "models",
        "techniques",
        "frameworks",
        "benchmarks",
        "papers",
        "decisions",
        "sessions",
        "patterns",
    ):
        (pages_dir / subdir).mkdir(parents=True, exist_ok=True)

    filler = "\n".join(
        f"- Routine incident note {i}: queue depth, replay window, and customer notice were checked."
        for i in range(1, 80)
    )
    pages = {
        "q4-incident-runbook": _page(
            "q4-incident-runbook",
            "Q4 Incident Runbook",
            f"""
## Overview
This runbook is intentionally long so retrieval must land on the right section.

{filler}

## Recovery Markers
The retry backoff controller is `outbox_retry_watermark`.
Operators must advance `outbox_retry_watermark` only after replay lag is below five minutes.
""",
            keywords=["incident", "runbook", "outbox_retry_watermark", "retry backoff"],
            questions=["Which recovery marker controls retry backoff?"],
        ),
        "enterprise-pricing-2026": _page(
            "enterprise-pricing-2026",
            "Enterprise Pricing 2026",
            """
| Region | Plan | Audit log retention | Monthly commit |
|---|---|---:|---:|
| APAC | Enterprise | 730 days | 42000 USD |
| EMEA | Enterprise | 365 days | 39000 USD |
| US | Growth | 180 days | 12000 USD |
""",
            page_type="decision",
            keywords=["APAC", "enterprise", "audit log retention", "730 days"],
            questions=["How many days are APAC Enterprise audit logs retained?"],
        ),
        "zh-release-policy": _page(
            "zh-release-policy",
            "中文灰度发布策略",
            """
## 回滚审批
中文业务线灰度发布由值班发布经理负责回滚审批。
当错误率超过 1.5% 时，发布经理必须在 10 分钟内冻结流量。
""",
            keywords=["中文", "灰度发布", "回滚审批", "值班发布经理"],
            questions=["中文灰度发布谁负责回滚审批？"],
        ),
        "mercury-public-status": _page(
            "mercury-public-status",
            "Mercury Public Launch Status",
            """
The public launch status for Mercury is green.
Budget approval exists, but the public page intentionally redacts the confidential amount.
""",
            keywords=["Mercury", "launch", "budget approval", "public launch status"],
            questions=["What is the public Mercury launch budget approval status?"],
        ),
        "mercury-confidential-budget": _page(
            "mercury-confidential-budget",
            "Mercury Confidential Budget",
            """
Mercury launch budget approval is restricted to finance leadership.
The confidential approved amount is 900000 USD and must not be exposed to public users.
""",
            scope="confidential",
            keywords=["Mercury", "launch", "budget approval", "900000 USD"],
            questions=["What is the Mercury launch budget approval amount?"],
        ),
        "partner-api-rate-limit-2024": _page(
            "partner-api-rate-limit-2024",
            "Partner API Rate Limit 2024",
            """
Status: superseded.
Effective date: 2024-01-01.
The old partner ingestion API limit was 600 requests per minute.
""",
            status="superseded",
            keywords=["partner ingestion", "API rate limit", "2024", "superseded"],
        ),
        "partner-api-rate-limit-2026": _page(
            "partner-api-rate-limit-2026",
            "Partner API Rate Limit 2026",
            """
Status: current.
Effective date: 2026-01-01.
The current partner ingestion API limit is 1200 requests per minute.
This page supersedes [[partner-api-rate-limit-2024]].
""",
            status="current",
            keywords=["partner ingestion", "API rate limit", "2026", "current"],
            questions=["What is the current API rate limit as of 2026?"],
        ),
        "soc2-evidence-retention": _page(
            "soc2-evidence-retention",
            "SOC2 Evidence Retention",
            """
SOC2 evidence retention is 400 days.
Citation: policy-handbook.md#S3.
Answers about this rule must include the citation reference.
""",
            keywords=["SOC2", "evidence retention", "policy-handbook.md#S3"],
            questions=["What citation supports the SOC2 evidence retention rule?"],
        ),
    }

    for page_id, content in pages.items():
        (concepts / f"{page_id}.md").write_text(content, encoding="utf-8")

    entities = {
        page_id: {
            "id": page_id,
            "type": "concept",
            "name": page_id.replace("-", " ").title(),
            "confidence": 1.0,
            "page": f"pages/concepts/{page_id}.md",
            "sources": [f"{page_id}.md"],
        }
        for page_id in pages
    }
    (graph / "entities.json").write_text(json.dumps(entities, ensure_ascii=False), encoding="utf-8")
    (graph / "edges.json").write_text('{"edges": []}', encoding="utf-8")
    cases_path = wiki_dir.parent / "private_kb_eval_cases.jsonl"
    cases_path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in PRIVATE_CASES) + "\n",
        encoding="utf-8",
    )
    return {
        "wiki_dir": str(wiki_dir),
        "pages": len(pages),
        "cases": len(PRIVATE_CASES),
        "cases_file": str(cases_path),
    }


def _load_search(wiki_dir: Path, streams: str):
    os.environ["LLM_WIKI_DIR"] = str(wiki_dir)
    os.environ["LLM_WIKI_SEARCH_STREAMS"] = streams
    import config

    config.reset_config()
    for module_name in ("search", "query"):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)
    query_module = sys.modules["query"]
    return query_module.search_wiki, query_module.read_page_content


def _retrieved_ids(results: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id") or item.get("file") or Path(item.get("path", "")).stem) for item in results]


def _scope_for_result(result: dict[str, Any]) -> str:
    try:
        text = Path(result.get("path", "")).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "public"
    for line in text.splitlines()[:20]:
        if line.startswith("scope:"):
            return line.split(":", 1)[1].strip().strip('"')
    return "public"


def _term_coverage(context: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lowered = context.lower()
    return sum(1 for term in terms if str(term).lower() in lowered) / len(terms)


def evaluate_private_kb(wiki_dir: Path, *, streams: str = "metadata,chunk,bm25", k: int = 5) -> dict[str, Any]:
    """Evaluate the fixture through the real search pipeline."""
    search_wiki, read_page_content = _load_search(wiki_dir, streams)
    details: list[dict[str, Any]] = []
    scenario_scores: dict[str, list[dict[str, float]]] = {}

    for case in PRIVATE_CASES:
        t0 = time.time()
        allowed_scopes = set(case.get("allowed_scopes", []))
        results = search_wiki(
            case["query"],
            limit=k,
            allowed_scopes=allowed_scopes or None,
            exclude_statuses=case.get("exclude_statuses"),
        )
        latency = time.time() - t0
        retrieved = _retrieved_ids(results)
        expected = set(case.get("expected_pages", []))
        forbidden = set(case.get("forbidden_pages", []))
        relevant = [1 if rid in expected else 0 for rid in retrieved[:k]]
        hit = 1.0 if any(relevant) else 0.0
        first_rank = next((idx + 1 for idx, rel in enumerate(relevant) if rel), None)
        mrr = 1.0 / first_rank if first_rank else 0.0
        recall = sum(relevant) / len(expected) if expected else 0.0
        contexts = "\n\n".join(read_page_content(r.get("path", "")) or r.get("text", "") for r in results)
        coverage = _term_coverage(contexts, [str(t) for t in case.get("must_contain", [])])

        forbidden_hits = [rid for rid in retrieved[:k] if rid in forbidden]
        unauthorized_hits: list[str] = []
        if allowed_scopes:
            for result in results[:k]:
                rid = str(result.get("id") or Path(result.get("path", "")).stem)
                if _scope_for_result(result) not in allowed_scopes:
                    unauthorized_hits.append(rid)

        row = {
            "case_id": case["id"],
            "scenario": case["scenario"],
            "query": case["query"],
            "expected_pages": sorted(expected),
            "forbidden_pages": sorted(forbidden),
            "retrieved": retrieved[:k],
            "hit_at_k": round(hit, 4),
            "recall_at_k": round(recall, 4),
            "mrr_at_k": round(mrr, 4),
            "must_contain_coverage": round(coverage, 4),
            "forbidden_hits": forbidden_hits,
            "unauthorized_hits": unauthorized_hits,
            "latency_sec": round(latency, 4),
        }
        details.append(row)
        scenario_scores.setdefault(case["scenario"], []).append({
            "hit_at_k": hit,
            "recall_at_k": recall,
            "mrr_at_k": mrr,
            "must_contain_coverage": coverage,
            "permission_leak": 1.0 if unauthorized_hits else 0.0,
            "forbidden_hit": 1.0 if forbidden_hits else 0.0,
        })

    by_scenario: dict[str, Any] = {}
    for scenario, rows in scenario_scores.items():
        by_scenario[scenario] = {
            "cases": len(rows),
            "hit_at_k": round(statistics.mean(r["hit_at_k"] for r in rows), 4),
            "recall_at_k": round(statistics.mean(r["recall_at_k"] for r in rows), 4),
            "mrr_at_k": round(statistics.mean(r["mrr_at_k"] for r in rows), 4),
            "must_contain_coverage": round(statistics.mean(r["must_contain_coverage"] for r in rows), 4),
            "permission_leak_rate": round(statistics.mean(r["permission_leak"] for r in rows), 4),
            "forbidden_hit_rate": round(statistics.mean(r["forbidden_hit"] for r in rows), 4),
        }

    return {
        "benchmark": "private_kb_retrieval",
        "pipeline_mode": "materialized-wiki -> search",
        "wiki_dir": str(wiki_dir),
        "streams": streams,
        "k": k,
        "cases": len(PRIVATE_CASES),
        "summary": {
            "hit_at_k": round(statistics.mean(d["hit_at_k"] for d in details), 4),
            "recall_at_k": round(statistics.mean(d["recall_at_k"] for d in details), 4),
            "mrr_at_k": round(statistics.mean(d["mrr_at_k"] for d in details), 4),
            "must_contain_coverage": round(statistics.mean(d["must_contain_coverage"] for d in details), 4),
            "permission_leak_rate": round(
                statistics.mean(1.0 if d["unauthorized_hits"] else 0.0 for d in details),
                4,
            ),
            "forbidden_hit_rate": round(
                statistics.mean(1.0 if d["forbidden_hits"] else 0.0 for d in details),
                4,
            ),
        },
        "by_scenario": by_scenario,
        "details": details,
    }


def generate_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Private Knowledge-Base Benchmark",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "Scope: retrieval-only benchmark over deterministic materialized wiki pages. Compile and LLM answer synthesis are skipped.",
        "",
        "## Summary",
        "",
        "| Cases | Streams | Hit@K | Recall@K | MRR@K | Required term coverage | Permission leak rate | Forbidden hit rate |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    summary = report["summary"]
    lines.append(
        f"| {report['cases']} | {report['streams']} | {summary['hit_at_k']:.4f} | "
        f"{summary['recall_at_k']:.4f} | {summary['mrr_at_k']:.4f} | "
        f"{summary['must_contain_coverage']:.4f} | {summary['permission_leak_rate']:.4f} | "
        f"{summary['forbidden_hit_rate']:.4f} |"
    )
    lines.extend([
        "",
        "## Scenario Breakdown",
        "",
        "| Scenario | Cases | Hit@K | Recall@K | MRR@K | Required term coverage | Permission leak rate | Forbidden hit rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for scenario, row in report["by_scenario"].items():
        lines.append(
            f"| {scenario} | {row['cases']} | {row['hit_at_k']:.4f} | {row['recall_at_k']:.4f} | "
            f"{row['mrr_at_k']:.4f} | {row['must_contain_coverage']:.4f} | "
            f"{row['permission_leak_rate']:.4f} | {row['forbidden_hit_rate']:.4f} |"
        )
    lines.extend([
        "",
        "## Findings",
        "",
    ])
    leak = report["by_scenario"].get("permission_filter", {}).get("permission_leak_rate", 0.0)
    if leak:
        lines.append("- Permission filtering is not product-grade: unauthorized or forbidden pages can still appear in raw retrieval results.")
    else:
        lines.append("- Permission filtering did not leak in this fixture, but the search API still lacks an explicit user/ACL parameter.")
    if report["by_scenario"].get("temporal", {}).get("forbidden_hit_rate", 0.0) > 0:
        lines.append("- Temporal retrieval ranks the current page first, but still returns superseded pages in the candidate set.")
    else:
        lines.append("- Temporal filtering excludes superseded pages in this fixture when `exclude_statuses` is supplied.")
    if report["by_scenario"].get("table", {}).get("hit_at_k", 0.0) < 1.0:
        lines.append("- Table retrieval needs structured table indexing or ledger integration.")
    lines.extend([
        "",
        "## Details",
        "",
        "| Case | Scenario | Retrieved | Forbidden hits | Unauthorized hits | MRR@K | Required terms | Latency |",
        "|---|---|---|---|---|---:|---:|---:|",
    ])
    for row in report["details"]:
        lines.append(
            f"| {row['case_id']} | {row['scenario']} | {', '.join(row['retrieved'])} | "
            f"{', '.join(row['forbidden_hits'])} | {', '.join(row['unauthorized_hits'])} | "
            f"{row['mrr_at_k']:.4f} | {row['must_contain_coverage']:.4f} | {row['latency_sec']:.4f}s |"
        )
    lines.extend([
        "",
        "## Limits",
        "",
        "- This fixture is synthetic and intentionally small; it is for regression and product-gap detection, not public leaderboard comparison.",
        "- The permission scenario verifies scope filtering through the `allowed_scopes` search parameter, not a full user/role policy engine.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run private KB retrieval benchmark")
    parser.add_argument("--wiki-dir", type=Path, default=Path("evals/private_kb/.wiki"))
    parser.add_argument("--streams", default="metadata,chunk,bm25")
    parser.add_argument("-k", "--top-k", type=int, default=5)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("evals/private_kb_benchmark.json"))
    parser.add_argument("--markdown", type=Path, default=Path("evals/PRIVATE_KB_BENCHMARK.md"))
    args = parser.parse_args()

    build_info = build_private_wiki(args.wiki_dir, force=args.rebuild)
    report = evaluate_private_kb(args.wiki_dir, streams=args.streams, k=args.top_k)
    report["build"] = build_info
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(generate_markdown(report), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "markdown": str(args.markdown),
        "cases": report["cases"],
        "hit_at_k": report["summary"]["hit_at_k"],
        "permission_leak_rate": report["summary"]["permission_leak_rate"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
