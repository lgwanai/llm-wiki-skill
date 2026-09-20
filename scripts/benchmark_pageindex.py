#!/usr/bin/env python3
"""Benchmark llm-wiki with PageIndex OSS Benchmark material.

The runner intentionally preserves PageIndex's document boundary: each question
is answered against a wiki compiled from exactly one PDF.  Predictions use the
same ``question`` / ``answer`` / ``answer_format`` / ``response`` schema as the
official MMLongBench-Doc-V2 judge.

Examples:
    python scripts/benchmark_pageindex.py run /path/to/PageIndex-OSS-Benchmark
    python scripts/benchmark_pageindex.py judge-configured predictions.json
    python scripts/benchmark_pageindex.py report predictions.judged.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve()
DEFAULT_CACHE = ROOT / ".benchmarks" / "pageindex-oss"
DEFAULT_RESULTS = ROOT / "evals" / "pageindex_oss_results"
PAGEINDEX_BENCHMARK_REPO = "https://github.com/VectifyAI/PageIndex-OSS-Benchmark"
PAGEINDEX_BENCHMARK_COMMIT = "ad4c0b92970a6f4801f09ff2e647389e8f5874fa"
PAGEINDEX_QUESTIONS_SHA256 = "f0cc046c0e3bdd4c8c4a4dc977e08e107d21d6a2d22fb8237914111d0f6e256e"
PAGEINDEX_DOCUMENTS_SHA256 = "f2625e712db1251976a135e000853df82fa182d547e52ab39d0ea1766d0c44d2"
PAGEINDEX_CORPUS_SHA256 = "a0ed377618ed48a6753d959062fd24cca3d1e607f5f490767ff510b57480a833"
MMLONGBENCH_REPO = "https://github.com/VectifyAI/MMLongBench-Doc-V2"
MMLONGBENCH_COMMIT = "3aba3c6831a432ee882f763435f9ebe92ab75ed9"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_fingerprint(documents_dir: Path, doc_ids: set[str] | None = None) -> str:
    digest = hashlib.sha256()
    paths = sorted(documents_dir.glob("*.pdf"))
    if doc_ids is not None:
        paths = [path for path in paths if path.name in doc_ids]
    for path in paths:
        digest.update(f"{path.name}\0{sha256_file(path)}\n".encode())
    return digest.hexdigest()


def validate_official_dataset(dataset_dir: Path) -> None:
    actual = {
        "questions.json": sha256_file(dataset_dir / "questions.json"),
        "documents.json": sha256_file(dataset_dir / "documents.json"),
        "PDF corpus": corpus_fingerprint(dataset_dir / "documents"),
    }
    expected = {
        "questions.json": PAGEINDEX_QUESTIONS_SHA256,
        "documents.json": PAGEINDEX_DOCUMENTS_SHA256,
        "PDF corpus": PAGEINDEX_CORPUS_SHA256,
    }
    mismatches = [
        f"{name}: expected {expected[name]}, got {value}"
        for name, value in actual.items()
        if value != expected[name]
    ]
    if mismatches:
        raise ValueError(
            "dataset does not match the pinned PageIndex OSS Benchmark commit:\n"
            + "\n".join(mismatches)
        )


def git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def runtime_fingerprint() -> str:
    """Fingerprint benchmark-relevant source, including uncommitted changes."""
    digest = hashlib.sha256()
    patterns = (
        "SKILL.md",
        "config/*.json",
        "references/*.md",
        "scripts/*.py",
        "templates/*.md",
    )
    paths = sorted({path for pattern in patterns for path in ROOT.glob(pattern)})
    for path in paths:
        if path.is_file():
            digest.update(f"{path.relative_to(ROOT)}\0".encode())
            digest.update(path.read_bytes())
            digest.update(b"\n")
    return digest.hexdigest()


def safe_model_config() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from config import get_llm_config

    config = get_llm_config()
    return {
        "provider": config.get("provider", "unknown"),
        "model": config.get("model", "unknown"),
        "temperature": config.get("temperature"),
        "max_context": config.get("max_context") or config.get("num_ctx"),
        "pdf_ingest": "native-text-layer-no-ocr",
    }


def load_dataset(dataset_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questions_path = dataset_dir / "questions.json"
    documents_path = dataset_dir / "documents.json"
    documents_dir = dataset_dir / "documents"
    for path in (questions_path, documents_path, documents_dir):
        if not path.exists():
            raise FileNotFoundError(f"PageIndex benchmark material missing: {path}")
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    documents = json.loads(documents_path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not isinstance(documents, list):
        raise ValueError("questions.json and documents.json must contain JSON lists")
    doc_ids = {row.get("doc_id") for row in documents}
    missing = sorted(
        {
            str(row.get("doc_id"))
            for row in questions
            if row.get("doc_id") not in doc_ids
            or not (documents_dir / str(row.get("doc_id"))).is_file()
        }
    )
    if missing:
        raise ValueError(f"questions reference missing documents: {missing}")
    return questions, documents


def select_cases(
    questions: list[dict[str, Any]],
    max_documents: int | None,
    max_questions: int | None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    docs: list[str] = []
    for row in questions:
        doc_id = str(row["doc_id"])
        if doc_id not in docs:
            if max_documents is not None and len(docs) >= max_documents:
                continue
            docs.append(doc_id)
        selected.append(row)
        if max_questions is not None and len(selected) >= max_questions:
            break
    return selected


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def case_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("doc_id", "")), " ".join(str(row.get("question", "")).split())


def wiki_cache_dir(
    cache_root: Path,
    document: Path,
    revision: str,
    model: dict[str, Any],
) -> Path:
    source_hash = sha256_file(document)[:12]
    config_hash = hashlib.sha256(
        json.dumps(model, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", document.stem).strip("-")[:48]
    return cache_root / "wikis" / f"{stem}-{source_hash}-{revision[:8]}-{config_hash}"


def recover_compile_records(cache_root: Path, document_ids: set[str]) -> list[dict[str, Any]]:
    """Recover the newest successful compile marker for every selected document."""
    newest: dict[str, tuple[float, dict[str, Any]]] = {}
    for marker in (cache_root / "wikis").glob("*/benchmark_compile.json"):
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source = str(record.get("source", ""))
        if source not in document_ids or record.get("status") != "ok":
            continue
        modified = marker.stat().st_mtime
        if source not in newest or modified > newest[source][0]:
            newest[source] = (modified, record)
    return [newest[source][1] for source in sorted(newest)]


def ensure_document_evidence(document: Path, wiki_dir: Path) -> dict[str, Any]:
    """Verify or backfill lossless evidence for one already-compiled document."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from raw_evidence import ingest_source_evidence, verify_evidence_bundle

    evidence_root = wiki_dir / "source" / "evidence"
    for manifest_path in evidence_root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            verification = verify_evidence_bundle(manifest_path)
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
        if manifest.get("source_name") == document.name and verification["coverage_complete"]:
            return {
                "status": "ok",
                "cached": True,
                "coverage_complete": True,
                "locator_units_indexed": verification["locator_units_indexed"],
                "manifest": str(manifest_path),
            }

    manifest = ingest_source_evidence(
        document,
        wiki_dir,
        native_pdf=True,
        redact=True,
    )
    return {
        "status": "ok",
        "cached": False,
        "coverage_complete": bool(manifest["coverage_complete"]),
        "locator_units_indexed": int(manifest["locator_units_indexed"]),
        "manifest": str(Path(manifest["raw_path"]).with_name("manifest.json")),
    }


