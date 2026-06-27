#!/usr/bin/env python3
"""Query-driven knowledge-base maintenance — 4-phase optimisation pipeline.

``wiki dream`` runs in four interruptible stages:

  Phase 1 — Light Sleep:   update page metadata from today's queries (safe, automatic)
  Phase 2 — Audit:         aggregate N-day logs → Agent merges similar queries → Top-10 report
  Phase 3 — Purify:        simulate Top-10 searches → detect duplicates / low-density → proposals
  Phase 4 — Enrich:        low-density + high-frequency pages → Agent deep-research → drafts

Human-initiated ``wiki compile`` or ``wiki query`` cancels the worker immediately.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from _experience import Experience, ExperienceStore
from _quality import (
    QualityReport,
    assess_quality,
    collect_test_queries,
    run_search_baseline,
)
from _snapshot import create_snapshot, ensure_git_repo, rollback
from config import get_wiki_dir

# ── constants ────────────────────────────────────────────────────────────────

AUDIT_WINDOW_DAYS = 7
TOP_N_AUDIT = 50      # queries to analyse
TOP_N_PURIFY = 10     # queries to simulate-search
TOP_N_ENRICH = 10     # max enrichment targets
MIN_QUERY_COUNT = 2   # minimum before a query is considered recurring
LOW_DENSITY_THRESHOLD = 1200  # chars (excluding whitespace)

LOW_VALUE_QUERIES = {
    "", "嗯", "哦", "好的", "好", "ok", "yes", "no", "thanks", "谢谢",
}

# ── exceptions ────────────────────────────────────────────────────────────────

class DreamCancelled(RuntimeError):
    """Raised when a dream worker is cancelled by a new query or compile."""
    pass


# ── time helpers ──────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _day_offset(offset_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=offset_days)).strftime("%Y%m%d")


# ── paths ─────────────────────────────────────────────────────────────────────

def _dream_dir() -> Path:
    return get_wiki_dir() / "dream"


def _status_path() -> Path:
    return _dream_dir() / "status.json"


def _cancel_path() -> Path:
    return _dream_dir() / "cancel.flag"


# ── status / cancel machinery ─────────────────────────────────────────────────

def _write_status(state: str, stage: str, message: str) -> None:
    directory = _dream_dir()
    directory.mkdir(parents=True, exist_ok=True)
    old = _read_json(_status_path(), {})
    now = _now()
    _status_path().write_text(
        json.dumps(
            {
                "state": state,
                "stage": stage,
                "pid": os.getpid(),
                "started_at": old.get("started_at", now),
                "updated_at": now,
                "message": message,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _check_cancelled() -> None:
    if _cancel_path().exists():
        _write_status("cancelled", "cancelled", "Dream cancelled by a new query or compile")
        raise DreamCancelled("Dream cancelled")


def cancel_active_dream(reason: str) -> None:
    """Request cancellation of any active dream worker.

    The cancel flag is the durable mechanism — workers poll it before every
    state change.
    """
    directory = _dream_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _cancel_path().write_text(
        json.dumps({"reason": reason, "timestamp": _now()}), encoding="utf-8"
    )
    status = _read_json(_status_path(), {})
    if isinstance(status, dict) and status.get("state") == "running":
        _write_status("cancelled", "cancelled", f"Dream cancelled: {reason}")


# ── query logging ─────────────────────────────────────────────────────────────

def log_query(result: dict, synthesis: bool) -> None:
    """Append a query event; logging must never fail the calling query."""
    audit_dir = get_wiki_dir() / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now(),
        "question": result.get("query", ""),
        "format": result.get("format", "markdown"),
        "synthesis": synthesis,
        "answer_chars": len(result.get("answer", "")),
        "sources": result.get("source_details", []),
    }
    with (audit_dir / f"query-log-{_today()}.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── query normalisation ───────────────────────────────────────────────────────

def _normalize_query(query: str) -> str:
    value = query.strip().lower().strip("?!？！。，, ")
    for phrase in ("我喜欢", "我偏好", "首选", "i like", "my preferred", "my favorite is"):
        value = value.replace(phrase, " ")
    return " ".join(value.split())


def _is_low_value(query: str) -> bool:
    return len(query) <= 1 or query in LOW_VALUE_QUERIES


def _terms(query: str) -> list[str]:
    stripped = re.sub(
        r"(?:是什么|怎么|如何|为什么|请问|查询|介绍|what is|how to|why)",
        " ", query, flags=re.I,
    )
    values = [
        term.strip("?!？！。，, ")
        for term in re.split(r"\s+", stripped)
        if len(term.strip()) >= 2
    ]
    return list(dict.fromkeys(values))[:8] or [query]


# ── page helpers ──────────────────────────────────────────────────────────────

def _read_page(path: Path) -> tuple[dict, str] | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, flags=re.DOTALL)
    if not match:
        return None
    frontmatter = yaml.safe_load(match.group(1)) or {}
    return (frontmatter if isinstance(frontmatter, dict) else {}, match.group(2))


def _write_page(path: Path, frontmatter: dict, body: str) -> None:
    content = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    content += "\n---\n\n" + body.lstrip()
    path.write_text(content, encoding="utf-8")


def _append_unique(frontmatter: dict, key: str, values: list[str], limit: int) -> int:
    existing = frontmatter.get(key, [])
    if isinstance(existing, str):
        existing = [existing]
    if not isinstance(existing, list):
        existing = []
    normalized = {_normalize_query(str(item)) for item in existing}
    added = 0
    for value in values:
        clean = value.strip()
        normalized_clean = _normalize_query(clean)
        if clean and not _is_low_value(normalized_clean) and normalized_clean not in normalized:
            existing.append(clean)
            normalized.add(normalized_clean)
            added += 1
        if len(existing) >= limit:
            break
    frontmatter[key] = existing[:limit]
    return added


def _page_density(body: str) -> int:
    return len(re.sub(r"\s+", "", body))


# ── multi-day log reader ──────────────────────────────────────────────────────

def _read_logs(days: int = AUDIT_WINDOW_DAYS) -> list[dict]:
    """Read query-log entries from the last `days` days, oldest first."""
    audit_dir = get_wiki_dir() / "audit"
    entries: list[dict] = []
    for offset in range(days - 1, -1, -1):
        path = audit_dir / f"query-log-{_day_offset(offset)}.jsonl"
        if not path.exists():
            continue
        for linenum, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    entries.append(entry)
            except json.JSONDecodeError:
                print(
                    f"  WARNING: corrupt line {linenum} in {path}, skipping: "
                    f"{line[:80]}{'...' if len(line) > 80 else ''}",
                    file=sys.stderr,
                )
    return entries


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1 — Light Sleep: metadata updates (safe, automatic)
# ══════════════════════════════════════════════════════════════════════════════

def phase_light_sleep() -> list[dict]:
    """Update page metadata from today's query log.

    Returns list of grouped query items with count, examples, sources,
    target-path, and density.
    """
    _write_status("running", "light", "Phase 1/4: Light sleep — metadata optimisation")

    # Aggregate queries by normalised form
    grouped: dict[str, dict] = {}
    for entry in _read_logs(days=1):
        _check_cancelled()
        normalized = _normalize_query(str(entry.get("question", "")))
        if _is_low_value(normalized):
            continue
        group = grouped.setdefault(
            normalized,
            {"query": normalized, "count": 0, "examples": [], "sources": []},
        )
        group["count"] += 1
        if entry.get("question") not in group["examples"]:
            group["examples"].append(entry["question"])
        group["sources"].extend(entry.get("sources", []))

    items = sorted(grouped.values(), key=lambda it: (-it["count"], it["query"]))

    # Write metadata back to each target page
    for item in items:
        _check_cancelled()
        sources = [s for s in item["sources"] if isinstance(s, dict)]
        sources.sort(key=lambda s: s.get("relevance", 0), reverse=True)
        target = next(
            (Path(s["path"]) for s in sources if Path(s.get("path", "")).is_file()),
            None,
        )
        if not target:
            item["action"] = "no editable target page"
            continue

        page = _read_page(target)
        if not page:
            item["action"] = "target lacks YAML frontmatter"
            continue

        frontmatter, body = page
        item["_target_path"] = str(target.resolve())
        item["_density"] = _page_density(body)

        added = _append_unique(frontmatter, "questions", [item["examples"][0], item["query"]], 12)
        added += _append_unique(frontmatter, "keywords", _terms(item["query"]), 24)
        fact = f"Dream observed query intent '{item['query']}' {item['count']} time(s)"
        added += _append_unique(frontmatter, "facts", [fact], 16)
        frontmatter["dream_last_touched"] = _now()
        frontmatter["dream_query_count"] = (
            int(frontmatter.get("dream_query_count") or 0) + item["count"]
        )
        if added:
            _write_page(target, frontmatter, body)
        item["action"] = (
            f"updated {target.name} ({added} metadata additions)"
            if added
            else f"{target.name} already covered"
        )

    # Persist light-sleep report
    directory = _dream_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{_today()}-light.json").write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    return items


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Audit: multi-day analysis → Agent task
# ══════════════════════════════════════════════════════════════════════════════

def phase_audit(light_items: list[dict]) -> Path:
    """Aggregate N-day query logs and produce an Agent analysis task.

    The Agent is expected to:
    1. Semantically merge similar queries
    2. Identify the top recurring information needs
    3. Flag queries whose search results suggest knowledge gaps

    Returns path to the audit task file.
    """
    _write_status("running", "audit", f"Phase 2/4: Audit — analysing {AUDIT_WINDOW_DAYS}d query trends")
    _check_cancelled()

    entries = _read_logs(days=AUDIT_WINDOW_DAYS)
    if not entries:
        output = _dream_dir() / f"{_today()}-audit.md"
        output.write_text("# Dream Audit\n\nNo queries recorded in the last "
                          f"{AUDIT_WINDOW_DAYS} days.\n", encoding="utf-8")
        return output

    # Build raw query stats for the Agent to interpret
    query_counts: dict[str, dict] = {}
    for entry in entries:
        raw = str(entry.get("question", "")).strip()
        if _is_low_value(_normalize_query(raw)):
            continue
        if raw not in query_counts:
            query_counts[raw] = {"count": 0, "latest": "", "sources": []}
        query_counts[raw]["count"] += 1
        query_counts[raw]["latest"] = entry.get("timestamp", "")
        query_counts[raw]["sources"].extend(entry.get("sources", []))

    # Sort by frequency
    ranked = sorted(query_counts.items(), key=lambda kv: -kv[1]["count"])
    top = ranked[:TOP_N_AUDIT]

    # Compile per-query source stats
    query_blocks: list[str] = []
    for i, (raw_query, stats) in enumerate(top, start=1):
        source_ids = list({
            s.get("id", "?") for s in stats["sources"] if isinstance(s, dict)
        })[:10]
        query_blocks.append(
            f"### Q{i}: [{stats['count']}×] {raw_query}\n\n"
            f"Last seen: {stats['latest']}\n"
            f"Top sources: {', '.join(f'[[{s}]]' for s in source_ids) if source_ids else 'none'}\n"
        )

    # Write Agent task
    output = _dream_dir() / f"{_today()}-audit.md"
    output.write_text(
        f"""# Dream Audit — {_today()} ({AUDIT_WINDOW_DAYS}d window)

