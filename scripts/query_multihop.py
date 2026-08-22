"""Evidence-driven multi-hop planning and coverage-aware result selection.

The module is retrieval-engine agnostic. Callers inject the official search and
page-reading functions, so every hop still goes through llm-wiki's access,
lifecycle, ranking, graph, and ledger controls.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

SearchFunction = Callable[[str, int], list[dict[str, Any]]]
ReadFunction = Callable[[str], str]

MAX_SUBGOALS = 5
DEFAULT_COVERAGE_THRESHOLD = 0.40

_QUESTION_WORDS = (
    "分别说明",
    "分别解释",
    "请说明",
    "请解释",
    "有什么",
    "为什么",
    "怎么样",
    "是什么",
    "如何",
    "怎么",
    "哪些",
    "哪个",
    "是否",
    "列出",
    "说明",
    "解释",
    "介绍",
    "请问",
    "首先",
    "然后",
    "最后",
    "以及",
    "并且",
    "同时",
)
_STOP_TERMS = {
    "什么",
    "如何",
    "怎么",
    "哪些",
    "哪个",
    "说明",
    "解释",
    "介绍",
    "列出",
    "请问",
    "以及",
    "然后",
    "并且",
    "同时",
    "之间",
    "相关",
    "是否",
    "可以",
    "能够",
    "the",
    "and",
    "what",
    "how",
    "why",
    "which",
    "with",
    "from",
}
_RELATION_MARKERS = (
    "考查",
    "先修",
    "前置",
    "依赖",
    "导致",
    "影响",
    "关系",
    "关联",
    "例题",
    "应用于",
    "易混",
    "推导",
    "requires",
    "depends",
    "causes",
    "tests",
    "example",
    "related",
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.casefold())


def query_terms(text: str) -> set[str]:
    """Extract stable lexical evidence terms for Chinese and English queries."""
    cleaned = text.casefold()
    for word in _QUESTION_WORDS:
        cleaned = cleaned.replace(word, " ")

    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_.-]+", cleaned)
        if len(token) >= 2 and token not in _STOP_TERMS
    }
    for sequence in re.findall(r"[\u4e00-\u9fff]+", cleaned):
        if len(sequence) < 2 or sequence in _STOP_TERMS:
            continue
        if len(sequence) <= 8:
            terms.add(sequence)
        terms.update(
            sequence[index : index + 2]
            for index in range(len(sequence) - 1)
            if sequence[index : index + 2] not in _STOP_TERMS
        )
    return terms


def evidence_support_score(goal: str, content: str) -> float:
    """Estimate how completely one document supports a retrieval subgoal."""
    if not content:
        return 0.0
    goal_variants = [goal]
    try:
        try:
            from query_language import cross_language_variants
        except ImportError:
            from .query_language import cross_language_variants

        goal_variants.extend(
            cross_language_variants(
                goal,
                "/__llm_wiki_builtin_glossary_only__",
                "/__llm_wiki_no_custom_glossary__",
            )
        )
    except (ImportError, OSError, TypeError, ValueError):
        pass
    normalized_content = _normalize(content)
    scores: list[float] = []
    for variant in goal_variants:
        terms = query_terms(variant)
        weighted_total = sum(min(len(term), 6) for term in terms)
        matched = sum(min(len(term), 6) for term in terms if _normalize(term) in normalized_content)
        if weighted_total:
            scores.append(matched / weighted_total)
    return round(max(scores, default=0.0), 4)


def _page_evidence_text(page: dict[str, Any], read_content: ReadFunction) -> str:
    """Read evidence uniformly from OKF pages and structured ledger rows."""
    path = str(page.get("path", ""))
    if path and not path.startswith("table://"):
        return read_content(path)
    row_data = page.get("row_data", {})
    if isinstance(row_data, dict) and row_data:
        return "\n".join(
            f"{key}: {value}" for key, value in row_data.items() if not str(key).startswith("_")
        )
    return str(page.get("text", ""))


def decompose_query(query: str) -> list[str]:
    """Create at most five deterministic subqueries for a compound question."""
    original = query.strip()
    if not original:
        return []
    candidates = [original]
    stripped = re.sub(r"[?？。.!！]+$", "", original).strip()
    clauses = re.split(
        r"(?:；|;|，并且|，然后|，同时|,\s*and\s+|\band then\b|以及|并且|然后|同时)",
        stripped,
        flags=re.IGNORECASE,
    )
    if len(clauses) > 1:
        candidates.extend(clause.strip(" ，,") for clause in clauses if len(clause.strip()) >= 3)

    comparison = re.search(
        r"(.+?)(?:和|与|及|versus|vs\.?)(.+?)(?:的)?(?:区别|差异|关系|比较|对比)",
        stripped,
        flags=re.IGNORECASE,
    )
    if comparison:
        for part in comparison.groups():
            cleaned_part = re.sub(
                r"(?:有什么|是什么|如何|how|what)$",
                "",
                part.strip(" ，,"),
                flags=re.IGNORECASE,
            ).strip()
            if cleaned_part:
                candidates.append(cleaned_part)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            deduped.append(normalized)
    return deduped[:MAX_SUBGOALS]


def atomic_subgoals(query: str) -> list[str]:
    """Return answer slots, excluding a redundant compound parent query."""
    decomposed = decompose_query(query)
    return decomposed[1:] if len(decomposed) > 1 else decomposed


def retrieval_evidence_status(
    query: str,
    pages: list[dict[str, Any]],
    read_content: ReadFunction,
    threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> dict[str, Any]:
    """Report which answer subgoals have direct support in retrieved pages."""
    goals = atomic_subgoals(query)
    support: list[dict[str, Any]] = []
    for index, goal in enumerate(goals):
        best_score = 0.0
        best_page = ""
        for page in pages:
            content = _page_evidence_text(page, read_content)
            score = evidence_support_score(goal, content)
            if score > best_score:
                best_score = score
                best_page = str(page.get("id", ""))
        support.append(
            {
                "id": index,
                "subgoal": goal,
                "score": round(best_score, 4),
                "supported_by": best_page,
                "satisfied": best_score >= threshold,
            }
        )
    missing = [item["subgoal"] for item in support if not item["satisfied"]]
    coverage = sum(1 for item in support if item["satisfied"]) / len(support) if support else 1.0
    return {
        "status": "complete" if not missing else "incomplete",
        "coverage": round(coverage, 4),
        "threshold": threshold,
        "subgoals": support,
        "missing_subgoals": missing,
    }


def _linked_followup_candidates(
    pages: list[dict[str, Any]],
    attempted: set[str],
    read_content: ReadFunction,
    goals: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        path = str(page.get("path", ""))
        if not path or path.startswith("table://"):
            continue
        content = read_content(path)
        for line in content.splitlines():
            links: list[tuple[str, str]] = []
            links.extend(
                (label.strip(), target.strip("/"))
                for label, target in re.findall(
                    r"\[([^\]]+)\]\((?:/)?([^)#]+?)\.md(?:#[^)]+)?\)", line
                )
            )
            links.extend(
                (target.strip(), target.strip())
                for target in re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", line)
            )
            for label, target_id in links:
                query_text = label or Path(target_id).name.replace("-", " ")
                if (
                    target_id == page.get("id")
                    or len(query_text) < 2
                    or query_text.casefold() in attempted
                ):
                    continue
                goal_scores = [
                    evidence_support_score(goal, f"{query_text} {line}") for goal in goals
                ]
                relevance = max(goal_scores, default=0.0)
                relation_bonus = (
                    0.18 if any(marker in line.casefold() for marker in _RELATION_MARKERS) else 0.0
                )
                candidates.append(
                    {
                        "query": query_text,
                        "target": target_id,
                        "parent": str(page.get("id", "")),
                        "parent_score": float(page.get("retrieval_path_score", 1.0)),
                        "relevance": round(relevance + relation_bonus, 4),
                    }
                )

    best_by_query: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = candidate["query"].casefold()
        previous = best_by_query.get(key)
        if previous is None or candidate["relevance"] > previous["relevance"]:
            best_by_query[key] = candidate
    return sorted(
        best_by_query.values(),
        key=lambda item: (item["relevance"], item["parent_score"]),
        reverse=True,
    )[:limit]


def linked_followup_queries(
    pages: list[dict[str, Any]],
    attempted: set[str],
    read_content: ReadFunction,
    limit: int = 5,
) -> list[str]:
    """Compatibility API returning ranked unresolved linked concepts."""
    return [
        item["query"]
        for item in _linked_followup_candidates(
            pages, attempted, read_content, goals=[], limit=limit
        )
    ]


def coverage_diverse_rank(
    query: str,
    candidates: list[dict[str, Any]],
    read_content: ReadFunction,
    limit: int,
) -> list[dict[str, Any]]:
    """Greedily retain relevant pages that add new answer-slot coverage."""
    if not candidates:
        return []
    goals = atomic_subgoals(query)
    annotated: list[dict[str, Any]] = []
    for rank, candidate in enumerate(candidates):
        item = dict(candidate)
        content = _page_evidence_text(item, read_content)
        goal_scores = [evidence_support_score(goal, content) for goal in goals]
        item["evidence_goal_scores"] = goal_scores
        item["evidence_goals"] = [
            index for index, score in enumerate(goal_scores) if score >= DEFAULT_COVERAGE_THRESHOLD
        ]
        item["_base_rank_score"] = 1.0 - rank / max(len(candidates), 1)
        annotated.append(item)

    selected: list[dict[str, Any]] = []
    covered: set[int] = set()
    remaining = annotated[:]
    strongest_score = max(
        (
            float(
                item.get(
                    "multi_hop_score",
                    item.get("rerank_score", item.get("score", 0)),
                )
                or 0
            )
            for item in remaining
        ),
        default=0.0,
    )
    while remaining and len(selected) < limit:

        def utility(item: dict[str, Any]) -> float:
            goal_set = set(item["evidence_goals"])
            new_goals = goal_set - covered
            duplicate_goals = goal_set & covered
            retrieval_score = float(
                item.get(
                    "multi_hop_score",
                    item.get("rerank_score", item.get("score", 0)),
                )
                or 0
            )
            return (
                0.55 * item["_base_rank_score"]
                + 0.25 * min(retrieval_score, 1.0)
                + 0.45 * (len(new_goals) / max(len(goals), 1))
                - 0.18 * (len(duplicate_goals) / max(len(goals), 1))
            )

        winner = max(remaining, key=utility)
        winner_score = float(
            winner.get(
                "multi_hop_score",
                winner.get("rerank_score", winner.get("score", 0)),
            )
            or 0
        )
        all_goals_covered = bool(goals) and len(covered) == len(goals)
        if (
            len(selected) >= min(limit, 2)
            and all_goals_covered
            and (not winner["evidence_goals"] or winner_score < strongest_score * 0.78)
        ):
            break
        winner["coverage_gain"] = sorted(set(winner["evidence_goals"]) - covered)
        covered.update(winner["evidence_goals"])
        winner.pop("_base_rank_score", None)
        selected.append(winner)
        remaining.remove(winner)
    return selected


def run_multi_hop(
    query: str,
    search: SearchFunction,
    read_content: ReadFunction,
    limit: int = 5,
    max_hops: int = 3,
    debug: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
    """Search until answer subgoals are covered or no useful frontier remains."""
    max_hops = max(1, min(int(max_hops), 5))
    goals = atomic_subgoals(query)
    frontier = [
        {"query": subquery, "parent_score": 1.0, "parent": ""}
        for subquery in decompose_query(query)
    ]
    attempted: set[str] = set()
    accumulated: dict[str, dict[str, Any]] = {}
    hop_trace: list[dict[str, Any]] = []
    stop_reason = "max_hops_reached"

    for hop in range(1, max_hops + 1):
        hop_pages: list[dict[str, Any]] = []
        hop_queries: list[str] = []
        for frontier_item in frontier:
            subquery = str(frontier_item["query"])
            key = subquery.casefold()
            if key in attempted:
                continue
            attempted.add(key)
            hop_queries.append(subquery)
            batch = search(subquery, max(limit, 5))
            raw_scores = [float(item.get("score", 0) or 0) for item in batch]
            high = max(raw_scores, default=1.0)
            low = min(raw_scores, default=0.0)
            for rank, result in enumerate(batch, 1):
                item = dict(result)
                raw_score = float(item.get("score", 0) or 0)
                raw_normalized = (raw_score - low) / (high - low) if high > low else 1.0 / rank
                rank_score = 1.0 / (1.0 + 0.20 * (rank - 1))
                search_score = 0.65 * rank_score + 0.35 * raw_normalized
                path_score = float(frontier_item.get("parent_score", 1.0)) * (0.82 ** (hop - 1))
                content = _page_evidence_text(item, read_content)
                goal_scores = [evidence_support_score(goal, content) for goal in goals]
                coverage_score = max(goal_scores, default=0.0)
                combined = 0.55 * search_score + 0.30 * coverage_score + 0.15 * path_score
                item["single_hop_score"] = raw_score
                item["score"] = round(combined, 4)
                item["multi_hop_score"] = round(combined, 4)
                item["retrieval_hop"] = hop
                item["retrieval_path_score"] = round(path_score, 4)
                item["retrieval_queries"] = [subquery]
                item["retrieval_parent"] = str(frontier_item.get("parent", ""))
                item["evidence_goal_scores"] = goal_scores
                item["evidence_goals"] = [
                    index
                    for index, score in enumerate(goal_scores)
                    if score >= DEFAULT_COVERAGE_THRESHOLD
                ]
                identity = str(item.get("path") or item.get("id"))
                existing = accumulated.get(identity)
                if existing is None:
                    accumulated[identity] = item
                    hop_pages.append(item)
                else:
                    if combined > float(existing.get("multi_hop_score", 0)):
                        preserved_queries = existing.get("retrieval_queries", [])
                        accumulated[identity] = item
                        existing = item
                        existing["retrieval_queries"] = preserved_queries
                    for evidence_query in item["retrieval_queries"]:
                        if evidence_query not in existing["retrieval_queries"]:
                            existing["retrieval_queries"].append(evidence_query)

        evidence = retrieval_evidence_status(query, list(accumulated.values()), read_content)
        hop_trace.append(
            {
                "hop": hop,
                "queries": hop_queries,
                "new_pages": [page.get("id", "") for page in hop_pages],
                "coverage": evidence["coverage"],
                "missing_subgoals": evidence["missing_subgoals"],
            }
        )
        if evidence["status"] == "complete":
            stop_reason = "evidence_complete"
            break
        if not hop_pages:
            stop_reason = "no_new_pages"
            break

        followups = _linked_followup_candidates(
            hop_pages,
            attempted,
            read_content,
            goals=evidence["missing_subgoals"],
            limit=max(limit, 5),
        )
        frontier = [
            {
                "query": item["query"],
                "parent_score": max(0.25, float(item["relevance"])),
                "parent": item["parent"],
            }
            for item in followups
        ]
        if not frontier:
            stop_reason = "no_relevant_frontier"
            break

    candidates = sorted(
        accumulated.values(),
        key=lambda item: (
            float(item.get("multi_hop_score", 0)),
            -int(item.get("retrieval_hop", 1)),
        ),
        reverse=True,
    )
    ranked = coverage_diverse_rank(query, candidates, read_content, limit)
    final_evidence = retrieval_evidence_status(query, ranked, read_content)
    trace = {
        "strategy": "multi_hop",
        "query": query,
        "max_hops": max_hops,
        "hops": hop_trace,
        "attempted_queries": sorted(attempted),
        "result_count": len(ranked),
        "stop_reason": stop_reason,
        "evidence": final_evidence,
    }
    return (ranked, trace) if debug else ranked