def compile_document(
    document: Path,
    wiki_dir: Path,
    *,
    jobs: int,
    chunk_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    marker = wiki_dir / "benchmark_compile.json"
    expected_hash = sha256_file(document)
    if marker.exists() and (wiki_dir / "pages").is_dir():
        prior = json.loads(marker.read_text(encoding="utf-8"))
        if prior.get("source_sha256") == expected_hash and prior.get("status") == "ok":
            evidence = ensure_document_evidence(document, wiki_dir)
            result = prior | {
                "cached": True,
                "wiki_dir": str(wiki_dir),
                "raw_evidence": evidence,
            }
            marker.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result

    wiki_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LLM_WIKI_DIR"] = str(wiki_dir)
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "compile_v2.py"),
        str(document),
        "--mode",
        "llm",
        "--pdf-text-layer",
        "--chunk-tokens",
        str(chunk_tokens),
        "-j",
        str(max(1, min(jobs, 4))),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    (wiki_dir / "benchmark_compile.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (wiki_dir / "benchmark_compile.stderr.log").write_text(completed.stderr, encoding="utf-8")
    pages = list((wiki_dir / "pages").rglob("*.md")) if (wiki_dir / "pages").is_dir() else []
    result = {
        "status": "ok" if completed.returncode == 0 and pages else "failed",
        "source": document.name,
        "source_sha256": expected_hash,
        "seconds": round(elapsed, 3),
        "pages_created": len(pages),
        "returncode": completed.returncode,
        "cached": False,
        "wiki_dir": str(wiki_dir),
    }
    if result["status"] != "ok":
        marker.write_text(json.dumps(result, indent=2), encoding="utf-8")
        tail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"compile failed for {document.name}: {tail}")
    result["raw_evidence"] = ensure_document_evidence(document, wiki_dir)
    marker.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def query_document(
    question: str,
    wiki_dir: Path,
    *,
    timeout: int,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["LLM_WIKI_DIR"] = str(wiki_dir)
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "_query", question],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout)[-2000:])
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        tail = completed.stdout[-1000:]
        raise RuntimeError(f"query worker returned invalid JSON: {tail}") from exc
    payload["query_seconds"] = round(elapsed, 3)
    return payload


