"""Deterministic, citation-bound checks for synthesized wiki answers."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Any

_CITATION = re.compile(
    r"(?<!!)\[[^\]\n]+\]\(<?/?(?P<markdown>[^\s():#<>]+)\.md"
    r"(?:#[^\s)<>]*)?>?\)|\[\[(?P<wikilink>[^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]"
)
_MODALITY = re.compile(
    r"(?P<deny>不可以|不允许|不准|不可|不得|严禁|禁止|"
    r"\b(?:must|shall|may|should)\s+not\b|\b(?:cannot|can['’]t)\b|"
    r"\bnot\s+(?:allowed|permitted|authorized)\b|"
    r"\b(?:do|does|did)\s+not\s+(?:allow|permit|authorize)\b|"
    r"\b(?:prohibit(?:s|ed)?|forbid(?:s|den)?|banned)\b)"
    r"|(?P<allow>不禁止|允许|准许|可以|\bnot\s+(?:prohibited|forbidden)\b|"
    r"\b(?:allow(?:s|ed)?|permit(?:s|ted)?|authoriz(?:es|ed)|can)\b|"
    r"\bmay\b(?!\s+\d))",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?<![a-z0-9.,])(?P<value>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?!\d|[.,]\d)"
    r"(?:[ \t]*(?P<unit>[%％]|天|日|周|个月|月|年|小时|分钟|秒|"
    r"days?\b|weeks?\b|months?\b|years?\b|hours?\b|minutes?\b|seconds?\b))?",
    re.IGNORECASE,
)
_UNITS = {
    "天": "day",
    "日": "day",
    "周": "week",
    "个月": "month",
    "月": "month",
    "年": "year",
    "小时": "hour",
    "分钟": "minute",
    "秒": "second",
}
_CLAUSE_BOUNDARY = re.compile(r"(?<=[。！？；;])\s*|(?<=[.!?])\s+|(?<!\d),|,(?!\d)")
_ANSWER_DATE = re.compile(
    r"^(?:(?P<marker>截至|截止|在|于|as of|on)\s*)?"
    r"(?P<year>\d{4})\s*(?:年\s*|[-/])"
    r"(?P<month>\d{1,2})\s*(?:月\s*|[-/])(?P<day>\d{1,2})(?!\d)\s*日?",
    re.IGNORECASE,
)
_RULE_PREFIX = re.compile(
    r"^(?:(?:当日|当天|当时|现行|当前|目前)\s*)?"
    r'(?:适用(?:的)?|有效的)\s*[“"]?(?P<version>[a-zA-Z0-9_\-\u3400-\u9fff]{1,24}?版)'
    r'[”"]?\s*[,，:：]?\s*'
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEK_RANGE = re.compile(
    rf"\b({'|'.join(_WEEKDAYS)})\s*(?:to|[-–—])\s*({'|'.join(_WEEKDAYS)})\b",
    re.IGNORECASE,
)
_CJK_WEEK_RANGE = r"(?:周|星期)([一二三四五六日天])(?:至|到|[-–—])(?:周|星期)?([一二三四五六日天])"
_WEEKDAY_REFERENCE = re.compile(r"(?:周|星期)([一二三四五六日天])(?:也)?适用(?:该|此)时段")
_WEEKDAY_MEMBERSHIP = re.compile(
    rf"(?:周|星期)([一二三四五六日天])(?:在|属于){_CJK_WEEK_RANGE}(?:的)?(?:营业|开放)?时段(?:内)?"
)
_CLOCK_TIME = re.compile(r"(?<![\d.])\d{1,2}(?::[0-5]\d|\.[0-5]\d)\s*(?:am|pm)", re.I)
_CLOSING_TERMS = r"关门|关闭|停止(?:借具|开放)|\bclos(?:e|es|ing)\b"
_STOP_WORDS = {
    "about",
    "and",
    "are",
    "does",
    "for",
    "from",
    "how",
    "into",
    "must",
    "shall",
    "that",
    "the",
    "this",
    "was",
    "were",
    "what",
    "when",
    "which",
    "who",
    "with",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
    "hour",
    "hours",
    "minute",
    "minutes",
    "second",
    "seconds",
    "是否",
    "能否",
    "多久",
    "多少",
    "如何",
    "什么",
    "请问",
    "以及",
    "因此",
    "应当",
}


def _citation_ids(text: str) -> set[str]:
    return {
        (match["markdown"] or match["wikilink"]).strip().removeprefix("/").removesuffix(".md")
        for match in _CITATION.finditer(text)
    }


def answer_body(answer: str) -> str:
    stripped = answer.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped.removeprefix("```json").removesuffix("```").strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return answer
        if isinstance(payload, dict) and isinstance(payload.get("answer"), str):
            return payload["answer"]
    return answer


def _plain(text: str) -> str:
    text = _CITATION.sub("", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Ignore positional list indices and Markdown markup, keeping dates and quantities.
    text = re.sub(r"^\s*(?:\d+[.)]|\[\d+\])(?:\s+|$)", "", text)
    return unicodedata.normalize("NFKC", re.sub(r"[*`_]", "", text)).strip(" #|\t")


def _terms(text: str) -> set[str]:
    normalized = _MODALITY.sub(" ", text.casefold())
    latin = {
        word.removesuffix("s")
        for word in re.findall(r"[a-z]{3,}", normalized)
        if word not in _STOP_WORDS
    }
    cjk = {
        sequence[index : index + 2]
        for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized)
        for index in range(len(sequence) - 1)
    }
    return (latin | cjk) - _STOP_WORDS


def _clauses(text: str) -> list[str]:
    # Split punctuation between statements without splitting decimal values.
    return [part.strip() for part in _CLAUSE_BOUNDARY.split(text) if part.strip()]


def _claim_lines(answer: str) -> list[tuple[str, set[str]]]:
    rows = []
    table_header = ""
    in_fence = False
    lines = answer_body(answer).splitlines()
    for index, line in enumerate(lines):
        line = line.strip()
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not line or (in_fence and not _NUMBER.search(line) and not _MODALITY.search(line)):
            continue
        text = _plain(line).strip(" -–—:。.")
        if not text or not re.search(r"\w", text):
            continue
        if re.fullmatch(
            r"(?:answer|sources|citations|related|references|答案|来源|引用|相关)", text, re.I
        ):
            continue
        if line.startswith("#") and not (_NUMBER.search(text) or _MODALITY.search(text)):
            continue
        ids = _citation_ids(line)
        if line.startswith("|"):
            if (
                index + 1 < len(lines)
                and re.fullmatch(r"[\s|:\-]+", lines[index + 1])
                and "-" in lines[index + 1]
                and not (_NUMBER.search(text) or _MODALITY.search(text))
            ):
                table_header = text
                continue
            if table_header:
                text = f"{table_header} | {text}"
        else:
            table_header = ""
        # Link-only source lists only name evidence and do not support other lines.
        rows.append((text, ids))
    return rows


def _number_value(match: re.Match[str]) -> tuple[Decimal, str]:
    unit = (match["unit"] or "").casefold()
    return Decimal(match["value"].replace(",", "")), _UNITS.get(unit, unit.rstrip("s"))


def _closest(text: str, candidates: list[str], question: str) -> list[str]:
    terms = _terms(text)
    if not terms and _NUMBER.search(text):
        normalized = text.strip(" .。!?;")
        exact = [candidate for candidate in candidates if candidate.strip(" .。!?;") == normalized]
        if exact:
            return exact
    terms = terms or _terms(question)
    scores = [len(terms & _terms(candidate)) for candidate in candidates]
    best = max(scores, default=0)
    return [candidate for candidate, score in zip(candidates, scores) if score == best]


def _number_label(text: str, match: re.Match[str]) -> list[str]:
    prefix = text[: match.start()].strip()
    prefix = re.sub(r"(?:为期|定为|为|是|共|\b(?:is|are|was|were)\b)[\s:：=|]*$", "", prefix)
    return re.findall(r"[a-z]+|[\u3400-\u9fff]", prefix.casefold())


def _label_overlap(left: list[str], right: list[str]) -> int:
    overlap = 0
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            break
        overlap += len(a)
    return overlap


def _comparable_numbers(
    text: str, numbers: list[re.Match[str]], chunks: list[str], question: str
) -> list[set[tuple[Decimal, str]]]:
    candidates = {chunk: list(_NUMBER.finditer(chunk)) for chunk in chunks}
    candidates = {chunk: matches for chunk, matches in candidates.items() if matches}
    lexical = _closest(text, list(candidates), question)
    fallback = {_number_value(match) for chunk in lexical for match in candidates[chunk]}
    located = [
        (chunk, match, _number_label(chunk, match))
        for chunk, matches in candidates.items()
        for match in matches
    ]
    comparisons = []
    for number in numbers:
        label = _number_label(text, number)
        bound = [(_label_overlap(label, field), chunk, match) for chunk, match, field in located]
        best = max((score for score, _, _ in bound), default=0)
        if best < 2:
            comparisons.append(fallback)
            continue
        anchored = [(chunk, match) for score, chunk, match in bound if score == best]
        closest = set(_closest(text, [chunk for chunk, _ in anchored], question))
        comparisons.append({_number_value(match) for chunk, match in anchored if chunk in closest})
    return comparisons


def _scope_temporal_claim(
    text: str, ids: set[str], evidence: dict[str, str], temporal: dict[str, Any]
) -> tuple[str, str]:
    """Check applicability at the query date and keep that date out of quantity matching."""
    if not temporal:
        return text, ""
    states = {identifier: temporal["states"].get(identifier, "undated") for identifier in ids}
    if any(state in {"expired", "scheduled"} for state in states.values()):
        return text, "cited_policy_not_effective"
    active = [identifier for identifier, state in states.items() if state == "active"]
    policy = temporal.get("rule_request") or bool(ids.intersection(temporal["policy_ids"]))
    if not active and not policy and not _RULE_PREFIX.search(text) and "适用" not in text:
        return text, ""

    date_match = _ANSWER_DATE.match(text)
    if date_match and (date_match["marker"] or _RULE_PREFIX.match(text[date_match.end() :])):
        try:
            claimed_date = date(*(int(date_match[key]) for key in ("year", "month", "day")))
        except ValueError:
            return text, "invalid_answer_date"
        if claimed_date.isoformat() != temporal["date"]:
            return text, "answer_date_differs_from_query"
        if active:
            text = text[date_match.end() :].lstrip(" ,，:：")

    version = _RULE_PREFIX.match(text)
    if version:
        if not active:
            return text, "effective_interval_unverified"
        label = version["version"].casefold()
        if not any(
            label in unicodedata.normalize("NFKC", evidence[item]).casefold()
            for item in active
            if item in evidence
        ):
            return text, "applicable_version_unverified"
        return text[version.end() :], ""
    if not active and policy:
        return text, "effective_interval_unverified"
    return text, ""


def _weekday_reference_supported(clause: str, statement: str, chunks: list[str]) -> bool:
    """Resolve a weekday clause only against the cited range with the claimed closing time."""
    clause = clause.rstrip(".。!?")
    reference = _WEEKDAY_REFERENCE.fullmatch(clause)
    membership = _WEEKDAY_MEMBERSHIP.search(statement)
    if not (reference or membership) or not re.search(_CLOSING_TERMS, statement, re.I):
        return False
    times = _CLOCK_TIME.findall(statement)
    stated_range = re.search(_CJK_WEEK_RANGE, statement)
    if len(times) != 1 or stated_range is None:
        return False
    weekdays = "一二三四五六日天"
    if reference:
        days = (reference[1], *stated_range.groups())
    else:
        assert membership is not None
        days = membership.groups()
    weekday, stated_first, stated_last = (min(weekdays.index(day), 6) for day in days)
    expected = re.sub(r"\s+", "", times[0]).casefold().replace(".", ":")
    closing_times = set()
    for chunk in chunks:
        day_range = _WEEK_RANGE.search(chunk)
        if not day_range:
            continue
        first, last = (_WEEKDAYS.index(day.casefold()) for day in day_range.groups())
        hours = _CLOCK_TIME.findall(chunk[day_range.end() :])
        if (
            (first, last) == (stated_first, stated_last)
            and first <= weekday <= last
            and len(hours) == 2
        ):
            closing_times.add(re.sub(r"\s+", "", hours[-1]).casefold().replace(".", ":"))
    if closing_times != {expected}:
        return False
    if reference:
        return True
    if re.fullmatch(rf"{re.escape(times[0])}\s*(?:{_CLOSING_TERMS})", clause, re.I):
        return True
    remaining = _WEEKDAY_MEMBERSHIP.sub("", clause)
    terms = _terms(remaining)
    return remaining != clause and terms <= _terms(" ".join(chunks))


def _modalities(text: str) -> set[str]:
    return {match.lastgroup for match in _MODALITY.finditer(text) if match.lastgroup}


def verify(
    answer: str,
    evidence: dict[str, str],
    question: str = "",
    *,
    temporal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check each cited statement against the selected local evidence."""
    statements = _claim_lines(answer)
    cited = _citation_ids(answer_body(answer))
    unsupported = sorted(cited - evidence.keys())
    unverified_values = []
    unsupported_claims = []
    polarity_conflicts = []
    temporal_conflicts = []
    missing_citations = []

    for text, ids in statements:
        claim = text[:240]
        if not ids:
            missing_citations.append(claim)
            continue
        if temporal:
            text, issue = _scope_temporal_claim(text, ids, evidence, temporal)
            if issue:
                temporal_conflicts.append(
                    {
                        "claim": claim,
                        "reason": issue,
                        "as_of": temporal["date"],
                        "citation_ids": sorted(ids),
                    }
                )
                continue
        chunks = [
            clause
            for identifier in sorted(ids & evidence.keys())
            for line in evidence[identifier].splitlines()
            for clause in _clauses(_plain(line))
            if clause
        ]
        for clause in _clauses(text):
            numbers = list(_NUMBER.finditer(clause))
            if numbers:
                comparisons = _comparable_numbers(clause, numbers, chunks, question)
                for match, supported in zip(numbers, comparisons, strict=True):
                    value, unit = _number_value(match)
                    comparable = {v for v, u in supported if not unit or u == unit}
                    if value not in comparable or (
                        unit and len(numbers) == 1 and len(comparable) > 1
                    ):
                        unverified_values.append(
                            {
                                "value": match["value"],
                                "unit": unit,
                                "evidence_values": [str(v) for v in sorted(comparable)],
                                "claim": claim,
                                "citation_ids": sorted(ids),
                            }
                        )

            modalities = _modalities(clause)
            if modalities:
                matching = _closest(
                    clause, [chunk for chunk in chunks if _modalities(chunk)], question
                )
                evidence_modes = set().union(*map(_modalities, matching))
                if evidence_modes and evidence_modes != modalities:
                    polarity_conflicts.append(
                        {
                            "claim": claim,
                            "answer_polarity": sorted(modalities),
                            "evidence_polarity": sorted(evidence_modes),
                            "evidence_excerpts": [item[:240] for item in dict.fromkeys(matching)][
                                :3
                            ],
                            "citation_ids": sorted(ids),
                        }
                    )
                elif not evidence_modes:
                    unsupported_claims.append({"claim": claim, "citation_ids": sorted(ids)})

            terms = _terms(clause)
            matched = terms & _terms(" ".join(chunks))
            lexical_support = len(matched) / len(terms) if terms else float(bool(chunks))
            if lexical_support < 0.45 and not _weekday_reference_supported(clause, text, chunks):
                unsupported_claims.append(
                    {
                        "claim": claim,
                        "citation_ids": sorted(ids),
                        "lexical_support": round(lexical_support, 4),
                    }
                )

    coverage = (len(statements) - len(missing_citations)) / len(statements) if statements else 0.0
    passed = bool(statements) and not (
        unsupported
        or unverified_values
        or unsupported_claims
        or polarity_conflicts
        or temporal_conflicts
        or missing_citations
    )
    return {
        "status": "pass" if passed else "warning",
        "citation_coverage": round(coverage, 4),
        "cited_concepts": sorted(cited),
        "unsupported_citations": unsupported,
        "unverified_values": unverified_values,
        "unsupported_claims": unsupported_claims,
        "polarity_conflicts": polarity_conflicts,
        "temporal_conflicts": temporal_conflicts,
        "missing_citations": missing_citations,
        "claims_checked": len(statements),
    }
