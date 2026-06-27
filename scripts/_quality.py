#!/usr/bin/env python3
"""Search quality assessment for dream self-looping.

After dream modifies wiki pages, this module re-runs search queries and
compares the before/after results to decide whether quality improved,
stayed the same, or degraded (triggering a rollback).

Metrics (3-dimension weighted):
- rank_preservation  (0.40) — did target pages maintain/improve search rank?
- density_improvement (0.30) — did page content become richer?
- coverage_score     (0.30) — are all expected pages still findable?

Decision thresholds:
    score >= 0          → keep
    -0.15 <= score < 0  → keep with warning
    score < -0.15       → rollback + record experience
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── constants ────────────────────────────────────────────────────────────────

LOW_DENSITY_THRESHOLD = 1200  # chars (excluding whitespace)

RANK_PRESERVATION_WEIGHT = 0.40
DENSITY_IMPROVEMENT_WEIGHT = 0.30
COVERAGE_SCORE_WEIGHT = 0.30

ROLLBACK_THRESHOLD = -0.15


# ── data types ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QualityReport:
    """Result of a before/after search quality comparison."""

    overall_score: float  # [-1, 1], negative = degraded
    per_query_scores: dict[str, float] = field(default_factory=dict)
    density_changes: dict[str, int] = field(default_factory=dict)
    rank_changes: dict[str, dict] = field(default_factory=dict)
    recommendation: str = "keep"  # "keep" | "warn" | "rollback"
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "per_query_scores": self.per_query_scores,
            "density_changes": self.density_changes,
            "rank_changes": self.rank_changes,
            "recommendation": self.recommendation,
            "summary": self.summary,
        }


# ── helpers ───────────────────────────────────────────────────────────────────

def _page_density(body: str) -> int:
    """Count non-whitespace characters (moved from dream.py)."""
    return len(re.sub(r"\s+", "", body))


def _read_page_parts(path: Path) -> tuple[dict, str] | None:
    """Return (frontmatter_dict, body_text) or None."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        import yaml
        fm = yaml.safe_load(match.group(1)) or {}
        return (fm if isinstance(fm, dict) else {}, match.group(2))
    except Exception:
        return ({}, match.group(2))


def _extract_page_ids(results: list[dict]) -> set[str]:
    """Extract unique page IDs from search results."""
    ids: set[str] = set()
    for r in results:
        rid = r.get("id", "")
        if rid:
            ids.add(rid)
    return ids


def _find_rank(results: list[dict], page_id: str) -> int:
    """Return 1-based rank of *page_id* in results, or -1 if not found."""
    for i, r in enumerate(results):
        if r.get("id") == page_id:
            return i + 1
    return -1


# ── quality assessment ───────────────────────────────────────────────────────

def _compute_rank_score(
    test_queries: list[str],
    baseline_results: dict[str, list[dict]],
    current_results: dict[str, list[dict]],
) -> tuple[float, dict[str, dict], dict[str, float]]:
    """Compute rank preservation score and per-query details."""
    rank_deltas: list[float] = []
    rank_changes: dict[str, dict] = {}
    per_query_rank_scores: dict[str, float] = {}

    for query in test_queries:
        baseline = baseline_results.get(query, [])
        current = current_results.get(query, [])
        query_changes: dict[str, tuple[int, int]] = {}
        query_deltas: list[float] = []

        for pid in _extract_page_ids(baseline):
            old_rank = _find_rank(baseline, pid)
            new_rank = _find_rank(current, pid)
            if old_rank > 0 and new_rank > 0:
                delta = 1.0 if new_rank < old_rank else (-1.0 if new_rank > old_rank else 0.0)
            elif old_rank > 0 and new_rank < 0:
                delta = -1.0
            elif old_rank < 0 and new_rank > 0:
                delta = 0.5
            else:
                continue
            rank_deltas.append(delta)
            query_deltas.append(delta)
            query_changes[pid] = (old_rank, new_rank)

        if query_changes:
            rank_changes[query] = {
                k: {"old": v[0], "new": v[1]} for k, v in query_changes.items()
            }
        per_query_rank_scores[query] = (
            round(sum(query_deltas) / len(query_deltas), 3) if query_deltas else 0.0
        )

    avg_rank_delta = sum(rank_deltas) / len(rank_deltas) if rank_deltas else 0.0
    rank_score = max(-1.0, min(1.0, avg_rank_delta))
    return rank_score, rank_changes, per_query_rank_scores


def _compute_density_score(modified_paths: list[Path]) -> tuple[float, dict[str, int]]:
    """Compute density improvement score for modified pages."""
    density_changes: dict[str, int] = {}
    density_deltas: list[float] = []

    for path in modified_paths:
        if not path.is_file():
            continue
        page = _read_page_parts(path)
        if not page:
            continue
        _, body = page
        density = _page_density(body)
        density_changes[str(path)] = density
        if density >= LOW_DENSITY_THRESHOLD:
            density_deltas.append(0.5)
        elif density > 0:
            ratio = density / LOW_DENSITY_THRESHOLD
            density_deltas.append(max(-0.5, ratio - 0.5))
        else:
            density_deltas.append(-0.5)

    avg = sum(density_deltas) / len(density_deltas) if density_deltas else 0.0
    return max(-1.0, min(1.0, avg)), density_changes