def build_manifest(
    dataset_dir: Path,
    cases: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    model: dict[str, Any],
) -> dict[str, Any]:
    selected_docs = {str(row["doc_id"]) for row in cases}
    metadata = [row for row in documents if str(row.get("doc_id")) in selected_docs]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": "llm-wiki compile_v2(llm) -> query(llm)",
        "pipeline_options": {
            "pdf_ingest": "native-text-layer-no-ocr",
            "chunk_policy": "configured cap only above model default context threshold",
        },
        "git_revision": git_revision(),
        "runtime_fingerprint": runtime_fingerprint(),
        "model": model,
        "dataset": {
            "source": PAGEINDEX_BENCHMARK_REPO,
            "commit": PAGEINDEX_BENCHMARK_COMMIT,
            "questions_sha256": sha256_file(dataset_dir / "questions.json"),
            "documents_sha256": sha256_file(dataset_dir / "documents.json"),
            "pdf_corpus_sha256": corpus_fingerprint(dataset_dir / "documents"),
            "selected_pdf_sha256": corpus_fingerprint(dataset_dir / "documents", selected_docs),
            "questions": len(cases),
            "documents": len(selected_docs),
            "pages": sum(int(row.get("pages", 0)) for row in metadata),
        },
        "scoring": {
            "official_judge_repo": MMLONGBENCH_REPO,
            "official_judge_commit": MMLONGBENCH_COMMIT,
            "prediction_schema_compatible": True,
        },
    }


