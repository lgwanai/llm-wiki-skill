#!/usr/bin/env python3
"""Open Knowledge Format (OKF v0.1) validation and interchange."""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml
from config import get_wiki_dir

RESERVED = {"index.md", "log.md"}
OKF_FIELDS = {"type", "title", "description", "resource", "tags", "timestamp"}


def concept_id(path: str | Path, bundle_root: str | Path) -> str:
    """Return the OKF Concept ID derived from a bundle-relative path."""
    return Path(path).resolve().relative_to(Path(bundle_root).resolve()).with_suffix("").as_posix()


def iter_concepts(bundle_root: str | Path) -> list[Path]:
    """Return every OKF concept document, excluding reserved files."""
    root = Path(bundle_root)
    if not root.is_dir():
        return []
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if path.name not in RESERVED
    ]


def find_concept(bundle_root: str | Path, identifier: str) -> Path | None:
    """Resolve an OKF Concept ID, bundle link, or unique filename stem."""
    root = Path(bundle_root)
    normalized = identifier.strip().split("#", 1)[0].lstrip("/")
    if normalized.endswith(".md"):
        normalized = normalized[:-3]
    direct = root / f"{normalized}.md"
    if direct.is_file():
        return direct
    matches = [path for path in iter_concepts(root) if path.stem == Path(normalized).name]
    return matches[0] if len(matches) == 1 else None


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
    """Merge an external OKF bundle into the native wiki OKF bundle."""
    root = Path(bundle).resolve()
    report = validate_bundle(root)
    if not report["valid"]:
        return {**report, "imported": 0, "destination": None}
    destination = get_wiki_dir() / "pages"
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
        if target.exists() and not force:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        imported += 1
    return {**report, "imported": imported, "skipped": skipped, "destination": str(destination)}


def export_bundle(destination: str | Path, force: bool = False) -> dict:
    """Copy the native OKF bundle for distribution without conversion."""
    root = Path(destination).resolve()
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"destination is not empty: {root}; use --force")
    root.mkdir(parents=True, exist_ok=True)
    pages_root = get_wiki_dir() / "pages"
    source_report = validate_bundle(pages_root)
    if not source_report["valid"]:
        return {**source_report, "exported": 0, "destination": str(root)}
    shutil.copytree(pages_root, root, dirs_exist_ok=True)
    report = validate_bundle(root)
    return {**report, "exported": len(iter_concepts(root)), "destination": str(root)}


def migrate_native_bundle(bundle: str | Path | None = None) -> dict:
    """Rewrite legacy wiki metadata in place as native OKF v0.1 concepts."""
    root = Path(bundle) if bundle else get_wiki_dir() / "pages"
    backup = root.parent / "backup" / f"pre-okf-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    if root.exists():
        shutil.copytree(root, backup)
    else:
        backup.mkdir(parents=True, exist_ok=True)
    legacy_log = root.parent / "log.md"
    if legacy_log.exists():
        shutil.copy2(legacy_log, backup / "legacy-log.md")
    root.mkdir(parents=True, exist_ok=True)
    migrated = 0
    skipped = 0
    for path in iter_concepts(root):
        metadata, body, error = read_markdown(path)
        if error:
            skipped += 1
            continue
        if metadata.get("title") and not any(
            key in metadata
            for key in ("id", "name", "summary", "keywords", "created_at", "published_at")
        ):
            continue
        okf_meta = {
            "type": str(metadata.get("type") or "Reference"),
            "title": metadata.get("title") or metadata.get("name") or path.stem,
        }
        description = metadata.get("description") or metadata.get("summary")
        if description:
            okf_meta["description"] = description
        resource = metadata.get("resource")
        if resource:
            okf_meta["resource"] = resource
        tags = metadata.get("tags") or metadata.get("keywords")
        if tags:
            okf_meta["tags"] = tags
        timestamp = (
            metadata.get("timestamp")
            or metadata.get("published_at")
            or metadata.get("created_at")
        )
        if timestamp:
            okf_meta["timestamp"] = timestamp
        provenance = metadata.get("provenance") or metadata.get("source")
        if provenance:
            okf_meta["provenance"] = provenance
        body = re.sub(
            r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
            lambda match: (
                f"[{match.group(2) or match.group(1)}]"
                f"(/{concept_id(find_concept(root, match.group(1)), root)}.md)"
                if find_concept(root, match.group(1))
                else f"[{match.group(2) or match.group(1)}]"
                f"(/concepts/{Path(match.group(1)).name}.md)"
            ),
            body,
        )
        _write_page(path, okf_meta, body)
        migrated += 1

    bundle_log = root / "log.md"
    if legacy_log.exists() and not bundle_log.exists():
        shutil.move(str(legacy_log), str(bundle_log))
    if bundle_log.exists():
        log_text = bundle_log.read_text(encoding="utf-8")
        log_text = re.sub(
            r"^## \[(\d{4}-\d{2}-\d{2})[^\]]*\]\s*(.*)$",
            lambda match: (
                f"## {match.group(1)}\n* **Update**: "
                f"{match.group(2).strip() or 'Legacy wiki update.'}"
            ),
            log_text,
            flags=re.MULTILINE,
        )
        bundle_log.write_text(log_text, encoding="utf-8")
    index = root / "index.md"
    if not index.exists():
        index.write_text(
            '---\nokf_version: "0.1"\n---\n# Wiki Index\n\n'
            "This directory is the canonical OKF knowledge bundle.\n",
            encoding="utf-8",
        )
    return {
        **validate_bundle(root),
        "migrated": migrated,
        "skipped": skipped,
        "backup": str(backup),
    }


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
    migrate = sub.add_parser("migrate")
    migrate.add_argument("bundle", nargs="?", default=None)
    args = parser.parse_args()
    if args.command == "validate":
        result = validate_bundle(args.bundle)
    elif args.command == "import":
        result = import_bundle(args.bundle, args.force)
    elif args.command == "export":
        result = export_bundle(args.destination, args.force)
    else:
        result = migrate_native_bundle(args.bundle)
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).strip())
    if not result.get("valid", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
