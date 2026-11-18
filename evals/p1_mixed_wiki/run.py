"""Build a held-out mixed Wiki, export Agent evidence, and score frozen answers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from random import Random
from typing import Any

import yaml
from corpus import SEED, Case, Doc, make_corpus

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ANSWER_HEADER = "## Retrieved Wiki Documents\n"
DOCUMENT = re.compile(r"^## DOC (\d+):", re.MULTILINE)
TERM_SPACES = re.compile(r"\s+")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized(value: str) -> str:
    return TERM_SPACES.sub("", unicodedata.normalize("NFKC", value).casefold())


def initialize(work: Path) -> Path:
    wiki = work / ".wiki"
    config = work / "wiki_config.yaml"
    config.write_text(
        "compile:\n  mode: agent\n"
        "query:\n  synthesis_mode: agent\n  max_results: 5\n  llm_query_expansion: false\n"
        "embeddings:\n  enabled: false\nreranker:\n  enabled: false\n",
        encoding="utf-8",
    )
    os.environ["LLM_WIKI_CONFIG"] = str(config)
    os.environ["LLM_WIKI_DIR"] = str(wiki)
    os.environ.pop("LLM_WIKI_SEARCH_STREAMS", None)
    os.environ.pop("LLM_WIKI_ALLOWED_SCOPES", None)
    os.environ.pop("LLM_WIKI_EXCLUDE_STATUSES", None)
    sys.path[:0] = [str(REPO / "scripts"), str(REPO)]

    return wiki


def concept_id(doc: Doc, page: int) -> str:
    prefix = "shuilian-" if doc.key in {"old", "new", "future"} else ""
    return f"concepts/{prefix}{doc.key}-p{page}"


def ingest(work: Path, docs: list[Doc]) -> tuple[dict, dict]:
    from compile_todo import update_task, verify_manifest
    from compile_v2 import create_agent_compile_task

    citations, sources = {}, {}
    for doc in docs:
        source = work / "documents" / doc.path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(doc.markdown(), encoding="utf-8")
        task = create_agent_compile_task(str(source))
        todo = Path(task["todo"])
        manifest = read_json(todo)
        (item,) = manifest["items"]
        update_task(todo, item["id"], "in_progress")
        outputs = []
        for i, (title, body) in enumerate(doc.pages, 1):
            identifier = concept_id(doc, i)
            output = Path(task["staged_pages"]) / f"{identifier}.md"
            output.parent.mkdir(parents=True, exist_ok=True)
            metadata = {
                "id": identifier,
                "type": "policy" if doc.metadata else "reference",
                "title": title,
                "description": doc.title,
                "tags": [doc.title],
                "source_citations": [{"artifact": item["source_citation"], "quote": title}],
                **doc.metadata,
            }
            output.write_text(
                "---\n"
                + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
                + f"---\n\n# {title}\n\n{body}\n",
                encoding="utf-8",
            )
            outputs.append(identifier)
        update_task(todo, item["id"], "completed", outputs=outputs)
        result = verify_manifest(todo)
        if not result["coverage_complete"]:
            raise RuntimeError(result["verification"])
        evidence = task["raw_evidence"]
        sources[doc.key] = {
            "path": doc.path,
            "source_id": evidence["source_id"],
            "source_version": evidence["source_version"],
            "physical_pages": len(doc.pages),
        }
        for i, identifier in enumerate(outputs, 1):
            citations[identifier] = [doc.key, i]
            citations[f"source/evidence/{evidence['source_key']}/pages/page-{i:04d}"] = [doc.key, i]
    return citations, sources


def capture_query(case: Case, citations: dict) -> dict[str, Any]:
    from query import query_wiki

    started = time.perf_counter_ns()
    result = query_wiki(case.question, mode="agent")
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    task_path = result.get("answer_task")
    if task_path:
        # The benchmark retains only its synthetic prompts, in the chosen workspace.
        Path(task_path).unlink(missing_ok=True)
    context = result["answer"].partition(ANSWER_HEADER)[2]
    starts = list(DOCUMENT.finditer(context))
    segments = {
        int(match[1]): context[
            match.start() : starts[i + 1].start() if i + 1 < len(starts) else None
        ].strip()
        for i, match in enumerate(starts)
    }
    evidence = []
    for i, item in enumerate(result["source_details"], 1):
        doc, page = citations.get(item["id"], [None, None])
        evidence.append(
            {
                "ref": i,
                "id": item["id"],
                "doc": doc,
                "page": page,
                "temporal": item.get("temporal", {}).get("state", "undated"),
                "text": segments.get(i, ""),
            }
        )
    return {
        "evidence": evidence,
        "time_ms": elapsed,
        "as_of": result["temporal_context"]["as_of"],
        "hint_exposed": "### Deterministic source calculation" in context,
    }


def write_packet(
    path: Path,
    cases: list[Case],
    captured: dict,
    sources: dict,
    label: str,
) -> None:
    order = list(cases)
    Random(f"{SEED}-{label}").shuffle(order)
    lines = [
        f"# Packet {label}",
        "Use only the evidence under each question. Identify the exact scope and effective date.",
        "If the retrieved documents do not support the requested answer, refuse rather than guess.",
        "Use an evidence number that contains the supporting fact itself. An extracted hint is "
        "a lead to check against the source, especially when several documents are present.",
        "Return one JSON line per case with id, status (answer/refuse), claims, "
        "and optional reason.",
        'Claim shape: {"slot": "listed slot", "value": "short exact answer", '
        '"citation": 1, "text": "a short factual sentence"}.',
        "For a refusal use claims: [] with a brief reason. Do not read the answer key.",
    ]
    for case in order:
        row = captured[case.key]
        lines += ["", f"## {case.key} {case.question}", f"Slots: {', '.join(case.slots)}"]
        for evidence in row["evidence"]:
            if not evidence["text"]:
                continue
            doc = sources.get(evidence["doc"], {})
            text = evidence["text"]
            text = re.sub(r"^\*\*Type\*\*:[^\n]+\n", "", text, flags=re.MULTILINE)
            text = re.sub(r"^\*\*Original source\*\*:[^\n]+\n", "", text, flags=re.MULTILINE)
            text = re.sub(r"^\*\*Scope\*\*:[^\n]+\n", "", text, flags=re.MULTILINE)
            lines += [
                f"[{evidence['ref']}] {doc.get('path', '')} · 页 {evidence['page']} · "
                f"{evidence['temporal']}",
                text.split("\n", 1)[-1].strip(),
            ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare(work: Path, rounds: int) -> None:
    work.mkdir(parents=True, exist_ok=False)
    docs, cases = make_corpus()
    frozen = {
        "seed": SEED,
        "documents": [asdict(doc) for doc in docs],
        "cases": [asdict(case) for case in cases],
    }
    write_json(work / "frozen-inputs.json", frozen)
    fingerprint = hashlib.sha256((work / "frozen-inputs.json").read_bytes()).hexdigest()
    initialize(work)
    citations, sources = ingest(work, docs)

    import raw_evidence
    from query import query_wiki

    original = raw_evidence._deterministic_answer_hints
    used = set()
    active = True

    def instrument(question, records):
        hints = original(question, records) if active else []
        used.update(hint["kind"] for hint in hints)
        return hints

    raw_evidence._deterministic_answer_hints = instrument
    result = query_wiki("评测缓存预热", mode="agent")
    if path := result.get("answer_task"):
        Path(path).unlink(missing_ok=True)
    rows = {"on": {}, "off": {}}
    seed = Random(SEED)
    order = list(cases)
    for repetition in range(rounds):
        seed.shuffle(order)
        for index, case in enumerate(order):
            # Alternate order so neither arm systematically benefits from warm caches.
            arms = ("on", "off") if (repetition + index) % 2 == 0 else ("off", "on")
            for arm in arms:
                active = arm == "on"
                used.clear()
                measured = capture_query(case, citations)
                current = rows[arm].get(case.key)
                if current is None:
                    rows[arm][case.key] = {
                        "evidence": measured["evidence"],
                        "as_of": measured["as_of"],
                        "hint_exposed": measured["hint_exposed"],
                        "hint_kinds": sorted(used),
                        "times_ms": [measured["time_ms"]],
                    }
                else:
                    if (
                        measured["evidence"] != current["evidence"]
                        or sorted(used) != current["hint_kinds"]
                    ):
                        raise RuntimeError(f"Retrieval changed between rounds for {case.key}/{arm}")
                    current["times_ms"].append(measured["time_ms"])
    raw_evidence._deterministic_answer_hints = original

    labels = ["packet-a", "packet-b"]
    arms = ["on", "off"]
    Random(SEED + 1).shuffle(arms)
    mask = dict(zip(labels, arms, strict=True))
    for label, arm in mask.items():
        write_packet(work / f"{label}.md", cases, rows[arm], sources, label)
    write_json(
        work / "retrieval.json",
        {
            "fingerprint": fingerprint,
            "source_inventory": sources,
            "rounds": rounds,
            "mask": mask,
            "rows": rows,
        },
    )
    print(f"{len(docs)} documents, {len(cases)} questions, {rounds} timed rounds per arm")
    print(f"Corpus and question SHA-256 {fingerprint}")


def supports(fact: dict, evidence: dict) -> bool:
    return (evidence["doc"], evidence["page"]) == (fact["doc"], fact["page"]) and normalized(
        fact["excerpt"]
    ) in normalized(evidence["text"])


def measure(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {}
    return {
        "n": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3),
    }


def score_case(case: dict, retrieval: dict, draft: dict, wiki: Path) -> dict:
    from query import verify_answer_evidence

    facts = case["facts"]
    expected = {fact["slot"]: fact for fact in facts}
    evidence = {item["ref"]: item for item in retrieval["evidence"]}
    recall = sum(any(supports(fact, item) for item in evidence.values()) for fact in facts)
    supported_slots = set()
    judgments = []
    answer_lines = []
    for claim in draft["claims"]:
        slot = claim["slot"]
        cited = evidence.get(claim["citation"])
        fact = expected.get(slot)
        supported = bool(
            draft["status"] == "answer"
            and fact
            and cited
            and slot not in supported_slots
            and normalized(claim["value"]) == normalized(fact["value"])
            and normalized(fact["value"]) in normalized(claim["text"])
            and supports(fact, cited)
        )
        if supported:
            supported_slots.add(slot)
        judgments.append(
            {
                **claim,
                "supported": supported,
                "cited_origin": ([cited["doc"], cited["page"]] if cited else None),
            }
        )
        identifier = cited["id"] if cited else "missing"
        answer_lines.append(f"{claim['text']} [证据](/{identifier}.md)")
    verify_ms = None
    verify_status = None
    verify_reasons = {}
    if answer_lines:
        pages = []
        for item in evidence.values():
            identifier = item["id"]
            is_raw = identifier.startswith("source/evidence/")
            location = (wiki if is_raw else wiki / "pages") / f"{identifier}.md"
            pages.append(
                {
                    "id": identifier,
                    "type": "source_evidence" if is_raw else "reference",
                    "path": str(location),
                }
            )
        tick = time.perf_counter_ns()
        report = verify_answer_evidence("\n".join(answer_lines), pages, case["question"])
        verify_ms = (time.perf_counter_ns() - tick) / 1_000_000
        verify_status = report["status"]
        verify_reasons = {
            key: report[key]
            for key in (
                "unverified_values",
                "polarity_conflicts",
                "temporal_conflicts",
                "unsupported_claims",
                "unsupported_citations",
                "missing_citations",
            )
            if report[key]
        }

    first = evidence.get(1, {})
    hit1 = any(supports(fact, first) for fact in facts) if first else False
    hints = [
        {"ref": item["ref"], "doc": item["doc"], "statement": hint}
        for item in evidence.values()
        for block in re.findall(
            r"^### Deterministic source calculation\n((?:- [^\n]+(?:\n|$))+)",
            item["text"],
            flags=re.MULTILINE,
        )
        for hint in block.splitlines()
    ]
    return {
        "id": case["key"],
        "question": case["question"],
        "group": case["group"],
        "language": case["language"],
        "control": case["control"],
        "answerable": bool(facts),
        "expected": facts,
        "evidence_hits": recall,
        "hit_at_1": hit1,
        "as_of": retrieval["as_of"],
        "hint_kinds": retrieval["hint_kinds"],
        "hint_exposed": retrieval["hint_exposed"],
        "visible_hints": hints,
        "top": [
            {key: value for key, value in e.items() if key != "text"} for e in evidence.values()
        ],
        "status": draft["status"],
        "reason": draft.get("reason", ""),
        "claims": judgments,
        "fully_supported": bool(facts)
        and len(supported_slots) == len(facts)
        and all(judgment["supported"] for judgment in judgments),
        "correct_refusal": not facts
        and draft["status"] == "refuse"
        and not judgments
        and bool(draft.get("reason")),
        "retrieval_times_ms": [round(value, 4) for value in retrieval["times_ms"]],
        "local_verify_ms": round(verify_ms, 4) if verify_ms is not None else None,
        "local_verify_status": verify_status,
        "local_verify_reasons": verify_reasons,
    }


def totals(rows: list[dict]) -> dict:
    positive = [row for row in rows if row["answerable"]]
    negative = [row for row in rows if not row["answerable"]]
    claims = [claim for row in rows for claim in row["claims"]]
    return {
        "questions": len(rows),
        "hit_at_1": [sum(row["hit_at_1"] for row in positive), len(positive)],
        "evidence_recall": [
            sum(row["evidence_hits"] for row in positive),
            sum(len(row["expected"]) for row in positive),
        ],
        "complete_evidence_at_5": [
            sum(row["evidence_hits"] == len(row["expected"]) for row in positive),
            len(positive),
        ],
        "citation_support": [sum(claim["supported"] for claim in claims), len(claims)],
        "correct_refusals": [sum(row["correct_refusal"] for row in negative), len(negative)],
        "false_refusals": [sum(row["status"] == "refuse" for row in positive), len(positive)],
        "fully_supported_answers": [sum(row["fully_supported"] for row in positive), len(positive)],
        "hint_triggered": sum(bool(row["hint_kinds"]) for row in rows),
        "hint_exposed": sum(row["hint_exposed"] for row in rows),
        "local_retrieval": measure([ms for row in rows for ms in row["retrieval_times_ms"]]),
        "verifier_pass_on_fully_supported": [
            sum(row["fully_supported"] and row["local_verify_status"] == "pass" for row in rows),
            sum(row["fully_supported"] for row in rows),
        ],
        "local_verification": measure(
            [row["local_verify_ms"] for row in rows if row["local_verify_ms"] is not None]
        ),
    }


def replay_drafts(baseline: dict, current: dict) -> list[dict]:
    """Keep prior Agent wording fixed and rebind each citation by source and page."""
    drafts = []
    for row in baseline["rows"]:
        evidence = current[row["id"]]["evidence"]
        prior_by_ref = {item["ref"]: item for item in row["top"]}
        claims = []
        for claim in row["claims"]:
            previous = prior_by_ref.get(claim["citation"])
            citation = 0
            if previous:
                candidates = [
                    item
                    for item in evidence
                    if [item["doc"], item["page"]] == claim["cited_origin"] and item["text"]
                ]
                preferred = next(
                    (
                        item
                        for item in candidates
                        if item["id"].startswith("source/evidence/")
                        == previous["id"].startswith("source/evidence/")
                    ),
                    None,
                )
                chosen = preferred or next(iter(candidates), None)
                citation = chosen["ref"] if chosen else 0
            claims.append(
                {
                    "slot": claim["slot"],
                    "value": claim["value"],
                    "text": claim["text"],
                    "citation": citation,
                }
            )
        drafts.append(
            {
                "id": row["id"],
                "status": row["status"],
                "reason": row["reason"],
                "claims": claims,
            }
        )
    return drafts


def score(work: Path, output: Path, replay_baseline: Path | None = None) -> None:
    wiki = initialize(work)
    from query import verify_answer_evidence

    verify_answer_evidence("基准预热", [], "预热")
    retrieval = read_json(work / "retrieval.json")
    frozen = work / "frozen-inputs.json"
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != retrieval["fingerprint"]:
        raise ValueError("Frozen corpus or questions changed")
    cases = read_json(frozen)["cases"]
    baseline = read_json(replay_baseline) if replay_baseline else None
    if baseline and baseline["corpus_sha256"] != retrieval["fingerprint"]:
        raise ValueError("Replay baseline uses a different corpus")
    checked = {}
    for label, arm in retrieval["mask"].items():
        if baseline:
            drafts = replay_drafts(baseline["arms"][arm], retrieval["rows"][arm])
        else:
            answer_path = work / f"{label}.answers.jsonl"
            drafts = [
                json.loads(line)
                for line in answer_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        keys = Counter(draft["id"] for draft in drafts)
        if keys != Counter(case["key"] for case in cases):
            raise ValueError(f"{label} needs exactly one answer per question: {keys}")
        if any(draft["status"] not in {"answer", "refuse"} for draft in drafts):
            raise ValueError(f"{label} contains an invalid answer status")
        by_id = {draft["id"]: draft for draft in drafts}
        rows = [
            score_case(case, retrieval["rows"][arm][case["key"]], by_id[case["key"]], wiki)
            for case in cases
        ]
        groups = {
            group: totals([row for row in rows if row["group"] == group])
            for group in dict.fromkeys(row["group"] for row in rows)
        }
        languages = {
            lang: totals([row for row in rows if not row["control"] and row["language"] == lang])
            for lang in dict.fromkeys(row["language"] for row in rows)
        }
        elapsed = work / f"{label}.seconds.txt"
        checked[arm] = {
            "core": totals([row for row in rows if not row["control"]]),
            "control": totals([row for row in rows if row["control"]]),
            "by_group": groups,
            "by_language": languages,
            "agent_batch_wall_seconds": float(elapsed.read_text())
            if not baseline and elapsed.is_file()
            else None,
            "rows": rows,
        }
    write_json(
        output,
        {
            "corpus_sha256": retrieval["fingerprint"],
            "runtime_files_sha256": {
                name: hashlib.sha256((REPO / "scripts" / name).read_bytes()).hexdigest()
                for name in (
                    "query.py",
                    "raw_evidence.py",
                    "compile_v2.py",
                    "query_temporal.py",
                    "answer_evidence.py",
                )
            },
            "source_inventory": retrieval["source_inventory"],
            "timed_rounds_per_arm": retrieval["rounds"],
            "ablation": "Disable only raw_evidence._deterministic_answer_hints in this process",
            "synthesis": (
                "Fixed prior host-Agent drafts; citations rebound by source and physical page"
                if baseline
                else "Current host Agent, one draft per case per arm, same-session batches"
            ),
            "arms": checked,
        },
    )
    print(
        json.dumps(
            {
                arm: {
                    section: result[section]
                    for section in ("core", "control", "agent_batch_wall_seconds")
                }
                for arm, result in checked.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--workspace", type=Path, required=True)
    prep.add_argument("--rounds", type=int, default=5)
    judge = sub.add_parser("score")
    judge.add_argument("--workspace", type=Path, required=True)
    judge.add_argument("--output", type=Path, required=True)
    judge.add_argument("--replay-baseline", type=Path, help="Keep prior Agent answers verbatim")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.rounds < 1:
            parser.error("--rounds must be positive")
        prepare(args.workspace.resolve(), args.rounds)
    else:
        score(args.workspace.resolve(), args.output.resolve(), args.replay_baseline)


if __name__ == "__main__":
    main()
