"""Claim-level knowledge extraction for OKF concept pages.

OKF v0.1 deliberately permits extension metadata.  This module keeps the
canonical Markdown page intact while exposing small, attributable knowledge
units for retrieval, contradiction checks, and answer verification.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

MAX_CLAIMS_PER_PAGE = 200
CLAIM_FIELDS = {
    "id",
    "subject",
    "predicate",
    "value",
    "modality",
    "conditions",
    "exceptions",
    "audience",
    "jurisdiction",
    "effective_from",
    "effective_until",
    "source",
    "source_kind",
    "footnotes",
    "confidence",
}
MODALITIES = {
    "fact",
    "must",
    "must_not",
    "may",
    "should",
    "entitlement",
    "definition",
    "procedure",
}


def _list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("| "))


def _claim_id(page_id: str, subject: str, predicate: str, value: str) -> str:
    payload = "\x1f".join((page_id, subject, predicate, value)).encode("utf-8")
    return f"{page_id}#claim-{hashlib.sha256(payload).hexdigest()[:12]}"


def infer_modality(text: str) -> str:
    """Infer only explicit normative language; otherwise return ``fact``."""
    lowered = text.casefold()
    if re.search(r"(?:不得|禁止|严禁|must\s+not|shall\s+not|prohibited)", lowered):
        return "must_not"
    if re.search(r"(?:必须|须要|应当|务必|must|shall|required)", lowered):
        return "must"
    if re.search(r"(?:可以|可选择|may|optional|permitted)", lowered):
        return "may"
    if re.search(r"(?:建议|应该|should|recommended)", lowered):
        return "should"
    if re.search(r"(?:定义为|是指|means|defined as)", lowered):
        return "definition"
    return "fact"


def normalize_claim(
    raw: dict[str, Any],
    page_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a conservative, JSON/YAML-safe claim or ``None`` if unusable."""
    metadata = metadata or {}
    subject = _clean_cell(str(raw.get("subject") or metadata.get("title") or page_id))
    predicate = _clean_cell(str(raw.get("predicate") or raw.get("attribute") or ""))
    value = _clean_cell(str(raw.get("value") or raw.get("object") or ""))
    if not predicate or not value:
        return None

    claim: dict[str, Any] = {
        "id": str(raw.get("id") or _claim_id(page_id, subject, predicate, value)),
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "modality": str(raw.get("modality") or infer_modality(f"{predicate} {value}")),
    }
    if claim["modality"] not in MODALITIES:
        claim["modality"] = "fact"

    inherited = {
        "audience": metadata.get("audience") or metadata.get("applies_to"),
        "jurisdiction": metadata.get("jurisdiction"),
        "effective_from": metadata.get("effective_from") or metadata.get("valid_from"),
        "effective_until": metadata.get("effective_until") or metadata.get("valid_until"),
    }
    for field in ("conditions", "exceptions", "audience", "jurisdiction", "footnotes"):
        values = _list(raw.get(field) if raw.get(field) not in (None, "") else inherited.get(field))
        if values:
            claim[field] = values
    for field in ("effective_from", "effective_until"):
        value_from_claim = raw.get(field) or inherited.get(field)
        if value_from_claim not in (None, ""):
            claim[field] = str(value_from_claim)
    for field in ("source", "source_kind"):
        if raw.get(field) not in (None, ""):
            claim[field] = raw[field]
    try:
        confidence = float(raw.get("confidence", metadata.get("confidence", 0.8)))
    except (TypeError, ValueError):
        confidence = 0.8
    claim["confidence"] = round(min(max(confidence, 0.0), 1.0), 3)
    return claim


def _footnotes(body: str) -> dict[str, str]:
    notes: dict[str, str] = {}
    for key, value in re.findall(r"(?m)^\[\^([^\]]+)\]:\s*(.+(?:\n(?: {2,}|\t).+)*)$", body):
        notes[key] = re.sub(r"\s+", " ", value).strip()
    return notes