def save_predictions(path: Path, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_path = path.with_name(f"{path.stem}.manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def run_benchmark(args: argparse.Namespace) -> int:
    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    questions, documents = load_dataset(dataset_dir)
    validate_official_dataset(dataset_dir)
    cases = select_cases(questions, args.max_documents, args.max_questions)
    if not cases:
        raise ValueError("no benchmark questions selected")
    model = safe_model_config()
    model["compile_chunk_tokens"] = args.chunk_tokens
    revision = git_revision()
    cache_root = Path(args.cache_dir).expanduser().resolve()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else DEFAULT_RESULTS / f"predictions-{stamp}.json"
    )
    prior_rows: list[dict[str, Any]] = []
    if output.exists() and args.resume:
        prior_rows = [
            row for row in json.loads(output.read_text(encoding="utf-8")) if not row.get("error")
        ]
    done = {case_key(row): row for row in prior_rows}
    rows = list(prior_rows)
    manifest_path = output.with_name(f"{output.stem}.manifest.json")
    if prior_rows and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = build_manifest(dataset_dir, cases, documents, model)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in cases:
        grouped.setdefault(str(row["doc_id"]), []).append(row)

    print(
        f"PageIndex-compatible benchmark: {len(cases)} questions / {len(grouped)} documents",
        flush=True,
    )
    compile_records = recover_compile_records(cache_root, set(grouped))
    completed_questions = 0
    for doc_index, (doc_id, doc_cases) in enumerate(grouped.items(), 1):
        if all(case_key(row) in done for row in doc_cases):
            completed_questions += len(doc_cases)
            print(
                f"[{doc_index}/{len(grouped)}] reuse {doc_id}: {len(doc_cases)} completed answers",
                flush=True,
            )
            continue
        document = dataset_dir / "documents" / doc_id
        wiki_dir = wiki_cache_dir(cache_root, document, revision, model)
        print(f"[{doc_index}/{len(grouped)}] compile {doc_id}", flush=True)
        try:
            compile_record = compile_document(
                document,
                wiki_dir,
                jobs=args.jobs,
                chunk_tokens=args.chunk_tokens,
                timeout=args.compile_timeout,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[-2000:]
            compile_record = {
                "status": "failed",
                "source": doc_id,
                "error": error,
                "wiki_dir": str(wiki_dir),
            }
            compile_records.append(compile_record)
            print(f"  ERROR compile {doc_id}: {error[-500:]}", flush=True)
            for row in doc_cases:
                key = case_key(row)
                if key in done:
                    completed_questions += 1
                    continue
                result = {**row, "response": "", "error": error}
                rows.append(result)
                done[key] = result
                completed_questions += 1
                print(
                    f"  [{completed_questions}/{len(cases)}] ERROR {row['question'][:72]}",
                    flush=True,
                )
            save_predictions(output, manifest | {"compile": compile_records}, rows)
            continue
        compile_records.append(compile_record)
        cache_label = "cached" if compile_record["cached"] else "built"
        print(
            f"  {cache_label}: {compile_record['pages_created']} pages in "
            f"{compile_record['seconds']:.1f}s",
            flush=True,
        )
        for row in doc_cases:
            key = case_key(row)
            if key in done:
                completed_questions += 1
                print(f"  [{completed_questions}/{len(cases)}] resume {row['question'][:72]}")
                continue
            try:
                answer = query_document(
                    str(row["question"]),
                    wiki_dir,
                    timeout=args.query_timeout,
                )
                result = {
                    **row,
                    "response": answer.get("answer", ""),
                    "retrieved_sources": answer.get("sources", []),
                    "pages_searched": answer.get("pages_searched", 0),
                    "query_seconds": answer.get("query_seconds"),
                    "verification": answer.get("verification", {}),
                    "error": None,
                }
            except Exception as exc:
                result = {**row, "response": "", "error": f"{type(exc).__name__}: {exc}"}
            rows.append(result)
            done[key] = result
            completed_questions += 1
            save_predictions(output, manifest | {"compile": compile_records}, rows)
            status = "ok" if not result.get("error") else "ERROR"
            print(
                f"  [{completed_questions}/{len(cases)}] {status} {row['question'][:72]}",
                flush=True,
            )

    manifest["compile"] = compile_records
    save_predictions(output, manifest, rows)
    print(f"wrote {output}")
    print("official scoring:")
    print(
        "  python -m eval.judge "
        f"{output} --out {output.with_name(output.stem + '.official-judged.json')}"
    )
    return 0


def rerun_queries(args: argparse.Namespace) -> int:
    """Reuse compiled OKF caches, backfill raw evidence, and rerun every query."""
    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    validate_official_dataset(dataset_dir)
    predictions = Path(args.predictions).expanduser().resolve()
    source_rows = json.loads(predictions.read_text(encoding="utf-8"))
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("predictions must contain a non-empty JSON list")

    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else predictions.with_name(f"{predictions.stem}.manifest.json")
    )
    if not manifest_path.is_file():
        raise FileNotFoundError(f"benchmark manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    compile_records = {
        str(record.get("source")): dict(record)
        for record in manifest.get("compile", [])
        if record.get("status") == "ok" and record.get("wiki_dir")
    }
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else predictions.with_name(f"{predictions.stem}-retrieval-{stamp}.json")
    )
    completed_rows: list[dict[str, Any]] = []
    if output.exists() and args.resume:
        completed_rows = [
            row for row in json.loads(output.read_text(encoding="utf-8")) if not row.get("error")
        ]
    done = {case_key(row): row for row in completed_rows}
    rows = list(completed_rows)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        grouped.setdefault(str(row["doc_id"]), []).append(row)

    refreshed_records: list[dict[str, Any]] = []
    total = len(source_rows)
    completed = 0
    for doc_index, (doc_id, doc_rows) in enumerate(grouped.items(), start=1):
        record = compile_records.get(doc_id)
        if not record:
            raise ValueError(f"no successful compile record for {doc_id}")
        wiki_dir = Path(record["wiki_dir"]).expanduser().resolve()
        document = dataset_dir / "documents" / doc_id
        evidence = ensure_document_evidence(document, wiki_dir)
        record["raw_evidence"] = evidence
        refreshed_records.append(record)
        cached_label = "cached" if evidence["cached"] else "backfilled"
        print(
            f"[{doc_index}/{len(grouped)}] {doc_id}: raw evidence {cached_label} "
            f"({evidence['locator_units_indexed']} units)",
            flush=True,
        )
        for source_row in doc_rows:
            key = case_key(source_row)
            if key in done:
                completed += 1
                continue
            clean_row = {
                key_name: value
                for key_name, value in source_row.items()
                if key_name
                not in {
                    "response",
                    "retrieved_sources",
                    "pages_searched",
                    "query_seconds",
                    "verification",
                    "error",
                    "llm_judge",
                    "judge_error",
                }
            }
            try:
                answer = query_document(
                    str(source_row["question"]),
                    wiki_dir,
                    timeout=args.query_timeout,
                )
                result = {
                    **clean_row,
                    "response": answer.get("answer", ""),
                    "retrieved_sources": answer.get("sources", []),
                    "pages_searched": answer.get("pages_searched", 0),
                    "query_seconds": answer.get("query_seconds"),
                    "verification": answer.get("verification", {}),
                    "error": None,
                }
            except Exception as exc:
                result = {
                    **clean_row,
                    "response": "",
                    "error": f"{type(exc).__name__}: {exc}"[-2000:],
                }
            rows.append(result)
            done[key] = result
            completed += 1
            rerun_manifest = manifest | {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "runtime_fingerprint": runtime_fingerprint(),
                "pipeline": "cached OKF + lossless raw evidence -> query(llm)",
                "baseline_predictions": str(predictions),
                "compile": refreshed_records,
            }
            save_predictions(output, rerun_manifest, rows)
            status = "ok" if not result.get("error") else "ERROR"
            print(
                f"  [{completed}/{total}] {status} {source_row['question'][:72]}",
                flush=True,
            )

    final_manifest = manifest | {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_fingerprint": runtime_fingerprint(),
        "pipeline": "cached OKF + lossless raw evidence -> query(llm)",
        "baseline_predictions": str(predictions),
        "compile": refreshed_records,
    }
    save_predictions(output, final_manifest, rows)
    print(f"wrote {output}")
    return 0


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("judge response is not a JSON object")
    return value