> **Phase 2/4**: {len(entries)} queries, {len(ranked)} unique, top {TOP_N_AUDIT} shown.

## Agent Task: Semantic Query Analysis

1. **Merge similar queries**: group queries that ask the same question in
   different words.  Example: "What is X?" / "Tell me about X" / "Explain X"
   → one canonical form.
2. **Identify top 10 information needs**: rank by frequency, pick the 10 most
   important questions users actually ask.
3. **Flag knowledge gaps**: for each top-10 query, note whether the retrieved
   sources fully answer it.  Mark queries whose answers rely on a single thin
   page.

Output your analysis into `{_dream_dir() / f'{_today()}-audit-analysis.md'}`.

## Raw Query Data (frequency-ordered, top {TOP_N_AUDIT})

{chr(10).join(query_blocks)}
""",
        encoding="utf-8",
    )

    _check_cancelled()
    return output


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Purify: simulate searches → duplicate / density proposals
# ══════════════════════════════════════════════════════════════════════════════

def _run_search(query_text: str) -> dict | None:
    """Run a local wiki search and return structured results."""
    try:
        from query import query_wiki
        return query_wiki(query_text, synthesis=False, mode="agent")
    except Exception as exc:
        print(f"  WARNING: search failed for '{query_text[:60]}': {exc}", file=sys.stderr)
        return None


def _analyze_search_results(
    query_text: str, result: dict, threshold: int = LOW_DENSITY_THRESHOLD,
) -> dict:
    """Extract per-result analysis: density, duplicates, coverage."""
    sources = result.get("source_details", []) if result else []
    analysed: list[dict] = []
    seen_bodies: dict[str, str] = {}  # normalised-first-200 → page-id

    for src in sources[:8]:
        path = Path(src.get("path", ""))
        if not path.is_file():
            analysed.append({**src, "status": "missing"})
            continue

        page = _read_page(path)
        if not page:
            analysed.append({**src, "status": "no-frontmatter"})
            continue

        _, body = page
        density = _page_density(body)
        # Simple duplicate detection: first 200 non-whitespace chars
        signature = re.sub(r"\s+", "", body)[:200]
        duplicate_of = seen_bodies.get(signature)
        if duplicate_of:
            analysed.append({
                **src,
                "density": density,
                "status": "duplicate",
                "duplicate_of": duplicate_of,
            })
        else:
            seen_bodies[signature] = src.get("id", "unknown")
            status = "ok" if density >= threshold else "low-density"
            analysed.append({**src, "density": density, "status": status})

    return {
        "query": query_text,
        "pages_found": result.get("pages_searched", 0) if result else 0,
        "results": analysed,
    }


def phase_purify(
    auto: bool = False,
    experiences: ExperienceStore | None = None,
    prior_context: str = "",
) -> Path | dict:
    """Run local searches for top queries, detect duplicates and low-density.

    When auto=False (default): produces a merge/density proposal for Agent
    review.  Does NOT modify any page content — only writes a report.

    When auto=True:
    1. Run searches, detect duplicates (unchanged logic)
    2. Create git snapshot of affected pages
    3. Run baseline quality queries
    4. Execute mechanical merges
    5. Run post-modification quality queries
    6. Compute QualityReport → keep/warn/rollback
    7. Record experience if rollback/warning

    Returns Path (report file, auto=False) or dict with results (auto=True).
    """
    _write_status("running", "purify", "Phase 3/4: Purify — simulating searches")
    _check_cancelled()

    # Collect candidate queries from recent entries
    entries = _read_logs(days=AUDIT_WINDOW_DAYS)
    query_counts: dict[str, int] = {}
    for entry in entries:
        raw = str(entry.get("question", "")).strip()
        norm = _normalize_query(raw)
        if _is_low_value(norm):
            continue
        query_counts[raw] = query_counts.get(raw, 0) + 1

    top = sorted(query_counts.items(), key=lambda kv: -kv[1])
    candidates = [(q, c) for q, c in top if c >= MIN_QUERY_COUNT][:TOP_N_PURIFY]
    if not candidates:
        output = _dream_dir() / f"{_today()}-purify.md"
        output.write_text(
            "# Dream Purify\n\nInsufficient recurring queries to analyse.\n",
            encoding="utf-8",
        )
        return output

    # Run searches and analyse
    analyses: list[dict] = []
    for query_text, count in candidates:
        _check_cancelled()
        print(f"  Searching: {query_text[:80]} ({count}×)", file=sys.stderr)
        result = _run_search(query_text)
        analysis = _analyze_search_results(query_text, result)
        analysis["query_count"] = count
        analyses.append(analysis)

    # Build merge candidates (duplicates across different queries)
    duplicate_groups: list[dict] = []
    for a in analyses:
        dups = [r for r in a["results"] if r.get("status") == "duplicate"]
        if dups:
            duplicate_groups.append({
                "query": a["query"],
                "duplicates": dups,
            })

    # Build low-density report
    low_density_pages: dict[str, dict] = {}
    for a in analyses:
        for r in a["results"]:
            if r.get("status") == "low-density":
                pid = r.get("id", "unknown")
                if pid not in low_density_pages:
                    low_density_pages[pid] = {
                        "id": pid,
                        "name": r.get("name", pid),
                        "path": r.get("path", ""),
                        "density": r.get("density", 0),
                        "queried_by": [],
                    }
                low_density_pages[pid]["queried_by"].append(a["query"])

    # Write report
    output = _dream_dir() / f"{_today()}-purify.md"
    sections = [
        f"# Dream Purify — {_today()}",
        "",
        f"Analysed {len(analyses)} recurring queries ({len(candidates)} candidates).",
        "",
    ]

    if duplicate_groups:
        sections.append("## Duplicate Content Detected")
        sections.append("")
        sections.append("> Agent: review these duplicates and decide whether to merge pages.")
        sections.append("")
        for g in duplicate_groups:
            sections.append(f"### Query: {g['query']}")
            for d in g["duplicates"]:
                sections.append(
                    f"- **[[{d.get('id', '?')}]]** is duplicate of "
                    f"**[[{d.get('duplicate_of', '?')}]]**"
                )
            sections.append("")

    if low_density_pages:
        sections.append("## Low-Density Pages")
        sections.append("")
        sections.append("| Page | Density (chars) | Queried By |")
        sections.append("|------|-----------------|------------|")
        for pid, info in sorted(
            low_density_pages.items(),
            key=lambda kv: kv[1]["density"],
        ):
            queried_by = ", ".join(info["queried_by"][:3])
            sections.append(f"| [[{pid}]] | {info['density']} | {queried_by} |")
        sections.append("")

    if not duplicate_groups and not low_density_pages:
        sections.append("✅ No duplicate or low-density issues detected.")

    sections.append("## Agent Task")
    sections.append("")
    sections.append(
        "1. **Merge duplicates**: for each duplicate pair, decide if the "
        "pages should be consolidated.  If yes, create a merge task — do NOT "
        "auto-execute.  Merging may break wikilinks; validate before committing."
    )
    sections.append(
        "2. **Evaluate low-density pages**: check whether flagged pages contain "
        "enough information to answer their associated queries.  If not, "
        "proceed to Phase 4 enrichment."
    )

    output.write_text("\n".join(sections) + "\n", encoding="utf-8")
    _check_cancelled()

    # ── auto-execute path ──────────────────────────────────────────────────
    if auto and experiences is not None:
        wiki_dir = get_wiki_dir()
        modified_paths: list[Path] = []
        merged_count = 0
        removed_count = 0
        outcome = "no_changes"
        quality_report: QualityReport | None = None
        exp_recorded = False

        if duplicate_groups or low_density_pages:
            # 1. Snapshot before modifications — ABORT if git unavailable
            snapshot_hash = create_snapshot(wiki_dir, "pre-phase3-purify")
            if not snapshot_hash:
                print("  [dream/purify] ABORTING auto-merge: git snapshot unavailable — "
                      "falling back to report-only mode", file=sys.stderr)
                # Fall through to return the report path
                return output

            # 2. Collect queries and run baseline
            test_queries = collect_test_queries(3, wiki_dir)
            if not test_queries:
                # Fallback: use candidate queries
                test_queries = [q for q, _ in candidates[:TOP_N_PURIFY]]

            baseline = run_search_baseline(test_queries, wiki_dir)

            # 3. Execute mechanical merges
            if duplicate_groups:
                print(f"  [dream/purify] auto-merging {len(duplicate_groups)} "
                      f"duplicate groups...", file=sys.stderr)
                merged_count, removed_count, modified_paths = _auto_merge_duplicates(
                    duplicate_groups, prior_context, wiki_dir,
                )

            # 4. Post-modification quality assessment
            current = run_search_baseline(test_queries, wiki_dir)
            quality_report = assess_quality(
                test_queries, baseline, current, modified_paths,
            )
            print(f"  [dream/purify] quality score: {quality_report.overall_score:+.3f} "
                  f"→ {quality_report.recommendation}", file=sys.stderr)

            # 5. Decision: keep / warn / rollback
            if quality_report.recommendation == "rollback" and snapshot_hash:
                rollback(wiki_dir, snapshot_hash, "phase3-quality-degraded")
                outcome = "rolled_back"
                # Record rollback experience
                lesson = (
                    f"Phase 3 auto-merge caused quality degradation "
                    f"(score: {quality_report.overall_score:+.3f}). "
                    f"Affected queries: {', '.join(test_queries[:5])}. "
                    f"Review duplicate groups before retrying merge."
                )
                exp = Experience(
                    category="merge",
                    phase=3,
                    context=f"Auto-merged {len(duplicate_groups)} duplicate groups. "
                            f"Rank changes: {quality_report.rank_changes}",
                    outcome="rollback",
                    lesson=lesson,
                )
                exp_recorded = experiences.add(exp)
            elif quality_report.recommendation == "warn":
                outcome = "kept_with_warning"
                lesson = (
                    f"Phase 3 merge completed with minor quality concern "
                    f"(score: {quality_report.overall_score:+.3f}). "
                    f"Monitor search results for affected queries."
                )
                exp = Experience(
                    category="merge",
                    phase=3,
                    context=f"Merged {merged_count} duplicates, removed {removed_count} "
                            f"pages. Modified: {[p.name for p in modified_paths]}",
                    outcome="warning",
                    lesson=lesson,
                )
                exp_recorded = experiences.add(exp)
            elif merged_count > 0:
                outcome = "kept"
                lesson = (
                    f"Phase 3 merge successful (score: {quality_report.overall_score:+.3f}). "
                    f"Merged {merged_count} duplicates, removed {removed_count} pages."
                )
                exp = Experience(
                    category="merge",
                    phase=3,
                    context=f"Merged duplicates from {len(duplicate_groups)} groups",
                    outcome="success",
                    lesson=lesson,
                )
                exp_recorded = experiences.add(exp)

        # Return structured result
        return {
            "report_path": output,
            "merged_count": merged_count,
            "removed_count": removed_count,
            "quality": quality_report.to_dict() if quality_report else None,
            "outcome": outcome,
            "experience_recorded": exp_recorded,
        }

    return output


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Enrich: research tasks for low-density + high-frequency pages
# ══════════════════════════════════════════════════════════════════════════════

def phase_enrich(
    auto: bool = False,
    experiences: ExperienceStore | None = None,
    prior_context: str = "",
) -> Path | dict:
    """Identify low-density pages that are frequently queried, and produce
    Agent deep-research task files.

    When auto=False (default): does NOT auto-execute research — only writes
    task descriptions.

    When auto=True:
    1. Identify enrichment targets (unchanged logic)
    2. Create git snapshot of target pages
    3. Run baseline quality queries
    4. Enrich page metadata (keywords, aliases, questions) mechanically
    5. Run post-modification quality queries
    6. Compute QualityReport → keep/warn/rollback
    7. Record experience if rollback/warning

    Returns Path (report file, auto=False) or dict with results (auto=True).
    """
    _write_status("running", "enrich", "Phase 4/4: Enrich — identifying research targets")
    _check_cancelled()

    # Build page statistics from multi-day logs
    entries = _read_logs(days=AUDIT_WINDOW_DAYS)
    page_stats: dict[str, dict] = {}  # path → {count, sources}
    for entry in entries:
        for src in entry.get("sources", []):
            if not isinstance(src, dict):
                continue
            path = src.get("path", "")
            if not path:
                continue
            if path not in page_stats:
                page_stats[path] = {"count": 0, "name": src.get("name", src.get("id", "?")), "id": src.get("id", "?")}
            page_stats[path]["count"] += 1

    # Filter: frequently queried AND low-density
    candidates: list[dict] = []
    path_density: dict[str, int] = {}
    for path, stats in page_stats.items():
        if stats["count"] < MIN_QUERY_COUNT:
            continue
        p = Path(path)
        if not p.is_file():
            continue
        page = _read_page(p)
        if not page:
            continue
        _, body = page
        density = _page_density(body)
        path_density[path] = density
        if density < LOW_DENSITY_THRESHOLD:
            candidates.append({**stats, "path": path, "density": density})

    candidates.sort(key=lambda c: (-c["count"], c["density"]))
    selected = candidates[:TOP_N_ENRICH]

    output = _dream_dir() / f"{_today()}-enrich.md"
    if not selected:
        output.write_text(
            "# Dream Enrich\n\n✅ No low-density + high-frequency pages found.\n",
            encoding="utf-8",
        )
        return output

    # Write enrichment task for Agent
    task_blocks: list[str] = []
    for i, c in enumerate(selected, start=1):
        task_blocks.append(
            f"### E{i}: [[{c.get('id', '?')}]]\n\n"
            f"- **Page**: {c.get('name', '?')}\n"
            f"- **Queried**: {c['count']}× in {AUDIT_WINDOW_DAYS}d\n"
            f"- **Density**: {c['density']} chars (threshold: {LOW_DENSITY_THRESHOLD})\n"
            f"- **Path**: `{c['path']}`\n"
        )

    output.write_text(
        f"""# Dream Enrich — {_today()}

