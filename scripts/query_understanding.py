"""Deterministic structured query understanding for wiki retrieval."""

from __future__ import annotations

import re
from typing import Any

_INTENT_MARKERS = {
    "structural_lookup": (
        "第几页",
        "第1页",
        "第2页",
        "页码",
        "封面",
        "page ",
        "page(",
        "cover page",
        "unit-",
        "unit ",
    ),
    "exact_lookup": (
        "邮箱",
        "邮件地址",
        "电话",
        "传真",
        "网址",
        "案号",
        "编号",
        "类名",
        "email",
        "e-mail",
        "fax",
        "phone",
        "web link",
        "case number",
        "filing id",
        "class name",
        "defendant",
        "plaintiff",
        "code ",
        "what date",
        "what amount",
    ),
    "comparison": ("比较", "对比", "区别", "差异", "compare", "difference", "versus", "vs"),
    "relationship": ("影响", "依赖", "关系", "路径", "关联", "impact", "depends", "relationship"),
    "procedure": ("如何", "怎么", "步骤", "流程", "how to", "procedure", "steps"),
    "definition": ("是什么", "定义", "含义", "what is", "define", "meaning"),
    "aggregation": (
        "多少",
        "总计",
        "合计",
        "平均",
        "最大",
        "最小",
        "how many",
        "count",
        "sum",
        "average",
    ),
    "ledger_filter": ("表", "台账", "预算", "金额", "字段", "行", "row", "table", "ledger", "sql"),
}
_RELATION_MARKERS = {
    "depends_on": ("依赖", "前置", "先修", "depends", "requires", "prerequisite"),
    "supersedes": ("替代", "取代", "废止", "supersedes", "replaces"),
    "contradicts": ("冲突", "矛盾", "不一致", "contradicts", "conflicts"),
    "caused_by": ("导致", "原因", "因为什么", "caused", "because"),
    "implemented_by": ("实现", "落地", "implemented by"),
    "part_of": ("属于", "组成", "包含于", "part of"),
}
_CURRENT_MARKERS = (
    "当前",
    "目前",
    "最新",
    "现行",
    "现在",
    "今天",
    "current",
    "currently",
    "latest",
    "today",
    "as of now",
)
_JURISDICTIONS = (
    "中国大陆",
    "中国",
    "香港",
    "澳门",
    "台湾",
    "北京",
    "上海",
    "深圳",
    "广州",
    "欧盟",
    "美国",
    "英国",
    "日本",
    "新加坡",
    "mainland china",
    "hong kong",
    "macau",
    "taiwan",
    "european union",
    "eu",
    "united states",
    "usa",
    "uk",
    "japan",
    "singapore",
)


def _first_matching_intent(query: str) -> str:
    lowered = query.casefold()
    for intent in (
        "structural_lookup",
        "exact_lookup",
        "comparison",
        "relationship",
        "procedure",
        "definition",
        "aggregation",
        "ledger_filter",
    ):
        if any(marker in lowered for marker in _INTENT_MARKERS[intent]):
            return intent
    return "fact"


def _audiences(query: str) -> list[str]:
    patterns = (
        r"(?:对于|面向|适用于|适用对象(?:是|为)?)[：:\s]*([^，。；;？?]{2,30})",
        r"(?:for|applies to)\s+([a-z][a-z0-9 _-]{1,40})",
    )
    values: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            value = re.split(r"(?:的|时|情况下|，|,|\?|？)", match.group(1), maxsplit=1)[0].strip()
            if value and value not in values:
                values.append(value)
    return values