def load_official_judge_prompt(path: Path) -> str:
    """Load the pinned judge's PROMPT constant without executing its module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "PROMPT" for target in targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, str):
                break
            required = ("{question}", "{answer}", "{answer_format}", "{response}")
            if not all(field in value for field in required):
                raise ValueError("official judge PROMPT is missing required fields")
            return value
    raise ValueError(f"PROMPT string not found in official judge file: {path}")


def configured_judge_prompt(row: dict[str, Any], template: str | None = None) -> str:
    response = str(row.get("response", ""))[:12000]
    if template is not None:
        return template.format(
            question=" ".join(str(row.get("question", "")).split()),
            answer=row.get("answer", ""),
            answer_format=row.get("answer_format", ""),
            response=response,
        )
    return f"""Decide whether a document-QA system's response gives the same answer as the
reference.

<question>{row.get("question", "")}</question>
<reference_answer>{row.get("answer", "")}</reference_answer>
<expected_format>{row.get("answer_format", "")}</expected_format>
<system_response>{response}</system_response>

Treat the reference as correct. Judge the answer actually stated, not formatting.
Equivalent answers may differ in wording, case, punctuation, list order, numeric formatting,
units, or harmless qualifiers. Mark false for a different value/entity/date, missing or extra
list members, wrong granularity, a shotgun list, or a refusal when the reference is answerable.
If the reference starts with "Not answerable", only a response that commits to no answer is
equivalent. Set abstained=true whenever the response commits to no answer.

