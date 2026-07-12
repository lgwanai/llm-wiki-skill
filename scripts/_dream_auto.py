#!/usr/bin/env python3
"""Merge/enrich helpers for dream auto-execution.

Extracted from dream.py to keep the core engine under 800 lines.
Mechanical operations for enrichment; LLM-based semantic fusion for merges
(since mechanical paragraph dedup fails when different sources describe
the same concept with different wording).
"""

from __future__ import annotations

import json
import re
import sys
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
    """Locate a native OKF concept by Concept ID or unique stem."""
    from okf import find_concept

    return find_concept(pages_dir, page_id)


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


# ── semantic merge ────────────────────────────────────────────────────────────

from _llm_utils import llm_fuse_pages


def _mechanical_fallback_merge(
    surv_body: str, dup_body: str, dup_id: str
) -> str | None:
    """Mechanical paragraph-level dedup fallback when LLM fusion is unavailable.

    Returns merged body with new paragraphs appended, or None if nothing new.
    """
    surv_paragraphs = set(extract_paragraphs(surv_body))
    new_paragraphs = [
        p for p in extract_paragraphs(dup_body)
        if p not in surv_paragraphs
    ]
    if not new_paragraphs:
        return None
    merged = surv_body.rstrip() + "\n\n"
    merged += (
        f"<!-- merged from [[{dup_id}]] by dream auto-merge (mechanical) -->\n\n"

    )
    merged += "\n\n".join(new_paragraphs)
    return merged


# ── auto-execute ──────────────────────────────────────────────────────────────

def auto_merge_duplicates(
    duplicate_groups: list[dict],
    wiki_dir: Path,
) -> tuple[int, int, list[Path]]:
    """Merge duplicate pages — LLM semantic fusion with mechanical fallback.

    For each duplicate pair:
    1. Read both pages
    2. LLM-based semantic fusion (dedup overlapping info, preserve unique facts)
    3. Falls back to mechanical paragraph dedup if LLM is unavailable
    4. Add redirect frontmatter to duplicate
    5. Update edges.json to point to the surviving page

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

            # ── LLM semantic fusion (primary) ──
            fused_body = llm_fuse_pages(
                surv_body, dup_body, dup_id, dup_of_id,
            )
            if fused_body is not None:
                _write_page(survivor_path, surv_fm, fused_body)
                modified.append(survivor_path)
                print(
                    f"  Fused: [[{dup_id}]] → [[{dup_of_id}]] "
                    f"(LLM semantic merge, {len(fused_body)} chars)",
                    file=sys.stderr,
                )
            else:
                # ── Mechanical fallback ──
                merged_body = _mechanical_fallback_merge(
                    surv_body, dup_body, dup_id,
                )
                if merged_body is not None:
                    _write_page(survivor_path, surv_fm, merged_body)
                    modified.append(survivor_path)
                    print(
                        f"  Merged: [[{dup_id}]] → [[{dup_of_id}]] "
                        f"(mechanical fallback)",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"  Skipped: [[{dup_id}]] → [[{dup_of_id}]] "
                        f"(no new content)",
                        file=sys.stderr,
                    )

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
    2. Extract additional OKF tags from page body

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
        existing_keywords = set(as_list(frontmatter.get("tags", [])))
        body_terms = extract_key_terms(body)
        new_keywords = body_terms - existing_keywords
        if new_keywords:
            all_keywords = list(existing_keywords) + list(new_keywords)
            frontmatter["tags"] = all_keywords[:24]
        _write_page(path, frontmatter, body)
        modified.append(path)
        enriched += 1

    return enriched, modified
