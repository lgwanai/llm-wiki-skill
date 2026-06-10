#!/usr/bin/env python3
"""Prepare qrels-centered BEIR wiki subsets for retrieval benchmarking.

The generated wiki is deterministic: each selected BEIR document becomes one
wiki page. This is intentionally not an LLM semantic compile; it preserves the
original document text so qrels remain comparable across datasets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_beir import BEIR_WIKI_CACHE_DIR, _yaml_string, load_beir  # noqa: E402


def _doc_slug(doc_id: str) -> str:
    digest = hashlib.sha1(doc_id.encode("utf-8")).hexdigest()[:16]
    return f"beir-{digest}"


def _read_test_qrels(dataset_key: str) -> dict[str, dict[str, int]]:
    _, _, qrels = load_beir(dataset_key)
    return qrels


def prepare_subset(
    dataset_key: str,
    query_count: int,
    output_name: str | None = None,
) -> dict[str, Any]:
    corpus, queries, qrels = load_beir(dataset_key)
    selected_qids = list(qrels)[:query_count]
    selected_doc_ids: list[str] = []
    for qid in selected_qids:
        for doc_id in qrels[qid]:
            if doc_id in corpus and doc_id not in selected_doc_ids:
                selected_doc_ids.append(doc_id)

    name = output_name or f"{dataset_key}_qrels{query_count}"
    root = BEIR_WIKI_CACHE_DIR / name
    wiki_dir = root / ".wiki"
    pages_dir = wiki_dir / "pages" / "papers"
    graph_dir = wiki_dir / "graph"
    pages_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)

    for subdir in (
        "concepts",
        "entities",
        "models",
        "techniques",
        "frameworks",
        "benchmarks",
        "decisions",
        "sessions",
        "patterns",
    ):
        (wiki_dir / "pages" / subdir).mkdir(parents=True, exist_ok=True)

    page_to_doc: dict[str, str] = {}
    entities: dict[str, dict[str, Any]] = {}
    for doc_id in selected_doc_ids:
        doc = corpus[doc_id]
        slug = _doc_slug(doc_id)
        title = doc.get("title") or doc_id
        text = doc.get("text") or ""
        content = "\n".join([
            "---",
            f"id: {_yaml_string(slug)}",
            "type: paper",
            f"name: {_yaml_string(title)}",
            f"source_id: {_yaml_string(doc_id)}",
            f"source: {_yaml_string(f'{dataset_key}:{doc_id}')}",
            "---",
            "",
            f"# {title}",
            "",
            text,
            "",
        ])
        page_path = pages_dir / f"{slug}.md"
        page_path.write_text(content, encoding="utf-8")
        page_to_doc[slug] = doc_id
        entities[slug] = {
            "id": slug,
            "type": "paper",
            "name": title,
            "source_id": doc_id,
            "confidence": 1.0,
            "page": f"pages/papers/{slug}.md",
            "sources": [f"{slug}.md"],
        }

    (graph_dir / "entities.json").write_text(json.dumps(entities, ensure_ascii=False), encoding="utf-8")
    (graph_dir / "edges.json").write_text('{"edges": []}', encoding="utf-8")
    (root / "page_to_doc_map.json").write_text(json.dumps(page_to_doc, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "dataset_key": dataset_key,
        "subset": name,
        "format": "beir-qrels-centered-direct-wiki",
        "query_count": len(selected_qids),
        "doc_count": len(selected_doc_ids),
        "qrels_relevances": sum(len(qrels[qid]) for qid in selected_qids),
        "selected_qids": selected_qids,
        "doc_ids": selected_doc_ids,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "root": str(root),
        "wiki_dir": str(wiki_dir),
        "dataset": dataset_key,
        "queries": len(selected_qids),
        "docs": len(selected_doc_ids),
        "qrels_relevances": manifest["qrels_relevances"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a qrels-centered BEIR wiki subset")
    parser.add_argument("dataset", choices=["scifact", "nfcorpus", "fiqa"])
    parser.add_argument("--queries", type=int, required=True)
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    print(json.dumps(prepare_subset(args.dataset, args.queries, args.name), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
