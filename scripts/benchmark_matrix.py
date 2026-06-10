#!/usr/bin/env python3
"""Benchmark coverage matrix for public and private knowledge-base evals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_beir import BEIR_DATASETS, BEIR_WIKI_CACHE_DIR, load_beir  # noqa: E402


PRIVATE_SCENARIOS = {
    "long_document": "Long document retrieval and section-local recall",
    "table": "Structured table/ledger retrieval",
    "chinese": "Chinese tokenization and semantic retrieval",
    "permission_filter": "Access-control filtered retrieval",
    "temporal": "Time-sensitive knowledge and stale claim handling",
    "qa_citation": "Answer citation accuracy and faithfulness",
}


def beir_dataset_status(dataset_key: str) -> dict[str, Any]:
    corpus, queries, qrels = load_beir(dataset_key)
    root = BEIR_WIKI_CACHE_DIR / dataset_key
    wiki_dir = root / ".wiki"
    page_map_path = root / "page_to_doc_map.json"
    manifest_path = root / "manifest.json"
    page_map = {}
    if page_map_path.exists():
        page_map = json.loads(page_map_path.read_text(encoding="utf-8"))
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    covered_docs = set(str(v) for v in page_map.values())
    covered_qrels = {
        qid: {doc_id: score for doc_id, score in rels.items() if doc_id in covered_docs}
        for qid, rels in qrels.items()
    }
    covered_qrels = {qid: rels for qid, rels in covered_qrels.items() if rels}
    return {
        "dataset": dataset_key,
        "name": BEIR_DATASETS[dataset_key]["name"],
        "corpus_docs": len(corpus),
        "queries": len(queries),
        "qrels_queries": len(qrels),
        "qrels_relevances": sum(len(v) for v in qrels.values()),
        "cached": bool(corpus and queries and qrels),
        "compiled_wiki_exists": wiki_dir.exists(),
        "compiled_manifest": manifest,
        "mapped_pages": len(page_map),
        "mapped_docs": len(covered_docs),
        "covered_qrels_queries": len(covered_qrels),
        "covered_qrels_query_pct": round(len(covered_qrels) / max(len(qrels), 1) * 100, 2),
        "fair_metric_ready": bool(qrels and page_map and covered_qrels),
    }


def beir_subset_status(dataset_key: str) -> list[dict[str, Any]]:
    """Return prepared qrels-centered subset caches for a BEIR dataset."""
    _, _, qrels = load_beir(dataset_key)
    rows: list[dict[str, Any]] = []
    for root in sorted(BEIR_WIKI_CACHE_DIR.glob(f"{dataset_key}_*")):
        wiki_dir = root / ".wiki"
        page_map_path = root / "page_to_doc_map.json"
        if not wiki_dir.exists() or not page_map_path.exists():
            continue
        try:
            page_map = json.loads(page_map_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        manifest_path = root / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest = {}
        covered_docs = set(str(v) for v in page_map.values())
        covered_qrels = {
            qid: {doc_id: score for doc_id, score in rels.items() if doc_id in covered_docs}
            for qid, rels in qrels.items()
        }
        covered_qrels = {qid: rels for qid, rels in covered_qrels.items() if rels}
        rows.append({
            "dataset": dataset_key,
            "subset": root.name,
            "format": manifest.get("format", ""),
            "mapped_pages": len(page_map),
            "mapped_docs": len(covered_docs),
            "covered_qrels_queries": len(covered_qrels),
            "qrels_queries_total": len(qrels),
            "covered_qrels_query_pct": round(len(covered_qrels) / max(len(qrels), 1) * 100, 2),
            "ready": bool(covered_qrels),
            "path": str(wiki_dir),
        })
    return rows


def private_scenario_status(root: Path) -> dict[str, Any]:
    evals_dir = root / "evals"
    private_benchmark_path = evals_dir / "private_kb_benchmark.json"
    private_benchmark: dict[str, Any] = {}
    if private_benchmark_path.exists():
        try:
            private_benchmark = json.loads(private_benchmark_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            private_benchmark = {}
    benchmark_scenarios = private_benchmark.get("by_scenario", {})
    scenario_files = {
        "long_document": list(evals_dir.glob("*long*")),
        "table": list(evals_dir.glob("*table*")) + list(evals_dir.glob("*ledger*")),
        "chinese": list(evals_dir.glob("*chinese*")) + list(evals_dir.glob("*zh*")),
        "permission_filter": list(evals_dir.glob("*permission*")) + list(evals_dir.glob("*acl*")),
        "temporal": list(evals_dir.glob("*temporal*")) + list(evals_dir.glob("*time*")),
        "qa_citation": list(evals_dir.glob("*citation*")) + list(evals_dir.glob("*qa_citation*")),
    }
    return {
        key: {
            "description": PRIVATE_SCENARIOS[key],
            "files": [str(p) for p in files]
            + ([str(private_benchmark_path)] if key in benchmark_scenarios else []),
            "metrics": benchmark_scenarios.get(key, {}),
            "ready": key in benchmark_scenarios or bool(files),
        }
        for key, files in scenario_files.items()
    }


def generate_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Benchmark Coverage Matrix",
        "",
        "## BEIR",
        "",
        "| Dataset | Corpus | Qrels queries | Compiled docs | Covered qrels | Ready |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["beir"].values():
        lines.append(
            f"| {row['name']} | {row['corpus_docs']} | {row['qrels_queries']} | "
            f"{row['mapped_docs']} | {row['covered_qrels_queries']} "
            f"({row['covered_qrels_query_pct']}%) | {row['fair_metric_ready']} |"
        )
    subset_rows = [
        row
        for rows in report.get("beir_subsets", {}).values()
        for row in rows
    ]
    if subset_rows:
        lines.extend([
            "",
            "## BEIR Qrels-Centered Subset Caches",
            "",
            "| Dataset | Subset | Format | Compiled docs | Covered qrels | Ready | Path |",
            "|---|---|---|---:|---:|---|---|",
        ])
        for row in subset_rows:
            lines.append(
                f"| {row['dataset']} | {row['subset']} | {row['format']} | "
                f"{row['mapped_docs']} | {row['covered_qrels_queries']}/{row['qrels_queries_total']} "
                f"({row['covered_qrels_query_pct']}%) | {row['ready']} | {row['path']} |"
            )
    lines.extend([
        "",
        "## Private Knowledge-Base Scenarios",
        "",
        "| Scenario | Ready | Hit@K | MRR@K | Permission leak | Forbidden hit | Files |",
        "|---|---|---:|---:|---:|---:|---|",
    ])
    for key, row in report["private_scenarios"].items():
        files = "<br>".join(row["files"]) if row["files"] else ""
        metrics = row.get("metrics", {})
        hit = metrics.get("hit_at_k", "")
        mrr = metrics.get("mrr_at_k", "")
        leak = metrics.get("permission_leak_rate", "")
        forbidden = metrics.get("forbidden_hit_rate", "")
        lines.append(f"| {key} | {row['ready']} | {hit} | {mrr} | {leak} | {forbidden} | {files} |")
    lines.extend([
        "",
        "## Required Next Work",
        "",
        "- Promote NFCorpus and FiQA from qrels-centered direct-wiki subsets to product-grade compiled caches.",
        "- Run `python scripts/benchmark_private_kb.py --rebuild` after retrieval changes to refresh private scenario metrics.",
        "- Add LLM compile fidelity evals: source claim preservation, entity split quality, relation graph correctness, contradiction handling.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark coverage matrix")
    parser.add_argument("--output", type=Path, default=Path("evals/benchmark_matrix.json"))
    parser.add_argument("--markdown", type=Path, default=Path("evals/BENCHMARK_MATRIX.md"))
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    report = {
        "beir": {key: beir_dataset_status(key) for key in BEIR_DATASETS},
        "beir_subsets": {key: beir_subset_status(key) for key in BEIR_DATASETS},
        "private_scenarios": private_scenario_status(root),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(generate_markdown(report), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "markdown": str(args.markdown),
        "beir_ready": [k for k, v in report["beir"].items() if v["fair_metric_ready"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