Return JSON only:
{{"equivalent": true_or_false, "abstained": true_or_false, "reason": "one sentence"}}"""


def judge_configured(args: argparse.Namespace) -> int:
    predictions = Path(args.predictions).expanduser().resolve()
    rows = json.loads(predictions.read_text(encoding="utf-8"))
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else predictions.with_name(f"{predictions.stem}.configured-judged.json")
    )
    if output.exists() and args.resume:
        prior = {case_key(row): row.get("llm_judge") for row in json.loads(output.read_text())}
        for row in rows:
            if prior.get(case_key(row)):
                row["llm_judge"] = prior[case_key(row)]
    sys.path.insert(0, str(ROOT / "scripts"))
    from _llm_utils import call_llm

    judge_template: str | None = None
    prompt_source = "llm-wiki directional rubric"
    if args.official_judge_file:
        judge_path = Path(args.official_judge_file).expanduser().resolve()
        judge_template = load_official_judge_prompt(judge_path)
        prompt_source = f"{MMLONGBENCH_REPO}@{MMLONGBENCH_COMMIT}:eval/judge.py:PROMPT"
    prompt_sha256 = hashlib.sha256(
        (judge_template or configured_judge_prompt({})).encode("utf-8")
    ).hexdigest()
    judge_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "judge": safe_model_config(),
        "prompt_source": prompt_source,
        "prompt_sha256": prompt_sha256,
        "official_model_match": False,
        "comparability": (
            "Directional only: official prompt text is reused, but the configured model "
            "and structured-output transport differ from the official luna/high judge."
        ),
    }
    judge_manifest_path = output.with_name(f"{output.stem}.judge-manifest.json")
    judge_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    judge_manifest_path.write_text(
        json.dumps(judge_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    total = len(rows)
    for index, row in enumerate(rows, 1):
        if "llm_judge" in row:
            continue
        if row.get("error") or not str(row.get("response", "")).strip():
            verdict = {
                "equivalent": False,
                "abstained": True,
                "reason": "The benchmark system returned no answer.",
            }
        else:
            try:
                raw = call_llm(
                    "You are a strict semantic-equivalence judge. Return JSON only.",
                    configured_judge_prompt(row, judge_template),
                    max_tokens=512,
                    temperature=0,
                )
                parsed = extract_json_object(raw)
                verdict = {
                    "equivalent": bool(parsed.get("equivalent")),
                    "abstained": bool(parsed.get("abstained")),
                    "reason": str(parsed.get("reason", ""))[:500],
                }
            except Exception as exc:
                verdict = {
                    "equivalent": False,
                    "abstained": False,
                    "reason": f"judge failed: {type(exc).__name__}: {exc}",
                }
        row["llm_judge"] = verdict
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"[{index}/{total}] {'EQUIV' if verdict['equivalent'] else 'no'} "
            f"{str(row.get('answer', ''))[:50]}",
            flush=True,
        )
    print(f"wrote {output}")
    return 0


def metrics(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    judged = [row for row in rows if isinstance(row.get("llm_judge"), dict)]
    equivalent = sum(bool(row["llm_judge"].get("equivalent")) for row in judged)
    errors = sum(bool(row.get("error")) for row in rows)
    latencies = [float(row["query_seconds"]) for row in rows if row.get("query_seconds")]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in judged:
        by_type.setdefault(str(row.get("doc_type", "unknown")), []).append(row)
    compile_rows = (manifest or {}).get("compile", [])
    compile_unique = {
        str(row.get("source")): row
        for row in compile_rows
        if isinstance(row, dict) and row.get("source")
    }
    result = {
        "questions": len(rows),
        "judged": len(judged),
        "correct": equivalent,
        "accuracy": equivalent / len(judged) if judged else 0.0,
        "errors": errors,
        "query_latency_seconds": {
            "mean": statistics.mean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "by_document_type": {
            name: {
                "questions": len(group),
                "correct": sum(bool(row["llm_judge"].get("equivalent")) for row in group),
                "accuracy": (
                    sum(bool(row["llm_judge"].get("equivalent")) for row in group) / len(group)
                ),
            }
            for name, group in sorted(by_type.items())
        },
    }
    if compile_unique:
        compile_seconds = [float(row.get("seconds", 0)) for row in compile_unique.values()]
        result["indexing"] = {
            "documents": len(compile_unique),
            "seconds_total": sum(compile_seconds),
            "seconds_mean": statistics.mean(compile_seconds),
            "knowledge_pages": sum(
                int(row.get("pages_created", 0)) for row in compile_unique.values()
            ),
            "cached_documents": sum(bool(row.get("cached")) for row in compile_unique.values()),
        }
    return result


def render_report(result: dict[str, Any], predictions: Path) -> str:
    lines = [
        "# llm-wiki — PageIndex OSS Benchmark",
        "",
        f"- Predictions: `{predictions.name}`",
        f"- Questions: {result['questions']}",
        f"- Judged: {result['judged']}",
        f"- Correct: {result['correct']}",
        f"- Accuracy: **{result['accuracy']:.1%}**",
        f"- Runtime errors: {result['errors']}",
        f"- Query latency mean / p50 / p95: "
        f"{result['query_latency_seconds']['mean']:.2f}s / "
        f"{result['query_latency_seconds']['p50']:.2f}s / "
        f"{result['query_latency_seconds']['p95']:.2f}s",
        "",
        "## By document type",
        "",
        "| Type | Questions | Correct | Accuracy |",
        "|---|---:|---:|---:|",
    ]
    for name, row in result["by_document_type"].items():
        lines.append(f"| {name} | {row['questions']} | {row['correct']} | {row['accuracy']:.1%} |")
    lines.extend(
        [
            "",
            "## Comparability",
            "",
            "The PDFs, questions, reference answers, prediction schema, and semantic-equivalence "
            "rubric follow PageIndex-OSS-Benchmark. A score produced by `judge-configured` is "
            "directional because it uses llm-wiki's configured model, not PageIndex's pinned "
            "gpt-5.6-luna/high judge. Run the official MMLongBench-Doc-V2 `eval.judge` command "
            "for a directly comparable score.",
            "",
        ]
    )
    indexing = result.get("indexing")
    if indexing:
        lines[8:8] = [
            f"- Indexed documents: {indexing['documents']}",
            f"- Generated knowledge pages: {indexing['knowledge_pages']}",
            f"- Indexing time total / mean: {indexing['seconds_total']:.2f}s / "
            f"{indexing['seconds_mean']:.2f}s per document",
        ]
    return "\n".join(lines)


def report(args: argparse.Namespace) -> int:
    predictions = Path(args.predictions).expanduser().resolve()
    rows = json.loads(predictions.read_text(encoding="utf-8"))
    manifest: dict[str, Any] | None = None
    manifest_path: Path | None = None
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser().resolve()
    else:
        base = re.sub(r"\.(?:configured|official)-judged$", "", predictions.stem)
        candidate = predictions.with_name(f"{base}.manifest.json")
        if candidate.exists():
            manifest_path = candidate
    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = metrics(rows, manifest)
    output = (
        Path(args.output).expanduser().resolve() if args.output else predictions.with_suffix(".md")
    )
    output.write_text(render_report(result, predictions), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"wrote {output}")
    return 0


def query_worker(question: str) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from query import query_wiki

    result = query_wiki(question, mode="llm")
    payload = {
        "answer": result.get("answer_text") or result.get("answer", ""),
        "sources": result.get("sources", []),
        "pages_searched": result.get("pages_searched", 0),
        "verification": result.get("verification", {}),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="compile PDFs and produce judge-compatible answers")
    run.add_argument("dataset_dir", help="PageIndex-OSS-Benchmark checkout or extracted archive")
    run.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    run.add_argument("--output")
    run.add_argument("--max-documents", type=int)
    run.add_argument("--max-questions", type=int)
    run.add_argument("--jobs", type=int, default=2)
    run.add_argument(
        "--chunk-tokens",
        type=int,
        default=12_000,
        help="chunk cap for documents beyond the model default threshold",
    )
    run.add_argument("--compile-timeout", type=int, default=3600)
    run.add_argument("--query-timeout", type=int, default=300)
    run.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)

    rerun = subparsers.add_parser(
        "rerun-queries",
        help="reuse compiled wikis, backfill raw evidence, and rerun retrieval",
    )
    rerun.add_argument("dataset_dir")
    rerun.add_argument("predictions")
    rerun.add_argument("--manifest")
    rerun.add_argument("--output")
    rerun.add_argument("--query-timeout", type=int, default=300)
    rerun.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)

    judge = subparsers.add_parser(
        "judge-configured",
        help="directional semantic judge using llm-wiki's configured model",
    )
    judge.add_argument("predictions")
    judge.add_argument("--output")
    judge.add_argument(
        "--official-judge-file",
        help="load the exact PROMPT constant from pinned MMLongBench eval/judge.py",
    )
    judge.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)

    report_parser = subparsers.add_parser("report", help="summarize a judged predictions file")
    report_parser.add_argument("predictions")
    report_parser.add_argument("--output")
    report_parser.add_argument("--manifest")

    worker = subparsers.add_parser("_query", help=argparse.SUPPRESS)
    worker.add_argument("question")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "run":
        return run_benchmark(args)
    if args.command == "rerun-queries":
        return rerun_queries(args)
    if args.command == "judge-configured":
        return judge_configured(args)
    if args.command == "report":
        return report(args)
    if args.command == "_query":
        return query_worker(args.question)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
