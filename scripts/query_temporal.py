"""Effective-time semantics for time-sensitive OKF concepts.

Publication time, knowledge freshness, and legal/business applicability are
different clocks.  This module only uses explicit applicability metadata:

``effective_from``
    Inclusive start instant/date.
``effective_until``
    Exclusive end instant/date.  At this instant the concept no longer applies.
``supersedes`` / ``superseded_by``
    Concept IDs used to infer the old rule's end from the replacement's start.

Unknown or absent dates remain unknown.  In particular, ``timestamp``,
``generated.at`` and ``stale_after`` are never treated as effective dates.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import yaml

START_FIELDS = ("effective_from", "valid_from", "effective_at")
END_FIELDS = ("effective_until", "valid_until")
CURRENT_TERMS = (
    "当前",
    "目前",
    "最新",
    "现在",
    "今天",
    "现行",
    "现在生效",
    "截至现在",
    "current",
    "currently",
    "latest",
    "effective now",
    "as of now",
    "today",
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_instant(value: Any, default_timezone: Any = timezone.utc) -> datetime | None:
    """Parse an ISO date/datetime-like value as a comparable UTC instant."""
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, date):
        return _utc(datetime.combine(value, time.min, tzinfo=default_timezone))
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=default_timezone)
        return _utc(parsed)
    except ValueError:
        pass
    for pattern in ("%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return _utc(datetime.strptime(raw, pattern).replace(tzinfo=default_timezone))
        except ValueError:
            continue
    return None


def query_time_context(query: str, now: datetime | None = None) -> dict[str, Any]:
    """Return the requested answer time without guessing from unrelated dates."""
    local_reference = now or datetime.now().astimezone()
    if local_reference.tzinfo is None:
        local_reference = local_reference.replace(tzinfo=timezone.utc)
    reference = _utc(local_reference)
    boundary_timezone = local_reference.tzinfo or timezone.utc
    lowered = query.casefold()
    if any(term in lowered for term in CURRENT_TERMS):
        return {
            "requested": True,
            "mode": "current",
            "as_of": reference,
            "explicit": False,
            "timezone": boundary_timezone,
        }

    patterns = (
        r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, query)
        if not match:
            continue
        try:
            as_of = _utc(
                datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=boundary_timezone,
                )
            )
        except ValueError:
            continue
        return {
            "requested": True,
            "mode": "as_of",
            "as_of": as_of,
            "explicit": True,
            "matched": match.group(0),
            "timezone": boundary_timezone,
        }

    return {
        "requested": False,
        "mode": "unspecified",
        "as_of": reference,
        "explicit": False,
        "timezone": boundary_timezone,
    }


def _read_frontmatter(path_value: str) -> dict[str, Any]:
    if not path_value or path_value.startswith("table://"):
        return {}
    try:
        text = Path(path_value).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, PermissionError):
        return {}
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.DOTALL)
    if not match:
        return {}
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _first_instant(
    metadata: dict[str, Any], fields: tuple[str, ...], default_timezone: Any = timezone.utc
) -> datetime | None:
    for field in fields:
        parsed = parse_instant(metadata.get(field), default_timezone)
        if parsed is not None:
            return parsed
    return None


def _as_ids(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        concept_id = str(item or "").strip().split("#", 1)[0].lstrip("/")
        if concept_id.endswith(".md"):
            concept_id = concept_id[:-3]
        if concept_id:
            normalized.append(concept_id)
    return normalized


def _iso(value: datetime | None) -> str:
    return value.isoformat().replace("+00:00", "Z") if value else ""


def rank_temporal_results(
    results: list[dict[str, Any]],
    context: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    """Annotate and rank results by applicability at the requested instant.

    No result is discarded merely because it is historical or scheduled.  The
    applicable rule ranks first, a scheduled replacement remains available for
    an "effective from" notice, and expired material remains available for
    historical explanation.
    """
    if not results:
        return []
    if not context.get("requested"):
        return [dict(item) for item in results[:limit]]

    as_of = _utc(context["as_of"])
    boundary_timezone = context.get("timezone") or timezone.utc
    annotated: list[dict[str, Any]] = []
    metadata_by_id: dict[str, dict[str, Any]] = {}
    for index, result in enumerate(results):
        item = dict(result)
        concept_id = str(item.get("id") or item.get("file") or "")
        metadata = _read_frontmatter(str(item.get("path", "")))
        item["_temporal_original_rank"] = index
        annotated.append(item)
        if concept_id:
            metadata_by_id[concept_id] = metadata

    inferred_ends: dict[str, list[datetime]] = {}
    for concept_id, metadata in metadata_by_id.items():
        replacement_start = _first_instant(metadata, START_FIELDS, boundary_timezone)
        if replacement_start is not None:
            for old_id in _as_ids(metadata.get("supersedes")):
                inferred_ends.setdefault(old_id, []).append(replacement_start)
        for new_id in _as_ids(metadata.get("superseded_by")):
            replacement = metadata_by_id.get(new_id, {})
            new_start = _first_instant(replacement, START_FIELDS, boundary_timezone)
            if new_start is not None:
                inferred_ends.setdefault(concept_id, []).append(new_start)

    priority = {"active": 4, "undated": 3, "scheduled": 2, "expired": 1}
    for item in annotated:
        concept_id = str(item.get("id") or item.get("file") or "")
        metadata = metadata_by_id.get(concept_id, {})
        start = _first_instant(metadata, START_FIELDS, boundary_timezone)
        end = _first_instant(metadata, END_FIELDS, boundary_timezone)
        inferred = min(inferred_ends.get(concept_id, []), default=None)
        used_inferred_end = False
        if end is None or (inferred is not None and inferred < end):
            end = inferred or end
            used_inferred_end = inferred is not None
        if start is not None and as_of < start:
            state = "scheduled"
        elif end is not None and as_of >= end:
            state = "expired"
        elif start is not None or end is not None:
            state = "active"
        else:
            state = "undated"
        item["temporal"] = {
            "state": state,
            "as_of": _iso(as_of),
            "effective_from": _iso(start),
            "effective_until": _iso(end),
            "effective_until_inferred": used_inferred_end,
            "status": str(metadata.get("status", "")),
            "date_basis": "explicit applicability metadata" if state != "undated" else "unknown",
        }
        base_score = float(item.get("rerank_score", item.get("score", 0)) or 0)
        item["temporal_score"] = round(base_score + priority[state], 4)

    annotated.sort(
        key=lambda item: (
            priority[item["temporal"]["state"]],
            float(item.get("rerank_score", item.get("score", 0)) or 0),
            -int(item["_temporal_original_rank"]),
        ),
        reverse=True,
    )
    for item in annotated:
        item.pop("_temporal_original_rank", None)
    return annotated[:limit]


def temporal_guidance(context: dict[str, Any], chinese: bool) -> str:
    """Return synthesis rules for an applicability-aware query."""
    if not context.get("requested"):
        return ""
    as_of = _iso(_utc(context["as_of"]))
    if chinese:
        return f"""## 时效性判定（强制）
本次回答时点为 `{as_of}`。必须以每篇文档标注的 Temporal State 为准：
- `active`：在该时点适用，作为“当前/当时政策”的主要答案。
- `scheduled`：尚未生效，不得当成现行规则；可明确提示其未来生效日期。
- `expired`：在该时点已失效，只能用于历史沿革或对比。
- `undated`：缺少明确生效区间，必须说明时效性未知，不得仅凭发布时间猜测。
若旧规与未来替代规则同时出现，替代规则生效前继续按旧规回答，并补充未来变化。
`timestamp`、`generated.at` 是文档更新时间，`stale_after` 是复核时间，都不是法规生效时间。"""
    return f"""## Temporal applicability (mandatory)
The answer instant is `{as_of}`. Use each document's Temporal State:
- `active`: applicable at that instant and authoritative for the current/as-of answer.
- `scheduled`: not yet effective; never present it as current, but note its future start date.
- `expired`: no longer effective at that instant; use only for history or comparison.
- `undated`: applicability is unknown; do not infer it from publication time.
When an old rule and a scheduled replacement coexist, answer with the old rule until the
replacement's effective time and mention the upcoming change. `timestamp`, `generated.at`,
and `stale_after` are not legal/business effective dates."""
