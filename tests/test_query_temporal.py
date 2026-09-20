"""Regression coverage for effective-time policy retrieval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.compile_v2 as compile_v2
import scripts.query as query
from scripts.query_temporal import query_time_context, rank_temporal_results


def _policy(path: Path, frontmatter: str, body: str = "Policy body") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter.strip()}\n---\n# Policy\n\n{body}\n", encoding="utf-8")
    return path


def test_query_time_context_detects_current_and_explicit_chinese_date():
    now = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)

    current = query_time_context("当前执行什么政策？", now=now)
    historical = query_time_context("2025年3月1日执行什么政策？", now=now)

    assert current["mode"] == "current"
    assert current["as_of"] == now
    assert historical["mode"] == "as_of"
    assert historical["as_of"] == datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert query.plan_query("截至2025-03-01适用什么规则")["intent"] == "temporal_as_of"


def test_future_replacement_does_not_invalidate_old_rule_early(tmp_path: Path):
    old = _policy(
        tmp_path / "policies" / "old.md",
        """
type: Policy
title: Old rule
effective_from: 2025-01-01
superseded_by: [/policies/new.md]
""",
    )
    new = _policy(
        tmp_path / "policies" / "new.md",
        """
type: Policy
title: New rule
effective_from: 2026-10-01
supersedes: [/policies/old.md]
""",
    )
    results = [
        {"id": "policies/new", "path": str(new), "score": 10.0},
        {"id": "policies/old", "path": str(old), "score": 1.0},
    ]
    context = query_time_context(
        "当前执行什么政策？",
        now=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )

    ranked = rank_temporal_results(results, context, limit=5)

    assert [item["id"] for item in ranked] == ["policies/old", "policies/new"]
    assert ranked[0]["temporal"]["state"] == "active"
    assert ranked[0]["temporal"]["effective_until"] == "2026-10-01T00:00:00Z"
    assert ranked[0]["temporal"]["effective_until_inferred"] is True
    assert ranked[1]["temporal"]["state"] == "scheduled"


def test_replacement_becomes_active_on_effective_date(tmp_path: Path):
    old = _policy(
        tmp_path / "policies" / "old.md",
        """
type: Policy
effective_from: 2025-01-01
superseded_by: [/policies/new.md]
""",
    )
    new = _policy(
        tmp_path / "policies" / "new.md",
        """
type: Policy
effective_from: 2026-10-01
supersedes: [/policies/old.md]
""",
    )
    results = [
        {"id": "policies/old", "path": str(old), "score": 10.0},
        {"id": "policies/new", "path": str(new), "score": 1.0},
    ]
    context = query_time_context(
        "2026年10月1日执行什么政策？",
        now=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )

    ranked = rank_temporal_results(results, context, limit=5)

    assert [item["id"] for item in ranked] == ["policies/new", "policies/old"]
    assert ranked[0]["temporal"]["state"] == "active"
    assert ranked[1]["temporal"]["state"] == "expired"


def test_date_only_boundary_uses_query_timezone(tmp_path: Path):
    page = _policy(
        tmp_path / "policy.md",
        "type: Policy\neffective_from: 2026-10-01",
    )
    china_time = timezone(timedelta(hours=8))
    context = query_time_context(
        "当前政策是什么？",
        now=datetime(2026, 10, 1, 0, 30, tzinfo=china_time),
    )

    ranked = rank_temporal_results(
        [{"id": "policy", "path": str(page), "score": 1.0}],
        context,
        limit=1,
    )

    assert ranked[0]["temporal"]["state"] == "active"
    assert ranked[0]["temporal"]["effective_from"] == "2026-09-30T16:00:00Z"


def test_timestamp_and_stale_after_are_not_effective_dates(tmp_path: Path):
    page = _policy(
        tmp_path / "policy.md",
        """
type: Policy
timestamp: 2026-01-01T00:00:00Z
stale_after: 2026-02-01T00:00:00Z
status: deprecated
""",
    )
    context = query_time_context(
        "当前政策是什么？",
        now=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )

    ranked = rank_temporal_results(
        [{"id": "policy", "path": str(page), "score": 1.0}],
        context,
        limit=1,
    )

    assert ranked[0]["temporal"]["state"] == "undated"
    assert ranked[0]["temporal"]["date_basis"] == "unknown"


def test_query_widens_current_retrieval_then_returns_active_rule_first(tmp_path: Path, monkeypatch):
    old = _policy(
        tmp_path / "old.md",
        """
type: Policy
title: Current rule
effective_from: 2000-01-01
superseded_by: [/new.md]
""",
        "The current limit is 10.",
    )
    new = _policy(
        tmp_path / "new.md",
        """
type: Policy
title: Future rule
effective_from: 2099-01-01
supersedes: [/old.md]
""",
        "The future limit is 20.",
    )
    observed: dict[str, int] = {}

    def fake_search(_text: str, limit: int = 5, **_kwargs):
        observed["limit"] = limit
        return [
            {"id": "new", "path": str(new), "type": "policy", "score": 9.0},
            {"id": "old", "path": str(old), "type": "policy", "score": 1.0},
        ]

    monkeypatch.setattr(
        query,
        "get_query_config",
        lambda: {
            "max_results": 2,
            "multi_hop_enabled": False,
            "multi_hop_max_hops": 3,
            "verify_answers": False,
        },
    )
    monkeypatch.setattr(query, "search_wiki", fake_search)

    result = query.query_wiki("当前政策是什么？", synthesis=False)

    assert observed["limit"] == 6
    assert result["sources"] == ["old", "new"]
    assert "`active`" in result["answer"]
    assert "`scheduled`" in result["answer"]
    assert result["temporal_context"]["mode"] == "current"
    assert result["source_details"][0]["temporal"]["state"] == "active"


def test_compile_normalizer_preserves_temporal_policy_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(compile_v2, "PAGES_DIR", tmp_path / "pages")
    page = """---
type: policy
title: New reimbursement rule
description: Applies next quarter.
effective_from: 2026-10-01
effective_until: 2027-01-01
supersedes: [/policies/old.md]
---
# New reimbursement rule
"""

    parsed = compile_v2._okf_page_from_model(page, "policy.pdf")

    assert parsed is not None
    metadata = parsed[1]
    assert str(metadata["effective_from"]) == "2026-10-01"
    assert str(metadata["effective_until"]) == "2027-01-01"
    assert metadata["supersedes"] == ["/policies/old.md"]


def test_agent_synthesis_task_explains_temporal_states(tmp_path: Path):
    page = _policy(
        tmp_path / "policy.md",
        "type: Policy\neffective_from: 2026-01-01",
    )
    context = query_time_context(
        "当前政策是什么？",
        now=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    ranked = rank_temporal_results(
        [{"id": "policy", "path": str(page), "type": "policy", "score": 1.0}],
        context,
        limit=1,
    )

    task = query.synthesize_answer_agent(
        "当前政策是什么？",
        ranked,
        temporal_context=context,
    )

    assert "时效性判定" in task
    assert "scheduled" in task
    assert "**Temporal State**: active" in task
