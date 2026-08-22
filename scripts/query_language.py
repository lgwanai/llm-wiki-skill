"""No-model cross-language query bridge for compiled OKF knowledge.

The bridge prefers vocabulary already curated in page titles, aliases, tags,
keywords, and questions. A small domain-neutral fallback glossary handles
common operational and education terms, and users can extend it through
``.wiki/query_lexicon.yaml`` without changing retrieval code.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_BUILTIN_PAIRS: dict[str, tuple[str, ...]] = {
    "事故恢复": ("incident recovery",),
    "故障恢复": ("incident recovery", "failure recovery"),
    "事故处理": ("incident response",),
    "重试退避": ("retry backoff",),
    "重试": ("retry",),
    "水位标记": ("watermark", "recovery marker"),
    "水位线": ("watermark",),
    "恢复标记": ("recovery marker",),
    "运行手册": ("runbook",),
    "操作手册": ("runbook",),
    "应急手册": ("incident runbook",),
    "接口限流": ("API rate limit",),
    "接口限额": ("API rate limit",),
    "证据保留": ("evidence retention",),
    "审计日志": ("audit log",),
    "引用": ("citation",),
    "出处": ("citation", "source reference"),
    "灰度发布": ("canary release", "staged rollout"),
    "回滚审批": ("rollback approval",),
    "知识点": ("knowledge point",),
    "前置知识": ("prerequisite",),
    "先修知识": ("prerequisite",),
    "同类题": ("similar question",),
    "试题": ("exam question",),
    "题目": ("question",),
    "易错点": ("common mistake",),
    "密度": ("density",),
    "质量": ("mass",),
    "体积": ("volume",),
}

_QUESTION_FILLERS = (
    "请给出",
    "请说明",
    "请解释",
    "给出",
    "说明",
    "解释",
    "请问",
    "什么是",
    "是什么",
    "如何",
    "哪些",
    "哪个",
    "分别",
    "然后",
    "并且",
    "以及",
)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _contains_latin(text: str) -> bool:
    return bool(re.search(r"[a-zA-Z]", text))


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _page_vocabulary(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    metadata: dict[str, Any] = {}
    if raw.startswith("---"):
        match = re.match(r"^---\s*\n(.*?)\n---", raw, flags=re.DOTALL)
        if match:
            try:
                parsed = yaml.safe_load(match.group(1)) or {}
                if isinstance(parsed, dict):
                    metadata = parsed
            except yaml.YAMLError:
                pass
    heading = re.search(r"^#\s+(.+)$", raw, flags=re.MULTILINE)
    values: list[str] = []
    for key in ("title", "name", "aliases", "keywords", "tags", "questions"):
        values.extend(_as_strings(metadata.get(key)))
    if heading:
        values.append(heading.group(1).strip())
    return list(dict.fromkeys(value for value in values if len(value) >= 2))


def _custom_pairs(glossary_path: Path) -> dict[str, list[str]]:
    if not glossary_path.is_file():
        return {}
    try:
        payload = yaml.safe_load(glossary_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("terms"), dict):
        payload = payload["terms"]
    if not isinstance(payload, dict):
        return {}
    return {
        str(source).strip(): _as_strings(targets)
        for source, targets in payload.items()
        if str(source).strip() and _as_strings(targets)
    }


@lru_cache(maxsize=8)
def _language_pairs(pages_dir_text: str, glossary_path_text: str) -> dict[str, tuple[str, ...]]:
    pages_dir = Path(pages_dir_text)
    forward: dict[str, list[str]] = {
        source: list(targets) for source, targets in _BUILTIN_PAIRS.items()
    }

    for path in sorted(pages_dir.rglob("*.md")) if pages_dir.is_dir() else []:
        vocabulary = _page_vocabulary(path)
        cjk_values = [value for value in vocabulary if _contains_cjk(value)]
        latin_values = [
            value for value in vocabulary if _contains_latin(value) and not _contains_cjk(value)
        ]
        if not cjk_values or not latin_values:
            continue
        preferred_latin = latin_values[0]
        preferred_cjk = cjk_values[0]
        for value in cjk_values:
            forward.setdefault(value, []).append(preferred_latin)
        for value in latin_values:
            forward.setdefault(value, []).append(preferred_cjk)

    for source, targets in _custom_pairs(Path(glossary_path_text)).items():
        forward.setdefault(source, []).extend(targets)

    # Built-in pairs are bidirectional too, but learned/custom mappings take
    # precedence through insertion order and phrase-length matching.
    for source, targets in list(forward.items()):
        for target in targets:
            forward.setdefault(target, []).append(source)
    return {source: tuple(dict.fromkeys(targets)) for source, targets in forward.items() if targets}


def _keyword_variant(query: str, matches: list[tuple[str, str]]) -> str:
    translated = query
    targets: list[str] = []
    for source, target in matches:
        translated = re.sub(re.escape(source), f" {target} ", translated, flags=re.IGNORECASE)
        targets.append(target)
    for filler in _QUESTION_FILLERS:
        translated = translated.replace(filler, " ")
    remaining_ascii = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", translated)
    translated_tokens = [
        token for target in targets for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", target)
    ]
    ordered = list(dict.fromkeys(translated_tokens + remaining_ascii))
    return " ".join(ordered).strip()


def cross_language_variants(
    query: str,
    pages_dir: str | Path,
    glossary_path: str | Path | None = None,
    limit: int = 3,
) -> list[str]:
    """Return controlled cross-language keyword variants for one query."""
    wiki_dir = Path(pages_dir).parent
    glossary = Path(glossary_path) if glossary_path else wiki_dir / "query_lexicon.yaml"
    pairs = _language_pairs(str(Path(pages_dir).resolve()), str(glossary.resolve()))
    matches: list[tuple[str, str]] = []
    for source in sorted(pairs, key=len, reverse=True):
        if not re.search(re.escape(source), query, flags=re.IGNORECASE):
            continue
        target = next(
            (
                candidate
                for candidate in pairs[source]
                if _contains_cjk(candidate) != _contains_cjk(source)
            ),
            "",
        )
        if target:
            matches.append((source, target))
    if not matches:
        return []

    # Do not translate a shorter phrase inside a longer phrase already used.
    selected: list[tuple[str, str]] = []
    occupied_sources: list[str] = []
    for source, target in matches:
        if any(source in longer for longer in occupied_sources):
            continue
        selected.append((source, target))
        occupied_sources.append(source)

    replaced = query
    for source, target in selected:
        replaced = re.sub(re.escape(source), target, replaced, flags=re.IGNORECASE)
    variants = [re.sub(r"\s+", " ", replaced).strip(), _keyword_variant(query, selected)]
    return list(dict.fromkeys(variant for variant in variants if variant and variant != query))[
        :limit
    ]