def _compute_coverage_score(
    test_queries: list[str],
    baseline_results: dict[str, list[dict]],
    current_results: dict[str, list[dict]],
) -> float:
    """Compute coverage score — are baseline pages still findable?"""
    all_baseline_ids: set[str] = set()
    all_current_ids: set[str] = set()
    for query in test_queries:
        all_baseline_ids |= _extract_page_ids(baseline_results.get(query, []))
        all_current_ids |= _extract_page_ids(current_results.get(query, []))
    if all_baseline_ids:
        still_findable = all_baseline_ids & all_current_ids
        coverage = len(still_findable) / len(all_baseline_ids)
    else:
        coverage = 1.0
    return (coverage * 2.0) - 1.0  # map [0,1] → [-1,1]


def _make_recommendation(overall: float) -> tuple[str, str]:
    """Translate composite score to a recommendation and summary."""
    if overall >= 0:
        return "keep", f"Quality stable or improved (score: {overall:+.2f})."
    elif overall >= ROLLBACK_THRESHOLD:
        return "warn", (
            f"Minor quality degradation (score: {overall:+.2f}). "
            f"Changes kept; review recommended."
        )
    return "rollback", (
        f"Significant quality degradation (score: {overall:+.2f}). "
        f"Rolling back to pre-modification state."
    )


def assess_quality(
    test_queries: list[str],
    baseline_results: dict[str, list[dict]],
    current_results: dict[str, list[dict]],
    modified_paths: list[Path],
) -> QualityReport:
    """Compare before/after search results and produce a QualityReport."""
    if not test_queries:
        return QualityReport(
            overall_score=0, recommendation="keep",
            summary="No test queries — skipping quality assessment.",
        )

    rank_score, rank_changes, per_query_scores = _compute_rank_score(
        test_queries, baseline_results, current_results,
    )
    density_score, density_changes = _compute_density_score(modified_paths)
    coverage_score = _compute_coverage_score(
        test_queries, baseline_results, current_results,
    )

    overall = (
        RANK_PRESERVATION_WEIGHT * rank_score
        + DENSITY_IMPROVEMENT_WEIGHT * density_score
        + COVERAGE_SCORE_WEIGHT * coverage_score
    )

    recommendation, summary = _make_recommendation(overall)
    return QualityReport(
        overall_score=round(overall, 3),
        per_query_scores=per_query_scores,
        density_changes=density_changes,
        rank_changes=rank_changes,
        recommendation=recommendation,
        summary=summary,
    )


# ── search baseline ───────────────────────────────────────────────────────────

def run_search_baseline(queries: list[str], wiki_dir: Path) -> dict[str, list[dict]]:
    """Run wiki search for each query and return raw results.

    Uses bm25 + metadata + graph streams (no LLM synthesis) for speed.
    Returns: {query: [search_result_dict, ...]}
    """
    results: dict[str, list[dict]] = {}

    try:
        from search import (
            bm25_search,
            metadata_search,
            graph_search,
            reciprocal_rank_fusion,
        )
        pages_dir = str(wiki_dir / "pages")
        graph_dir = str(wiki_dir / "graph")

        for query in queries:
            try:
                bm25 = bm25_search(query, pages_dir, limit=10)
                meta = metadata_search(query, pages_dir, limit=10)
                graph = graph_search(query, graph_dir, limit=10)
                fused = reciprocal_rank_fusion([bm25, meta, graph], k=60)
                results[query] = fused[:10]
            except Exception as exc:
                print(
                    f"  [dream/quality] search failed for '{query[:60]}': {exc}",
                    file=sys.stderr,
                )
                results[query] = []
    except ImportError:
        try:
            from query import query_wiki
            for query in queries:
                try:
                    result = query_wiki(query, synthesis=False, mode="agent")
                    sources = result.get("source_details", []) if result else []
                    results[query] = sources[:10]
                except Exception:
                    results[query] = []
        except Exception:
            print(
                "  [dream/quality] cannot import search modules; "
                "quality assessment disabled",
                file=sys.stderr,
            )

    return results


def collect_test_queries(phase: int, wiki_dir: Path) -> list[str]:
    """Collect queries for quality assessment.

    Phase 3: top recurring queries from recent audit logs.
    Phase 4: queries associated with enriched pages.
    """
    audit_dir = wiki_dir / "audit"
    if not audit_dir.is_dir():
        return []

    from datetime import datetime, timedelta, timezone

    queries: dict[str, int] = {}
    for offset in range(7):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).strftime(
            "%Y%m%d"
        )
        log_path = audit_dir / f"query-log-{day}.jsonl"
        if not log_path.is_file():
            continue
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                q = str(entry.get("question", "")).strip()
                if len(q) >= 2:
                    queries[q] = queries.get(q, 0) + 1
            except json.JSONDecodeError:
                continue

    ranked = sorted(queries.items(), key=lambda kv: -kv[1])
    return [q for q, c in ranked if c >= 2][:10]
