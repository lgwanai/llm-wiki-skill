#!/usr/bin/env python3
"""Mechanical merge/enrich helpers for dream auto-execution.

Extracted from dream.py to keep the core engine under 800 lines.
All operations are mechanical — no LLM calls required.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_page(path: Path) -> tuple[dict, str] | None:
    """Return (frontmatter_dict, body_text) or None."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, flags=re.DOTALL)
    if not match:
        return None
    import yaml
    fm = yaml.safe_load(match.group(1)) or {}
    return (fm if isinstance(fm, dict) else {}, match.group(2))


def _write_page(path: Path, frontmatter: dict, body: str) -> None:
    import yaml
    content = (
        "---\n"
        + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + body.lstrip()
    )
    path.write_text(content, encoding="utf-8")


# ── page helpers ──────────────────────────────────────────────────────────────

def find_page_path(page_id: str, pages_dir: Path) -> Path | None:
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


def extract_paragraphs(body: str) -> list[str]:
    """Split body into non-empty paragraphs."""
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def extract_key_terms(body: str) -> set[str]:
    """Extract Chinese (2-8 chars) and English (4+ chars) terms for keywords."""
    cn_terms = set(re.findall(r"[一-鿿]{2,8}", body))
    en_terms = {
        w.lower() for w in re.findall(r"[a-zA-Z]{3,}", body)
        if len(w) >= 4
    }
    return cn_terms | en_terms


def as_list(value) -> list:
    """Normalise a value to a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def update_edges_redirect(edges_file: Path, from_id: str, to_id: str) -> None:
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


# ── auto-execute ──────────────────────────────────────────────────────────────

def auto_merge_duplicates(
    duplicate_groups: list[dict],
    wiki_dir: Path,
) -> tuple[int, int, list[Path]]:
    """Mechanically merge duplicate pages. No LLM required.

    For each duplicate pair:
    1. Read both pages
    2. Merge non-overlapping content (preserving original paragraph order)
    3. Add redirect frontmatter to duplicate
    4. Update edges.json to point to the surviving page

    Returns (merged_count, removed_count, modified_paths).
    """
    merged = 0
    removed = 0
    modified: list[Path] = []
    pages_dir = wiki_dir / "pages"
    edges_file = wiki_dir / "graph" / "edges.json"

    for group in duplicate_groups:
        dups = group.get("duplicates", [])
        if len(dups) < 2:
            continue
        for dup in dups:
            dup_id = dup.get("id", "")
            dup_of_id = dup.get("duplicate_of", "")
            if not dup_id or not dup_of_id:
                continue
            dup_path = find_page_path(dup_id, pages_dir)
            survivor_path = find_page_path(dup_of_id, pages_dir)
            if not dup_path or not survivor_path:
                continue
            dup_page = _read_page(dup_path)
            survivor_page = _read_page(survivor_path)
            if not dup_page or not survivor_page:
                continue
            dup_fm, dup_body = dup_page
            surv_fm, surv_body = survivor_page
            surv_paragraphs = set(extract_paragraphs(surv_body))
            new_paragraphs = [
                p for p in extract_paragraphs(dup_body)
                if p not in surv_paragraphs
            ]
            if new_paragraphs:
                merged_body = surv_body.rstrip() + "\n\n"
                merged_body += (
                    "<!-- merged from [[{}]] by dream auto-merge -->\n\n"
                    .format(dup_id)
                )
                merged_body += "\n\n".join(new_paragraphs)
                _write_page(survivor_path, surv_fm, merged_body)
                modified.append(survivor_path)
            dup_fm["redirect"] = dup_of_id
            dup_fm["status"] = "redirect"
            dup_fm["dream_merged_date"] = _now()
            _write_page(dup_path, dup_fm, dup_body)
            modified.append(dup_path)
            update_edges_redirect(edges_file, dup_id, dup_of_id)
            merged += 1
            removed += 1

    return merged, removed, modified


def auto_enrich_pages(
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
        frontmatter["dream_enrich"] = True
        frontmatter["dream_enrich_date"] = _now()
        existing_keywords = set(as_list(frontmatter.get("keywords", [])))
        body_terms = extract_key_terms(body)
        new_keywords = body_terms - existing_keywords
        if new_keywords:
            all_keywords = list(existing_keywords) + list(new_keywords)
            frontmatter["keywords"] = all_keywords[:24]
        name = candidate.get("name", "")
        aliases = set(as_list(frontmatter.get("aliases", [])))
        if name and name not in aliases:
            aliases.add(name)
            frontmatter["aliases"] = sorted(aliases)
        _write_page(path, frontmatter, body)
        modified.append(path)
        enriched += 1

    return enriched, modified