def _table_claims(
    body: str,
    page_id: str,
    metadata: dict[str, Any],
    notes: dict[str, str],
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    current_heading = ""
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        heading_match = re.match(r"^#{1,6}\s+(.+)$", lines[index].strip())
        if heading_match:
            current_heading = heading_match.group(1).strip()
            index += 1
            continue
        if "|" not in lines[index] or index + 1 >= len(lines):
            index += 1
            continue
        header = [_clean_cell(cell) for cell in lines[index].strip().strip("|").split("|")]
        separator = lines[index + 1].strip()
        if len(header) < 2 or not re.fullmatch(r"\|?\s*[-:]+(?:\s*\|\s*[-:]+)+\s*\|?", separator):
            index += 1
            continue
        index += 2
        row_number = 0
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            cells = [_clean_cell(cell) for cell in lines[index].strip().strip("|").split("|")]
            if len(cells) != len(header):
                break
            row_number += 1
            is_fact_table = any(
                marker in current_heading.casefold()
                for marker in ("key facts", "关键事实", "核心事实")
            )
            if is_fact_table and len(cells) >= 2:
                raw = {
                    "predicate": cells[0],
                    "value": " | ".join(cells[1:]),
                    "source_kind": "key_facts_table",
                    "source": {"section": current_heading, "row": row_number},
                }
                referenced = re.findall(r"\[\^([^\]]+)\]", raw["value"])
                footnote_values = [notes[key] for key in referenced if key in notes]
                if footnote_values:
                    raw["footnotes"] = footnote_values
                claim = normalize_claim(raw, page_id, metadata)
                if claim:
                    claims.append(claim)
            else:
                row = {column: value for column, value in zip(header, cells) if column and value}
                if row:
                    primary = next(iter(row.values()))
                    raw = {
                        "subject": primary,
                        "predicate": current_heading or "table row",
                        "value": "; ".join(f"{key}: {value}" for key, value in row.items()),
                        "source_kind": "table",
                        "source": {
                            "section": current_heading or "table",
                            "row": row_number,
                            "columns": header,
                        },
                    }
                    referenced = re.findall(r"\[\^([^\]]+)\]", raw["value"])
                    footnote_values = [notes[key] for key in referenced if key in notes]
                    if footnote_values:
                        raw["footnotes"] = footnote_values
                    claim = normalize_claim(raw, page_id, metadata)
                    if claim:
                        claims.append(claim)
            index += 1
    return claims


def _key_value_claims(
    body: str,
    page_id: str,
    metadata: dict[str, Any],
    notes: dict[str, str],
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    current_heading = ""
    for line_number, line in enumerate(body.splitlines(), 1):
        heading = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if heading:
            current_heading = heading.group(1).strip()
            continue
        match = re.match(r"^\s*[-*]?\s*\*\*([^*]+)\*\*\s*[:：]\s*(.+?)\s*$", line)
        if not match:
            continue
        predicate, value = (_clean_cell(part) for part in match.groups())
        raw: dict[str, Any] = {
            "predicate": predicate,
            "value": value,
            "source_kind": "key_value",
            "source": {"section": current_heading, "line": line_number},
        }
        referenced = re.findall(r"\[\^([^\]]+)\]", value)
        footnote_values = [notes[key] for key in referenced if key in notes]
        if footnote_values:
            raw["footnotes"] = footnote_values
        claim = normalize_claim(raw, page_id, metadata)
        if claim:
            claims.append(claim)
    return claims


def extract_claims(
    metadata: dict[str, Any],
    body: str,
    page_id: str,
) -> list[dict[str, Any]]:
    """Read explicit claims and deterministically derive claims from Markdown."""
    claims: list[dict[str, Any]] = []
    explicit = metadata.get("claims", [])
    if isinstance(explicit, dict):
        explicit = [explicit]
    if isinstance(explicit, list):
        for raw in explicit:
            if isinstance(raw, dict):
                claim = normalize_claim(raw, page_id, metadata)
                if claim:
                    claims.append(claim)

    notes = _footnotes(body)
    claims.extend(_table_claims(body, page_id, metadata, notes))
    claims.extend(_key_value_claims(body, page_id, metadata, notes))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        key = (
            str(claim.get("subject", "")).casefold(),
            str(claim.get("predicate", "")).casefold(),
            str(claim.get("value", "")).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
        if len(deduped) >= MAX_CLAIMS_PER_PAGE:
            break
    return deduped


def validate_claims(claims: Any) -> list[str]:
    """Return human-readable schema errors for explicit claim metadata."""
    if claims in (None, []):
        return []
    if not isinstance(claims, list):
        return ["claims must be a list"]
    errors: list[str] = []
    ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claims[{index}] must be a mapping")
            continue
        for field in ("subject", "predicate", "value"):
            if not str(claim.get(field, "")).strip():
                errors.append(f"claims[{index}].{field} is required")
        unknown = sorted(set(claim) - CLAIM_FIELDS)
        if unknown:
            errors.append(f"claims[{index}] has unknown fields: {', '.join(unknown)}")
        claim_id = str(claim.get("id", ""))
        if claim_id and claim_id in ids:
            errors.append(f"duplicate claim id: {claim_id}")
        ids.add(claim_id)
    return errors


def claim_text(claim: dict[str, Any]) -> str:
    """Render all retrieval-bearing claim fields as a stable text string."""
    parts: list[str] = []
    for field in (
        "subject",
        "predicate",
        "value",
        "modality",
        "conditions",
        "exceptions",
        "audience",
        "jurisdiction",
        "effective_from",
        "effective_until",
        "footnotes",
    ):
        value = claim.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value not in (None, ""):
            parts.append(str(value))
    return " ".join(parts)


def source_authority(metadata: dict[str, Any]) -> float:
    """Return a bounded authority score without inventing source provenance."""
    raw = metadata.get("source_authority")
    try:
        if raw not in (None, ""):
            return min(max(float(raw), 0.0), 1.0)
    except (TypeError, ValueError):
        pass
    label = str(metadata.get("document_status") or metadata.get("source_type") or "").casefold()
    if any(term in label for term in ("official", "正式", "法规", "标准", "signed")):
        return 1.0
    if any(term in label for term in ("approved", "批准", "发布")):
        return 0.9
    if any(term in label for term in ("draft", "草案", "征求意见")):
        return 0.45
    if any(term in label for term in ("meeting", "会议", "note", "笔记")):
        return 0.35
    return 0.6


def _normalized_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value).casefold())


def _qualifier_set(claim: dict[str, Any], field: str) -> set[str]:
    return {
        _normalized_value(value) for value in _list(claim.get(field)) if _normalized_value(value)
    }


def _intervals_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return False only when ISO-like applicability intervals are provably disjoint."""
    try:
        try:
            from query_temporal import parse_instant
        except ImportError:
            from .query_temporal import parse_instant

        left_start = parse_instant(left.get("effective_from"))
        left_end = parse_instant(left.get("effective_until"))
        right_start = parse_instant(right.get("effective_from"))
        right_end = parse_instant(right.get("effective_until"))
    except (ImportError, TypeError, ValueError):
        return True
    if left_end is not None and right_start is not None and left_end <= right_start:
        return False
    if right_end is not None and left_start is not None and right_end <= left_start:
        return False
    return True


def claims_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Detect a conflict only when identity, scope, conditions, and time overlap."""
    if _normalized_value(left.get("subject")) != _normalized_value(right.get("subject")):
        return False
    if _normalized_value(left.get("predicate")) != _normalized_value(right.get("predicate")):
        return False
    if _normalized_value(left.get("value")) == _normalized_value(right.get("value")):
        return False
    for field in ("jurisdiction", "audience"):
        left_scope = _qualifier_set(left, field)
        right_scope = _qualifier_set(right, field)
        if left_scope and right_scope and left_scope.isdisjoint(right_scope):
            return False
    for field in ("conditions", "exceptions"):
        left_conditions = _qualifier_set(left, field)
        right_conditions = _qualifier_set(right, field)
        if left_conditions and right_conditions and left_conditions != right_conditions:
            return False
    if not _intervals_overlap(left, right):
        return False
    modalities = {str(left.get("modality", "fact")), str(right.get("modality", "fact"))}
    if modalities == {"must", "must_not"}:
        return True
    left_has_number = bool(re.search(r"\d", str(left.get("value", ""))))
    right_has_number = bool(re.search(r"\d", str(right.get("value", ""))))
    return left_has_number or right_has_number or modalities & {"must", "must_not", "entitlement"}


def detect_claim_conflicts(
    existing_claims: list[dict[str, Any]],
    incoming_claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return explainable claim-level conflicts with qualifiers preserved."""
    conflicts: list[dict[str, Any]] = []
    for existing in existing_claims:
        for incoming in incoming_claims:
            if claims_conflict(existing, incoming):
                conflicts.append(
                    {
                        "existing_claim": existing,
                        "new_claim": incoming,
                        "contradiction_type": (
                            "temporal"
                            if existing.get("effective_from") or incoming.get("effective_from")
                            else (
                                "numerical"
                                if re.search(
                                    r"\d",
                                    f"{existing.get('value', '')}{incoming.get('value', '')}",
                                )
                                else "factual"
                            )
                        ),
                        "severity": "high",
                        "resolution_suggestion": (
                            "Review source authority and applicability qualifiers; preserve both "
                            "claims until one is explicitly superseded."
                        ),
                    }
                )
    return conflicts