def _conditions(query: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(
        r"(?:如果|当|在|若|unless|if|when)\s*([^，。；;？?]{2,50})",
        query,
        re.IGNORECASE,
    ):
        value = match.group(1).strip()
        if value and value not in values:
            values.append(value)
    return values


def _numeric_constraints(query: str) -> list[dict[str, str]]:
    constraints: list[dict[str, str]] = []
    for operator, value, unit in re.findall(
        r"(不少于|不低于|至少|超过|大于|小于|不超过|至多|>=|<=|>|<)\s*"
        r"(\d+(?:\.\d+)?)\s*([%％万千百元天年月小时分钟A-Za-z]*)",
        query,
    ):
        constraints.append({"operator": operator, "value": value, "unit": unit})
    return constraints


def _required_evidence(intent: str) -> list[str]:
    return {
        "structural_lookup": ["requested page or section", "verbatim local evidence"],
        "exact_lookup": ["exact requested field", "verbatim source evidence"],
        "comparison": ["comparison side A", "comparison side B", "comparison dimensions"],
        "relationship": ["source entity", "target entity", "typed relationship or path"],
        "procedure": ["preconditions", "ordered steps", "exceptions or failure handling"],
        "definition": ["definition", "scope or boundary"],
        "aggregation": ["matching records", "aggregation field", "calculation result"],
        "ledger_filter": ["matching records", "filter fields"],
        "temporal_current": ["active rule", "audience and jurisdiction", "upcoming replacement"],
        "temporal_as_of": ["rule active at requested time", "audience and jurisdiction"],
    }.get(intent, ["direct supporting fact"])


def understand_query(query: str) -> dict[str, Any]:
    """Parse stable retrieval constraints without making an LLM call."""
    try:
        from query_temporal import query_time_context
    except ImportError:
        from .query_temporal import query_time_context

    lowered = query.casefold()
    temporal = query_time_context(query)
    intent = _first_matching_intent(query)
    if temporal.get("mode") == "current" or any(marker in lowered for marker in _CURRENT_MARKERS):
        intent = "temporal_current"
    elif temporal.get("requested"):
        intent = "temporal_as_of"

    jurisdictions = [value for value in _JURISDICTIONS if value.casefold() in lowered]
    relation_types = [
        relation
        for relation, markers in _RELATION_MARKERS.items()
        if any(marker in lowered for marker in markers)
    ]
    output_format = "markdown"
    if any(marker in lowered for marker in ("表格", "对照表", "table")):
        output_format = "table"
    elif any(marker in lowered for marker in ("时间线", "timeline")):
        output_format = "timeline"

    page_numbers = {
        int(value)
        for value in re.findall(
            r"(?:page|页|第|cover page)\s*[-(]?\s*(\d{1,4})",
            query,
            re.IGNORECASE,
        )
    }
    if "second cover" in lowered or "第二封面" in query:
        page_numbers.add(2)
    elif "cover page" in lowered or "封面" in query:
        page_numbers.add(1)
    field_markers = {
        "email": ("email", "e-mail", "邮箱", "邮件地址"),
        "url": ("url", "web link", "website", "网址", "链接"),
        "phone": ("phone", "fax", "telephone", "电话", "传真"),
        "date": ("date", "日期", "年月日"),
        "percentage": ("percentage", "proportion", "percent", "比例", "百分比"),
        "money": ("amount", "expense", "spend", "how much", "金额", "多少"),
    }
    field_types = [
        field_type
        for field_type, markers in field_markers.items()
        if any(marker in lowered for marker in markers)
    ]
    structural_terms = [
        f"{kind.casefold()} {number}"
        for kind, number in re.findall(
            r"\b(unit|section)\s*[-:]?\s*(\d{1,4})\b",
            query,
            re.IGNORECASE,
        )
    ]

    return {
        "intent": intent,
        "temporal_mode": temporal.get("mode", "unspecified"),
        "temporal_context": temporal,
        "jurisdictions": jurisdictions,
        "audiences": _audiences(query),
        "conditions": _conditions(query),
        "numeric_constraints": _numeric_constraints(query),
        "aggregation_requested": any(
            marker in lowered for marker in ("how many", "多少", "总计", "合计", "count", "sum")
        ),
        "relation_types": relation_types,
        "required_evidence": _required_evidence(intent),
        "page_numbers": sorted(page_numbers),
        "field_types": field_types,
        "structural_terms": structural_terms,
        "raw_evidence_preferred": intent in {"exact_lookup", "structural_lookup"},
        "output_format": output_format,
        "keywords": [token for token in re.split(r"\s+", query.strip()) if token],
    }
