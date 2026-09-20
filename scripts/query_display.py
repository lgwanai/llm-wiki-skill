"""Readable query evidence and exact-subject matching for CLI consumers."""

from __future__ import annotations

import re
from pathlib import Path

from okf import read_markdown


def query_subject(query: str) -> str:
    """Strip definition-question framing without reducing a question to substrings."""
    text = query.strip().strip("？?。.!！").strip()
    text = re.sub(r"^(?:请问|请解释一下|请解释)\s*", "", text)
    text = re.sub(r"^(?:什么是|何为)\s*", "", text)
    text = re.sub(r"\s*(?:是什么|的定义是什么|的定义)$", "", text)
    text = re.sub(r"^(?:what\s+(?:is|are)|define)\s+(?:(?:a|an|the)\s+)?", "", text, flags=re.I)
    return text.strip().casefold()


def page_metadata(path: str) -> dict:
    try:
        if not path or not Path(path).is_file():
            return {}
        metadata, _, _ = read_markdown(Path(path))
        return metadata
    except (OSError, UnicodeError, ValueError):
        return {}


def exact_subject_match(query: str, path: str) -> bool:
    metadata = page_metadata(path)
    names = [metadata.get("title"), metadata.get("name")]
    aliases = metadata.get("aliases", [])
    names.extend(aliases if isinstance(aliases, list) else [aliases])
    if not any(names) and path:
        names.append(Path(path).stem)
    subject = query_subject(query)
    return bool(subject) and any(
        isinstance(name, str) and name.strip().casefold() == subject for name in names
    )


def plain_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"</?[A-Za-z][A-Za-z0-9]*(?:\s+[^<>]*)?/?>", "", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)([*_])(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def read_snippet(path: str, query: str, max_len: int = 220) -> str:
    """Return actual description/prose/table values, never Markdown scaffolding."""
    if not path or not Path(path).is_file():
        return ""
    try:
        metadata, body, _ = read_markdown(Path(path))
        candidates: list[tuple[str, float]] = []
        description = metadata.get("description") or metadata.get("summary")
        if isinstance(description, str) and description.strip():
            candidates.append((plain_text(description), 1.5))
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        body = re.sub(r"^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1[^\n]*$", "", body, flags=re.M | re.S)
        skip_section = False
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("#"):
                heading = line.lstrip("#").strip().casefold()
                skip_section = heading in {
                    "可回答的问题",
                    "关联关系",
                    "关系",
                    "来源追溯",
                    "questions",
                    "relationships",
                    "references",
                }
                continue
            if skip_section or not line or re.fullmatch(r"[\s|:\-–—=_*]+", line):
                continue
            if line.startswith("|"):
                cells = [plain_text(cell) for cell in line.strip("|").split("|")]
                if cells in [["属性", "值"], ["Property", "Value"]]:
                    continue
                line = "：".join(cell for cell in cells if cell)
            line = re.sub(r"^(?:>\s*|[-*+]\s+|\d+[.)]\s+)", "", line)
            text = plain_text(line)
            if len(text) >= 8:
                candidates.append((text, 0.0))
        if not candidates:
            return ""
        from search import _tokenize

        stop = {"什么", "怎么", "如何", "是", "的", "what", "is", "are", "the", "a", "an"}
        terms = {
            term.casefold()
            for term in _tokenize(query)
            if len(term) >= 2 and term.casefold() not in stop
        }
        subject = query_subject(query)

        def relevance(candidate: tuple[str, float]) -> float:
            text, prior = candidate
            lower = text.casefold()
            return (
                prior
                + sum(term in lower for term in terms)
                + (2 if subject and subject in lower else 0)
            )

        text = max(candidates, key=relevance)[0]
        return text[:max_len].rstrip() + ("…" if len(text) > max_len else "")
    except (OSError, UnicodeError, ValueError):
        return ""


def source_detail(page: dict, query: str) -> dict:
    path = str(page.get("path") or "")
    metadata = page_metadata(path)
    identifier = page.get("id", "unknown")
    title = metadata.get("title") or metadata.get("name") or page.get("name") or identifier
    return {
        "id": identifier,
        "name": str(title),
        "title": str(title),
        "path": path,
        "page_type": str(metadata.get("type") or page.get("type") or "unknown"),
        "description": str(metadata.get("description") or metadata.get("summary") or ""),
        "snippet": read_snippet(path, query),
        "provenance": metadata.get("provenance") or metadata.get("source") or "",
        "resource": metadata.get("resource") or "",
        "relevance": page.get("score", 0),
        "retrieval_hop": page.get("retrieval_hop", 1),
        "matched_section": page.get("matched_section", ""),
        "temporal": page.get("temporal", {}),
        "matched_claim": page.get("matched_claim", {}),
        "claim_hits": page.get("claim_hits", []),
        "source_authority": page.get("source_authority", 0.6),
        "applicability_reasons": page.get("applicability_reasons", []),
        "images": page.get("images", []),
    }