> **Phase 4/4**: {len(selected)} candidates ({TOP_N_ENRICH} max).

## Agent Task: Deep Research

For each candidate below:
1. Search the web for supplementary information about the topic.
2. Compile findings with `wiki compile` — use `confidence: low` and
   `source: web-research` in frontmatter.
3. Do NOT modify existing pages — write NEW draft pages instead.

{chr(10).join(task_blocks)}

## Constraints

- **Max 10 enrichment targets per dream run** — prioritise by query frequency.
- Mark all web-sourced content with `confidence: 0.5` and `status: draft`.
- If deep-research skill is available, prefer it over raw web search.
""",
        encoding="utf-8",
    )

    _check_cancelled()

    # ── auto-execute path ──────────────────────────────────────────────────
    if auto and experiences is not None and selected:
        wiki_dir = get_wiki_dir()
        modified_paths: list[Path] = []
        enriched_count = 0
        outcome = "no_changes"
        quality_report: QualityReport | None = None
        exp_recorded = False

        # 1. Snapshot before modifications — ABORT if git unavailable
        snapshot_hash = create_snapshot(wiki_dir, "pre-phase4-enrich")
        if not snapshot_hash:
            print("  [dream/enrich] ABORTING auto-enrich: git snapshot unavailable — "
                  "falling back to report-only mode", file=sys.stderr)
            return output

        # 2. Collect queries and run baseline
        test_queries = collect_test_queries(4, wiki_dir)
        if not test_queries:
            test_queries = [
                c.get("name", "") for c in selected if c.get("name")
            ][:10]
        if not test_queries:
            test_queries = [f"what is {c.get('name', '')}" for c in selected[:5]]

        baseline = run_search_baseline(test_queries, wiki_dir)

        # 3. Enrich page metadata mechanically
        enriched_count, modified_paths = _auto_enrich_pages(
            selected, wiki_dir,
        )

        # 4. Post-modification quality assessment
        current = run_search_baseline(test_queries, wiki_dir)
        quality_report = assess_quality(
            test_queries, baseline, current, modified_paths,
        )
        print(f"  [dream/enrich] quality score: {quality_report.overall_score:+.3f} "
              f"→ {quality_report.recommendation}", file=sys.stderr)

        # 5. Decision
        if quality_report.recommendation == "rollback" and snapshot_hash:
            rollback(wiki_dir, snapshot_hash, "phase4-quality-degraded")
            outcome = "rolled_back"
            lesson = (
                f"Phase 4 auto-enrich caused quality degradation "
                f"(score: {quality_report.overall_score:+.3f}). "
                f"Enriched pages: {[p.name for p in modified_paths]}. "
                f"Review enrichment strategy before retrying."
            )
            exp = Experience(
                category="enrich",
                phase=4,
                context=f"Auto-enriched {len(selected)} pages. "
                        f"Rank changes: {quality_report.rank_changes}",
                outcome="rollback",
                lesson=lesson,
            )
            exp_recorded = experiences.add(exp)
        elif quality_report.recommendation == "warn":
            outcome = "kept_with_warning"
            lesson = (
                f"Phase 4 enrichment completed with minor concern "
                f"(score: {quality_report.overall_score:+.3f}). "
                f"Verify enriched pages manually."
            )
            exp = Experience(
                category="enrich",
                phase=4,
                context=f"Enriched {enriched_count} pages. "
                        f"Modified: {[p.name for p in modified_paths]}",
                outcome="warning",
                lesson=lesson,
            )
            exp_recorded = experiences.add(exp)
        elif enriched_count > 0:
            outcome = "kept"
            lesson = (
                f"Phase 4 enrichment successful (score: {quality_report.overall_score:+.3f}). "
                f"Enriched {enriched_count} pages with additional metadata."
            )
            exp = Experience(
                category="enrich",
                phase=4,
                context=f"Enriched {enriched_count} low-density pages",
                outcome="success",
                lesson=lesson,
            )
            exp_recorded = experiences.add(exp)

        return {
            "report_path": output,
            "enriched_count": enriched_count,
            "quality": quality_report.to_dict() if quality_report else None,
            "outcome": outcome,
            "experience_recorded": exp_recorded,
        }

    return output


# ══════════════════════════════════════════════════════════════════════════════
# Auto-execute helpers
# ══════════════════════════════════════════════════════════════════════════════

def _auto_merge_duplicates(
    duplicate_groups: list[dict],
    experiences_context: str,
    wiki_dir: Path,
) -> tuple[int, int, list[Path]]:
    """Mechanically merge duplicate pages. No LLM required.

    For each duplicate pair:
    1. Read both pages
    2. If one is a strict subset of the other, keep the richer one, add redirect
    3. If they have different content, merge non-overlapping sections
    4. Update edges.json to point to the surviving page

    Returns (merged_count, removed_count, modified_paths).
    """
    merged = 0
    removed = 0
    modified: list[Path] = []

    pages_dir = wiki_dir / "pages"
    graph_dir = wiki_dir / "graph"
    edges_file = graph_dir / "edges.json"

    for group in duplicate_groups:
        dups = group.get("duplicates", [])
        if len(dups) < 2:
            continue

        for dup in dups:
            dup_id = dup.get("id", "")
            dup_of_id = dup.get("duplicate_of", "")
            if not dup_id or not dup_of_id:
                continue

            dup_path = _find_page_path(dup_id, pages_dir)
            survivor_path = _find_page_path(dup_of_id, pages_dir)
            if not dup_path or not survivor_path:
                continue

            dup_page = _read_page(dup_path)
            survivor_page = _read_page(survivor_path)
            if not dup_page or not survivor_page:
                continue

            dup_fm, dup_body = dup_page
            surv_fm, surv_body = survivor_page

            # Merge: copy non-overlapping content from duplicate to survivor,
            # preserving original paragraph order
            surv_paragraphs = set(_extract_paragraphs(surv_body))
            new_paragraphs = [
                p for p in _extract_paragraphs(dup_body)
                if p not in surv_paragraphs
            ]

            if new_paragraphs:
                merged_body = surv_body.rstrip() + "\n\n"
                merged_body += "<!-- merged from [[{}]] by dream auto-merge -->\n\n".format(
                    dup_id
                )
                merged_body += "\n\n".join(new_paragraphs)
                _write_page(survivor_path, surv_fm, merged_body)
                modified.append(survivor_path)

            # Add redirect frontmatter to duplicate
            dup_fm["redirect"] = dup_of_id
            dup_fm["status"] = "redirect"
            dup_fm["dream_merged_date"] = _now()
            _write_page(dup_path, dup_fm, dup_body)
            modified.append(dup_path)

            # Update edges: point edges from dup to survivor
            _update_edges_redirect(edges_file, dup_id, dup_of_id)

            merged += 1
            removed += 1

    return merged, removed, modified


def _auto_enrich_pages(
    candidates: list[dict],
    wiki_dir: Path,
) -> tuple[int, list[Path]]:
    """Mechanically enrich page metadata. No LLM required.

    For each candidate page:
    1. Add dream_enrich frontmatter marker
    2. Extract additional keywords from page body
    3. Add basic aliases from page name

    Returns (enriched_count, modified_paths).
    """
    enriched = 0
    modified: list[Path] = []

    for candidate in candidates:
        path_str = candidate.get("path", "")
        if not path_str:
            continue

        path = Path(path_str)
        if not path.is_file():
            continue

        page = _read_page(path)
        if not page:
            continue

        frontmatter, body = page

        # Mark as enriched
        frontmatter["dream_enrich"] = True
        frontmatter["dream_enrich_date"] = _now()

        # Extract keywords from body
        existing_keywords = set(
            _as_list(frontmatter.get("keywords", []))
        )
        body_terms = _extract_key_terms(body)
        new_keywords = body_terms - existing_keywords
        if new_keywords:
            all_keywords = list(existing_keywords) + list(new_keywords)
            frontmatter["keywords"] = all_keywords[:24]

        # Add alias from page name if not present
        name = candidate.get("name", "")
        aliases = set(_as_list(frontmatter.get("aliases", [])))
        if name and name not in aliases:
            aliases.add(name)
            frontmatter["aliases"] = sorted(aliases)

        _write_page(path, frontmatter, body)
        modified.append(path)
        enriched += 1

    return enriched, modified


def _find_page_path(page_id: str, pages_dir: Path) -> Path | None:
    """Locate a page file by its ID in the pages directory tree."""
    for subdir_name in ("concepts", "entities", "models", "techniques",
                         "frameworks", "benchmarks", "papers", "decisions",
                         "sessions", "patterns"):
        subdir = pages_dir / subdir_name
        if not subdir.is_dir():
            continue
        for f in subdir.iterdir():
            if f.suffix != ".md":
                continue
            if f.stem == page_id or f.name == f"{page_id}.md":
                return f
    return None


def _extract_paragraphs(body: str) -> list[str]:
    """Split body into non-empty paragraphs."""
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def _extract_key_terms(body: str) -> set[str]:
    """Extract key terms from page body for keywords."""
    import re as _re
    cn_terms = set(_re.findall(r"[一-鿿]{2,8}", body))
    en_terms = set(
        w.lower() for w in _re.findall(r"[a-zA-Z]{3,}", body)
        if len(w) >= 4
    )
    return cn_terms | en_terms


def _as_list(value) -> list:
    """Normalise a value to a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _update_edges_redirect(
    edges_file: Path, from_id: str, to_id: str,
) -> None:
    """Update edges.json: replace references to from_id with to_id."""
    if not edges_file.is_file():
        return
    try:
        edges_data = json.loads(edges_file.read_text(encoding="utf-8"))
        edges = (
            edges_data.get("edges", edges_data)
            if isinstance(edges_data, dict)
            else edges_data
        )
        if not isinstance(edges, list):
            return

        changed = False
        for edge in edges:
            if edge.get("source") == from_id:
                edge["source"] = to_id
                changed = True
            if edge.get("target") == from_id:
                edge["target"] = to_id
                changed = True

        if changed:
            edges_file.write_text(
                json.dumps(edges_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except (OSError, json.JSONDecodeError):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════════

def run_worker(auto: bool = False) -> str:
    """Execute all four dream phases in sequence.  Cancellable at any boundary.

    Args:
        auto: If True, phases 3 & 4 auto-execute modifications with quality
              gating (snapshot → modify → assess → keep/rollback).
              If False (default), phases 3 & 4 generate reports for human review.
    """
    directory = _dream_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _cancel_path().unlink(missing_ok=True)
    _write_status("running", "start", "Dream worker started")

    wiki_dir = get_wiki_dir()
    experiences: ExperienceStore | None = None
    ctx_phase3 = ""
    ctx_phase4 = ""

    if auto:
        # Initialise git repo for snapshot safety
        ensure_git_repo(wiki_dir)
        # Load prior experiences for context
        experiences = ExperienceStore(wiki_dir)
        ctx_phase3 = experiences.to_context(3)
        ctx_phase4 = experiences.to_context(4)
        if ctx_phase3:
            print(f"  [dream] loaded {len(experiences.load_for_phase(3))} prior experiences for phase 3",
                  file=sys.stderr)
        if ctx_phase4:
            print(f"  [dream] loaded {len(experiences.load_for_phase(4))} prior experiences for phase 4",
                  file=sys.stderr)

    try:
        # Phase 1 — safe metadata updates (always auto)
        light = phase_light_sleep()
        _check_cancelled()

        # Phase 2 — query analysis (report only)
        audit = phase_audit(light)
        _check_cancelled()

        # Phase 3 — search simulation + content analysis
        if auto:
            purify = phase_purify(
                auto=True,
                experiences=experiences,
                prior_context=ctx_phase3,
            )
        else:
            purify = phase_purify()
        _check_cancelled()

        # Phase 4 — enrichment research tasks
        if auto:
            enrich = phase_enrich(
                auto=True,
                experiences=experiences,
                prior_context=ctx_phase4,
            )
        else:
            enrich = phase_enrich()

    except DreamCancelled:
        return "Dream cancelled"
    except RuntimeError:
        raise
    except Exception as exc:
        _write_status("failed", "failed", str(exc))
        raise

    _check_cancelled()

    def _phase_path(result: Path | dict | object) -> Path:
        """Extract report path from a phase result (Path, dict, or other)."""
        if isinstance(result, Path):
            return result
        if isinstance(result, dict) and "report_path" in result:
            rp = result["report_path"]
            return rp if isinstance(rp, Path) else Path(str(rp))
        return Path(".")

    _write_status(
        "complete",
        "done",
        f"Dream complete: {len(light)} query themes; "
        f"audit={audit.name}; purify={_phase_path(purify).name}; "
        f"enrich={_phase_path(enrich).name}",
    )
    return "Dream complete"


def start_dream(foreground: bool = False, worker: bool = False,
                auto: bool = False) -> str:
    """Entry point — run in foreground (blocking) or background (detached).

    Args:
        foreground: Run synchronously in this process.
        worker: Internal flag for subprocess invocation.
        auto: If True, phases 3 & 4 auto-execute with quality gating
              (snapshot → modify → assess → keep/rollback).
    """
    if foreground or worker:
        return run_worker(auto=auto)

    directory = _dream_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _cancel_path().unlink(missing_ok=True)
    stdout = open(directory / "dream.out.log", "a", encoding="utf-8")
    stderr = open(directory / "dream.err.log", "a", encoding="utf-8")
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    if auto:
        cmd.append("--auto")
    try:
        child = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    finally:
        stdout.close()
        stderr.close()
    return f"Dream started in background (pid {child.pid}). Status: {_status_path()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run query-driven dream consolidation")
    parser.add_argument(
        "--foreground", action="store_true",
        help="Run the dream worker in this process",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Auto-execute phases 3 & 4 with quality gating (no human confirmation)",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(start_dream(foreground=args.foreground, worker=args.worker,
                      auto=args.auto))


if __name__ == "__main__":
    main()
