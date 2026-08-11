#!/usr/bin/env python3
"""Restore cited source images to already-compiled OKF pages.

This is a deterministic migration for pages compiled before Agent-mode media
finalization existed. It never decides which concepts need figures: it only
replays the page citations already present in each compiled page.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import compile_v2


def _candidate_pages(pages_dir: Path, source_name: str, material_id: str) -> list[Path]:
    matches: list[Path] = []
    for page in sorted(pages_dir.rglob("*.md")):
        if "assets" in page.relative_to(pages_dir).parts:
            continue
        try:
            content = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if material_id:
            matched = material_id in content
        else:
            matched = source_name in content
        if matched:
            matches.append(page)
    return matches


def backfill_source_media(
    *,
    wiki_dir: Path,
    source: Path,
    material_id: str = "",
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or apply media restoration for pages citing one source."""
    wiki_dir = wiki_dir.expanduser().resolve()
    source = source.expanduser().resolve()
    pages_dir = wiki_dir / "pages"
    if not source.is_file():
        raise FileNotFoundError(f"Source not found: {source}")
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"Wiki pages directory not found: {pages_dir}")

    compile_v2.WIKI_DIR = wiki_dir
    compile_v2.PAGES_DIR = pages_dir
    source_content, source_name = compile_v2.read_source_content(source)
    page_map = compile_v2._source_page_image_map(source_content)
    candidates = _candidate_pages(pages_dir, source_name, material_id.strip())
    records: list[dict[str, Any]] = []

    if apply:
        source_content = compile_v2._persist_source_image_references(source_content, source)
        page_map = compile_v2._source_page_image_map(source_content)

    for page in candidates:
        content = page.read_text(encoding="utf-8")
        cited_pages = compile_v2._extract_cited_pages(content)
        media_pages = set(cited_pages)
        for page_number in cited_pages:
            media_pages.update({page_number - 1, page_number + 1})
        source_image_count = sum(
            len(page_map.get(page_number, []))
            for page_number in media_pages
            if page_number > 0
        )
        if not cited_pages:
            records.append({
                "page": str(page),
                "status": "skipped_no_page_citation",
                "source_images": 0,
            })
            continue
        before = len(list(compile_v2.MARKDOWN_IMAGE_RE.finditer(content)))
        if apply:
            enriched = compile_v2._attach_source_media(content, source_content, page)
            after = len(list(compile_v2.MARKDOWN_IMAGE_RE.finditer(enriched)))
            if enriched != content:
                compile_v2.atomic_write(page, enriched)
            changed = enriched != content
            images_added = max(0, after - before)
        else:
            existing_names = {
                Path(compile_v2._clean_image_target(match.group("target"))).name
                for match in compile_v2.MARKDOWN_IMAGE_RE.finditer(content)
            }
            expected_names = {
                Path(target).name
                for page_number in media_pages
                if page_number > 0
                for _, target in page_map.get(page_number, [])
            }
            images_added = len(expected_names - existing_names)
            changed = images_added > 0
        records.append({
            "page": str(page),
            "status": ("updated" if apply else "would_update") if changed else "unchanged",
            "cited_pages": cited_pages,
            "source_images": source_image_count,
            "images_added": images_added,
        })

    return {
        "status": "applied" if apply else "preview",
        "wiki_dir": str(wiki_dir),
        "source": str(source),
        "material_id": material_id.strip(),
        "matched_pages": len(candidates),
        "updated_pages": sum(
            1 for record in records if record["status"] in {"updated", "would_update"}
        ),
        "images_added": sum(int(record.get("images_added", 0)) for record in records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore cited textbook/exam images to legacy compiled pages"
    )
    parser.add_argument("--wiki-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--material-id", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = backfill_source_media(
        wiki_dir=args.wiki_dir,
        source=args.source,
        material_id=args.material_id,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
