#!/usr/bin/env python3
"""Open Knowledge Format (OKF v0.1) validation and interchange."""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from config import get_wiki_dir

RESERVED = {"index.md", "log.md"}
OKF_FIELDS = {"type", "title", "description", "resource", "tags", "timestamp"}


def read_markdown(path: Path) -> tuple[dict, str, str | None]:
    """Return frontmatter, body, and a parse error if present."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, "", str(exc)
    if not text.startswith("---\n"):
        return {}, text, "missing YAML frontmatter"
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text, "unclosed YAML frontmatter"
    try:
        metadata = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        return {}, text, f"invalid YAML: {exc}"
    if not isinstance(metadata, dict):
        return {}, text, "frontmatter must be a mapping"
    return metadata, text[end + 5 :], None


def validate_bundle(bundle: str | Path) -> dict:
    """Validate the normative OKF v0.1 conformance requirements."""
    root = Path(bundle).resolve()
    errors: list[dict] = []
    warnings: list[dict] = []
    concepts = 0
    if not root.is_dir():
        return {
            "valid": False,
            "concepts": 0,
            "errors": [{"path": str(root), "message": "bundle is not a directory"}],
            "warnings": [],
        }

    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if path.name in RESERVED:
            if path.name == "log.md":
                text = path.read_text(encoding="utf-8")
                for heading in re.findall(r"^##\s+(.+)$", text, re.MULTILINE):
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading.strip()):
                        warnings.append(
                            {"path": rel, "message": f"non-ISO log date heading: {heading}"}
                        )
            continue
        concepts += 1
        metadata, _, error = read_markdown(path)
        if error:
            errors.append({"path": rel, "message": error})
        elif not str(metadata.get("type", "")).strip():
            errors.append({"path": rel, "message": "required field 'type' is empty"})

    return {"valid": not errors, "concepts": concepts, "errors": errors, "warnings": warnings}


def _write_page(path: Path, metadata: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{frontmatter}\n---\n{body.lstrip()}", encoding="utf-8")


def import_bundle(bundle: str | Path, force: bool = False) -> dict:
    """Import an OKF bundle losslessly into the searchable wiki OKF namespace."""
    root = Path(bundle).resolve()
    report = validate_bundle(root)
    if not report["valid"]:
        return {**report, "imported": 0, "destination": None}
    destination = get_wiki_dir() / "pages" / "okf"
    imported = 0
    skipped = 0
    for source in sorted(root.rglob("*.md")):
        rel = source.relative_to(root)
        target = destination / rel
        if source.name in RESERVED:
            target.parent.mkdir(parents=True, exist_ok=True)
            if force or not target.exists():
                shutil.copy2(source, target)
            continue
        metadata, body, _ = read_markdown(source)
        concept_id = rel.with_suffix("").as_posix()
        wiki_meta = dict(metadata)  # preserve all producer-defined extensions
        wiki_meta.update(
            {
                "id": concept_id,
                "name": metadata.get("title") or rel.stem,
                "summary": metadata.get("description", ""),
                "keywords": metadata.get("tags", []),
                "source": metadata.get("resource") or f"okf:{root.name}",
                "okf_concept_id": concept_id,
                "okf_version": "0.1",
            }
        )
        if target.exists() and not force:
            skipped += 1
            continue
        _write_page(target, wiki_meta, body)
        imported += 1
    return {**report, "imported": imported, "skipped": skipped, "destination": str(destination)}


def _is_uri(value: object) -> bool:
    return isinstance(value, str) and urlparse(value).scheme in {
        "http",
        "https",
        "gs",
        "s3",
        "file",
    }


def _description(metadata: dict, body: str) -> str:
    value = metadata.get("summary") or metadata.get("description")
    if value:
        return str(value).strip().splitlines()[0]
    prose = re.sub(r"[#>*_`|\[\]()]", " ", body)
    prose = re.sub(r"\s+", " ", prose).strip()
    return prose[:240]


def export_bundle(destination: str | Path, force: bool = False) -> dict:
    """Export wiki pages as an OKF v0.1 knowledge bundle."""
    root = Path(destination).resolve()
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"destination is not empty: {root}; use --force")
    root.mkdir(parents=True, exist_ok=True)
    pages_root = get_wiki_dir() / "pages"
    exported: list[tuple[Path, dict]] = []
    for source in sorted(pages_root.rglob("*.md")):
        if source.name in RESERVED or "sessions" in source.parts:
            continue
        metadata, body, error = read_markdown(source)
        if error:
            continue
        rel = source.relative_to(pages_root)
        okf_meta = {
            key: value
            for key, value in metadata.items()
            if key
            not in {
                "id",
                "name",
                "summary",
                "keywords",
                "created_at",
                "published_at",
                "confidence",
                "source",
                "aliases",
                "questions",
                "facts",
            }
        }
        okf_meta["type"] = str(metadata.get("type") or "Reference")
        okf_meta["title"] = metadata.get("name") or metadata.get("title") or source.stem
        description = _description(metadata, body)
        if description:
            okf_meta["description"] = description
        source_value = metadata.get("resource") or metadata.get("source")
        if _is_uri(source_value):
            okf_meta["resource"] = source_value
        tags = metadata.get("tags") or metadata.get("keywords")
        if tags:
            okf_meta["tags"] = tags if isinstance(tags, list) else [str(tags)]
        stamp = (
            metadata.get("timestamp") or metadata.get("published_at") or metadata.get("created_at")
        )
        if stamp:
            okf_meta["timestamp"] = stamp
        target = root / rel
        _write_page(target, okf_meta, body)
        exported.append((rel, okf_meta))

    groups: dict[str, list[tuple[Path, dict]]] = {}
    for rel, metadata in exported:
        groups.setdefault(rel.parent.as_posix(), []).append((rel, metadata))
    for directory, items in groups.items():
        index = root / ("" if directory == "." else directory) / "index.md"
        lines = [
            f"# {Path(directory).name.title() if directory != '.' else 'Knowledge Bundle'}",
            "",
        ]
        for rel, metadata in items:
            lines.append(
                f"* [{metadata['title']}]({rel.name}) - {metadata.get('description', '')}".rstrip()
            )
        index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "log.md").write_text(
        "# Bundle Update Log\n\n"
        f"## {datetime.now(timezone.utc):%Y-%m-%d}\n"
        "* **Export**: Generated from LLM Wiki.\n",
        encoding="utf-8",
    )
    report = validate_bundle(root)
    return {**report, "exported": len(exported), "destination": str(root)}


def main() -> None:
    parser = argparse.ArgumentParser(description="OKF v0.1 interoperability")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("bundle")
    imp = sub.add_parser("import")
    imp.add_argument("bundle")
    imp.add_argument("--force", action="store_true")
    exp = sub.add_parser("export")
    exp.add_argument("destination")
    exp.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "validate":
        result = validate_bundle(args.bundle)
    elif args.command == "import":
        result = import_bundle(args.bundle, args.force)
    else:
        result = export_bundle(args.destination, args.force)
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).strip())
    if not result.get("valid", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
