#!/usr/bin/env python3
"""Multi-dimensional benchmark report for compiled llm-wiki retrieval.

This script intentionally separates:
- dataset/corpus coverage
- compiled wiki quality
- index health
- retrieval effectiveness
- latency probes
- query robustness probes

It is designed to run against an existing compiled BEIR wiki cache without
calling the LLM compile pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_beir import (  # noqa: E402
    BM25Retriever,
    LLMWikiRetriever,
    _filter_qrels_to_docs,
    _mrr_at_k,
    _ndcg_at_k,
    _recall_at_k,
    evaluate_retrieval,
    load_beir,
)


DEFAULT_RESULT_FILES = {
    "llm_wiki_vector": "evals/beir_results_compiled_cache_scifact_qwen8b_qrels50_vectorstream.json",
    "llm_wiki_bm25": "evals/beir_results_compiled_cache_scifact_qwen8b_qrels50_bm25stream.json",
    "llm_wiki_bm25_vector": "evals/beir_results_compiled_cache_scifact_qwen8b_qrels50.json",
    "original_bm25_subset": "evals/beir_results_scifact_qrels50_bm25_subset.json",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]


def _summarize_latencies(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "count": len(values),
        "mean_sec": round(statistics.mean(values), 4),
        "p50_sec": round(_percentile(values, 0.50), 4),
        "p95_sec": round(_percentile(values, 0.95), 4),
        "max_sec": round(max(values), 4),
    }


def _metric_row(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, list):
        method = result[0]["methods"][0]
        compile_info = result[0].get("llm_wiki_compile", {})
        return {
            "queries": method.get("queries_evaluated"),
            "NDCG@10": method.get("NDCG@10"),
            "Recall@10": method.get("Recall@10"),
            "MRR@10": method.get("MRR@10"),
            "Precision@10": method.get("Precision@10"),
            "eval_time_sec": method.get("eval_time_sec"),
            "mapped_docs": compile_info.get("mapped_beir_docs"),
            "wiki_pages": compile_info.get("wiki_pages"),
            "coverage_mode": method.get("coverage_mode"),
        }
    return {
        "queries": result.get("queries_evaluated"),
        "NDCG@10": result.get("NDCG@10"),
        "Recall@10": result.get("Recall@10"),
        "MRR@10": result.get("MRR@10"),
        "Precision@10": result.get("Precision@10"),
        "eval_time_sec": result.get("eval_time_sec"),
    }


def load_result_summary(result_files: dict[str, str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name, raw_path in result_files.items():
        path = Path(raw_path)
        if path.exists():
            summary[name] = _metric_row(_load_json(path))
        else:
            summary[name] = {"missing": str(path)}
    return summary


def dataset_coverage(
    dataset_key: str,
    wiki_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]], dict[str, str], dict[str, dict[str, int]], set[str]]:
    corpus, queries, qrels = load_beir(dataset_key)
    page_map_path = wiki_root / "page_to_doc_map.json"
    page_to_doc = {str(k): str(v) for k, v in _load_json(page_map_path).items()}
    covered_docs = set(page_to_doc.values())
    covered_qrels = _filter_qrels_to_docs(qrels, covered_docs)
    relevant_docs = {doc_id for rels in qrels.values() for doc_id in rels}
    return (
        {
            "dataset": dataset_key,
            "corpus_docs": len(corpus),
            "queries_total": len(queries),
            "qrels_queries_total": len(qrels),
            "qrels_relevances_total": sum(len(v) for v in qrels.values()),
            "unique_relevant_docs": len(relevant_docs),
            "compiled_mapped_pages": len(page_to_doc),
            "compiled_unique_docs": len(covered_docs),
            "compiled_doc_coverage_pct": round(len(covered_docs) / max(len(corpus), 1) * 100, 2),
            "covered_qrels_queries": len(covered_qrels),
            "covered_qrels_query_pct": round(len(covered_qrels) / max(len(qrels), 1) * 100, 2),
            "covered_relevances": sum(len(v) for v in covered_qrels.values()),
            "covered_relevant_doc_pct": round(
                len(covered_docs.intersection(relevant_docs)) / max(len(relevant_docs), 1) * 100,
                2,
            ),
        },
        corpus,
        queries,
        covered_qrels,
        covered_docs,
    )


def compiled_wiki_quality(wiki_dir: Path, wiki_root: Path) -> dict[str, Any]:
    pages = sorted((wiki_dir / "pages").glob("**/*.md"))
    page_types: Counter[str] = Counter()
    page_dirs: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    pages_with_source = 0
    yaml_failures = 0
    page_lengths: list[int] = []

    for page in pages:
        if page.name == "index.md":
            continue
        page_dirs[page.parent.name] += 1
        text = page.read_text(encoding="utf-8", errors="replace")
        page_lengths.append(len(text))
        fm = re.match(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
        if not fm:
            yaml_failures += 1
            continue
        frontmatter = fm.group(1)
        type_match = re.search(r"^type:\s*(.+)$", frontmatter, flags=re.MULTILINE)
        source_match = re.search(r"^source:\s*(.+)$", frontmatter, flags=re.MULTILINE)
        page_types[(type_match.group(1).strip() if type_match else "unknown")] += 1
        if source_match:
            source = source_match.group(1).strip().strip('"')
            source_counts[source] += 1
            pages_with_source += 1

    audit_path = wiki_dir / "audit.json"
    audit_entries = _load_json(audit_path) if audit_path.exists() else []
    contradiction_entries = [
        entry for entry in audit_entries
        if int(entry.get("contradictions", 0) or 0) > 0
    ]
    contradictions_total = sum(int(entry.get("contradictions", 0) or 0) for entry in audit_entries)

    page_map = _load_json(wiki_root / "page_to_doc_map.json")
    pages_per_doc: dict[str, int] = defaultdict(int)
    for doc_id in page_map.values():
        pages_per_doc[str(doc_id)] += 1
    pages_per_doc_values = list(pages_per_doc.values())

    return {
        "page_files": len(pages),
        "page_types": dict(page_types.most_common()),
        "page_dirs": dict(page_dirs.most_common()),
        "pages_with_source": pages_with_source,
        "pages_with_source_pct": round(pages_with_source / max(len(pages) - 1, 1) * 100, 2),
        "frontmatter_parse_failures": yaml_failures,
        "page_length_chars": {
            "mean": round(statistics.mean(page_lengths), 1) if page_lengths else 0,
            "p50": round(_percentile(page_lengths, 0.50), 1),
            "p95": round(_percentile(page_lengths, 0.95), 1),
        },
        "sources_total": len(source_counts),
        "pages_per_mapped_doc": {
            "mean": round(statistics.mean(pages_per_doc_values), 2) if pages_per_doc_values else 0,
            "p50": round(_percentile(pages_per_doc_values, 0.50), 2),
            "p95": round(_percentile(pages_per_doc_values, 0.95), 2),
            "max": max(pages_per_doc_values) if pages_per_doc_values else 0,
        },
        "audit_entries": len(audit_entries),
        "audit_entries_with_contradictions": len(contradiction_entries),
        "contradictions_total": contradictions_total,
    }


def index_health(wiki_dir: Path) -> dict[str, Any]:
    graph_dir = wiki_dir / "graph"
    page_embeddings_path = graph_dir / "embeddings.json"
    chunk_embeddings_path = graph_dir / "chunk_embeddings.json"
    pages = [p for p in (wiki_dir / "pages").glob("**/*.md") if p.name != "index.md"]

    def embedding_status(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"exists": False, "items": 0}
        data = _load_json(path)
        items = data.get("items", data if isinstance(data, dict) else {})
        meta = data.get("_meta", data.get("meta", {})) if isinstance(data, dict) else {}
        return {
            "exists": True,
            "items": len(items),
            "model": meta.get("model"),
            "dimension": meta.get("dimension"),
            "mode": meta.get("mode"),
        }

    page_status = embedding_status(page_embeddings_path)
    chunk_status = embedding_status(chunk_embeddings_path)
    page_status["coverage_pct"] = round(page_status["items"] / max(len(pages), 1) * 100, 2)

    return {
        "page_files": len(pages),
        "page_embedding": page_status,
        "chunk_embedding": chunk_status,
        "bm25_cache_exists": (graph_dir / ".bm25_index.json").exists(),
        "chunk_bm25_cache_exists": (graph_dir / ".chunk_bm25_index.json").exists(),
        "metadata_cache_exists": (graph_dir / ".metadata_index.json").exists(),
    }


def run_original_bm25_subset(
    corpus: dict[str, dict[str, str]],
    queries: dict[str, str],
    covered_qrels: dict[str, dict[str, int]],
    candidate_doc_ids: set[str],
) -> dict[str, Any]:
    filtered_corpus = {doc_id: doc for doc_id, doc in corpus.items() if doc_id in candidate_doc_ids}
    retriever = BM25Retriever(filtered_corpus)
    t0 = time.time()
    result = evaluate_retrieval(
        retriever,
        queries,
        covered_qrels,
        k_values=[1, 5, 10],
        method_name="bm25-original-docs-covered-relevant-only",
        show_progress=False,
    )
    result["eval_time_sec"] = round(time.time() - t0, 4)
    result["candidate_docs"] = len(filtered_corpus)
    return result


def _query_variants(query: str) -> dict[str, str]:
    stripped = re.sub(r"[^\w\s-]", " ", query, flags=re.UNICODE)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    words = query.split()
    truncated = " ".join(words[: max(4, int(len(words) * 0.65))])
    return {
        "original": query,
        "lowercase": query.lower(),
        "no_punctuation": stripped,
        "truncated_65pct": truncated,
    }


def probe_retriever(
    dataset_key: str,
    corpus: dict[str, dict[str, str]],
    queries: dict[str, str],
    covered_qrels: dict[str, dict[str, int]],
    wiki_dir: Path,
    streams: str,
    embedding_model: str,
    sample: int,
    robustness: bool,
) -> dict[str, Any]:
    retriever = LLMWikiRetriever(
        dataset_key,
        corpus,
        streams=streams,
        embedding_mode="local",
        embedding_model=embedding_model,
        compiled_wiki_dir=wiki_dir,
    )
    retriever.build_vector_indexes(batch_size=16)
    qids = list(covered_qrels)[:sample]
    latencies: list[float] = []
    per_query: list[dict[str, Any]] = []

    for qid in qids:
        query = queries[qid]
        t0 = time.time()
        results = retriever.search(query, limit=10)
        elapsed = time.time() - t0
        latencies.append(elapsed)
        retrieved = [doc_id for doc_id, _ in results]
        per_query.append({
            "qid": qid,
            "latency_sec": round(elapsed, 4),
            "NDCG@10": round(_ndcg_at_k(retrieved, covered_qrels[qid], 10), 4),
            "Recall@10": round(_recall_at_k(retrieved, covered_qrels[qid], 10), 4),
            "MRR@10": round(_mrr_at_k(retrieved, covered_qrels[qid], 10), 4),
            "top_doc": retrieved[0] if retrieved else "",
        })

    output: dict[str, Any] = {
        "streams": streams,
        "sample": len(qids),
        "latency": _summarize_latencies(latencies),
        "effectiveness_sample": {
            "NDCG@10": round(statistics.mean([x["NDCG@10"] for x in per_query]), 4) if per_query else 0,
            "Recall@10": round(statistics.mean([x["Recall@10"] for x in per_query]), 4) if per_query else 0,
            "MRR@10": round(statistics.mean([x["MRR@10"] for x in per_query]), 4) if per_query else 0,
        },
        "details": per_query,
    }

    if robustness:
        variants: dict[str, list[float]] = defaultdict(list)
        variant_mrr: dict[str, list[float]] = defaultdict(list)
        top_doc_stability: dict[str, list[float]] = defaultdict(list)
        for qid in qids:
            original_query = queries[qid]
            original_results = retriever.search(original_query, limit=10)
            original_top = original_results[0][0] if original_results else ""
            for variant_name, variant_query in _query_variants(original_query).items():
                results = retriever.search(variant_query, limit=10)
                retrieved = [doc_id for doc_id, _ in results]
                variants[variant_name].append(_recall_at_k(retrieved, covered_qrels[qid], 10))
                variant_mrr[variant_name].append(_mrr_at_k(retrieved, covered_qrels[qid], 10))
                top_doc_stability[variant_name].append(1.0 if retrieved and retrieved[0] == original_top else 0.0)

        output["robustness"] = {
            name: {
                "Recall@10": round(statistics.mean(vals), 4) if vals else 0,
                "MRR@10": round(statistics.mean(variant_mrr[name]), 4) if variant_mrr[name] else 0,
                "top1_stability": round(statistics.mean(top_doc_stability[name]), 4) if top_doc_stability[name] else 0,
            }
            for name, vals in variants.items()
        }

    return output


def generate_markdown(report: dict[str, Any]) -> str:
    retrieval = report.get("retrieval_effectiveness", {})
    lines = [
        "# Multi-Dimensional Retrieval Evaluation",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Verdict",
        "",
        report.get("verdict", ""),
        "",
        "## Retrieval",
        "",
        "| Method | Queries | NDCG@10 | Recall@10 | MRR@10 | Eval time |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in retrieval.items():
        if "missing" in row:
            continue
        lines.append(
            f"| {name} | {row.get('queries', '')} | {row.get('NDCG@10', 0):.4f} | "
            f"{row.get('Recall@10', 0):.4f} | {row.get('MRR@10', 0):.4f} | "
            f"{row.get('eval_time_sec', '')} |"
        )

    coverage = report["coverage"]
    lines.extend([
        "",
        "## Coverage",
        "",
        f"- Corpus docs: {coverage['corpus_docs']}",
        f"- Compiled mapped docs: {coverage['compiled_unique_docs']} ({coverage['compiled_doc_coverage_pct']}%)",
        f"- Covered qrels queries: {coverage['covered_qrels_queries']}/{coverage['qrels_queries_total']} "
        f"({coverage['covered_qrels_query_pct']}%)",
        f"- Covered relevance labels: {coverage['covered_relevances']}/{coverage['qrels_relevances_total']}",
        "",
        "## Index Health",
        "",
        f"- Page embeddings: {report['index_health']['page_embedding']['items']} items, "
        f"{report['index_health']['page_embedding']['coverage_pct']}% coverage",
        f"- Embedding model: {report['index_health']['page_embedding'].get('model')}",
        f"- Chunk embeddings: {report['index_health']['chunk_embedding']['items']} items",
        "",
        "## Compile Quality",
        "",
        f"- Page files: {report['compiled_wiki_quality']['page_files']}",
        f"- Frontmatter parse failures: {report['compiled_wiki_quality']['frontmatter_parse_failures']}",
        f"- Audit contradictions: {report['compiled_wiki_quality']['contradictions_total']}",
        f"- Pages per mapped doc mean/p95: "
        f"{report['compiled_wiki_quality']['pages_per_mapped_doc']['mean']} / "
        f"{report['compiled_wiki_quality']['pages_per_mapped_doc']['p95']}",
    ])

    if report.get("probes"):
        lines.extend(["", "## Probes", ""])
        for name, probe in report["probes"].items():
            latency = probe.get("latency", {})
            sample_metrics = probe.get("effectiveness_sample", {})
            lines.append(
                f"- {name}: sample={probe.get('sample')}, "
                f"NDCG@10={sample_metrics.get('NDCG@10')}, "
                f"Recall@10={sample_metrics.get('Recall@10')}, "
                f"p50={latency.get('p50_sec')}s, p95={latency.get('p95_sec')}s"
            )
            robustness = probe.get("robustness", {})
            for variant, metrics in robustness.items():
                lines.append(
                    f"  - {variant}: Recall@10={metrics.get('Recall@10')}, "
                    f"MRR@10={metrics.get('MRR@10')}, top1_stability={metrics.get('top1_stability')}"
                )

    lines.extend([
        "",
        "## Limits",
        "",
        "- This is still a compiled subset evaluation, not a full SciFact/BEIR leaderboard run.",
        "- Vector latency reflects local Qwen/Qwen3-Embedding-8B on the current CPU environment.",
        "- Chunk-vector evaluation is reported as index health unless chunk embeddings are explicitly generated.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or assemble a multi-dimensional retrieval benchmark")
    parser.add_argument("--dataset", default="scifact")
    parser.add_argument("--compiled-wiki-dir", type=Path, default=Path("evals/beir_wiki/scifact/.wiki"))
    parser.add_argument("--embedding-model", default="Qwen/Qwen3-Embedding-8B")
    parser.add_argument("--latency-sample", type=int, default=0)
    parser.add_argument("--robustness-sample", type=int, default=0)
    parser.add_argument("--probe-streams", default="vector,bm25")
    parser.add_argument("--output", type=Path, default=Path("evals/beir_multidim_report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("evals/BEIR_MULTIDIM_REPORT.md"))
    args = parser.parse_args()

    wiki_dir = args.compiled_wiki_dir
    wiki_root = wiki_dir.parent
    os.environ["LLM_WIKI_DIR"] = str(wiki_dir)
    os.environ["EMBEDDING_MODE"] = "local"
    os.environ["EMBEDDING_MODEL"] = args.embedding_model
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    coverage, corpus, queries, covered_qrels, covered_doc_ids = dataset_coverage(args.dataset, wiki_root)
    retrieval = load_result_summary(DEFAULT_RESULT_FILES)
    retrieval["original_bm25_compiled_subset_recomputed"] = _metric_row(
        run_original_bm25_subset(corpus, queries, covered_qrels, covered_doc_ids)
    )

    probes: dict[str, Any] = {}
    probe_sample = max(args.latency_sample, args.robustness_sample)
    if probe_sample > 0:
        for stream in [s.strip() for s in args.probe_streams.split(",") if s.strip()]:
            probes[stream] = probe_retriever(
                args.dataset,
                corpus,
                queries,
                covered_qrels,
                wiki_dir,
                stream,
                args.embedding_model,
                sample=probe_sample,
                robustness=args.robustness_sample > 0,
            )

    vector = retrieval.get("llm_wiki_vector", {})
    bm25_vector = retrieval.get("llm_wiki_bm25_vector", {})
    verdict = (
        "Qwen 8B page-vector retrieval is currently the strongest tested path. "
        "Hybrid bm25,vector underperforms pure vector on the compiled subset, "
        "so fusion weighting should be treated as an optimization target. "
        "Coverage is materially better than the earlier 4-query run but remains a subset evaluation."
    )
    if vector.get("NDCG@10", 0) < bm25_vector.get("NDCG@10", 0):
        verdict = (
            "Hybrid retrieval is currently strongest on the available subset. "
            "Coverage remains partial, so full BEIR comparison is not yet justified."
        )

    report = {
        "verdict": verdict,
        "coverage": coverage,
        "compiled_wiki_quality": compiled_wiki_quality(wiki_dir, wiki_root),
        "index_health": index_health(wiki_dir),
        "retrieval_effectiveness": retrieval,
        "probes": probes,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(generate_markdown(report), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "markdown": str(args.markdown),
        "coverage_queries": coverage["covered_qrels_queries"],
        "best_known": "llm_wiki_vector",
        "best_known_ndcg10": retrieval.get("llm_wiki_vector", {}).get("NDCG@10"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
