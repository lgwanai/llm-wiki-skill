#!/usr/bin/env python3
"""Persistent completeness worklists for source compilation.

A compile run is complete only when every immutable source task is completed,
has at least one recorded output, and still matches its recorded checksum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .source_versions import (
        active_source,
        json_bytes,
        publish_changes,
        read_json,
        strip_secrets,
    )
except ImportError:
    from source_versions import active_source, json_bytes, publish_changes, read_json, strip_secrets

VALID_STATUSES = {"pending", "in_progress", "completed", "failed", "blocked"}
TERMINAL_FAILURE_STATUSES = {"failed", "blocked"}


def utc_now() -> str:
    """Return the current UTC time as ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    """Return a stable SHA-256 checksum for text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 checksum for a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist a JSON manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _refresh_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Recalculate task counters and overall state."""
    items = manifest.get("items", [])
    counts = {status: 0 for status in VALID_STATUSES}
    for item in items:
        status = item.get("status", "pending")
        counts[status if status in counts else "pending"] += 1

    total = len(items)
    completed = counts["completed"]
    manifest["summary"] = {
        "total": total,
        "pending": counts["pending"],
        "in_progress": counts["in_progress"],
        "completed": completed,
        "failed": counts["failed"],
        "blocked": counts["blocked"],
    }
    all_completed = bool(total) and completed == total
    metadata = manifest.get("metadata", {})
    needs_verification = metadata.get("staged_pages") or metadata.get("directory_worklist")
    manifest["coverage_complete"] = all_completed and not needs_verification
    if manifest["coverage_complete"]:
        manifest["status"] = "completed"
    elif all_completed:
        manifest["status"] = "awaiting_verification"
    elif counts["failed"] or counts["blocked"]:
        manifest["status"] = "incomplete"
    elif counts["in_progress"]:
        manifest["status"] = "in_progress"
    else:
        manifest["status"] = "pending"
    manifest["updated_at"] = utc_now()
    return manifest


def create_manifest(
    path: str | Path,
    *,
    source: str,
    mode: str,
    items: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new ordered compile worklist."""
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        task = dict(item)
        task.setdefault("id", f"task-{index:04d}")
        task["order"] = index
        task.setdefault("label", task["id"])
        task.setdefault("status", "pending")
        task.setdefault("attempts", 0)
        task.setdefault("outputs", [])
        task.setdefault("notes", [])
        task.setdefault("error", "")
        normalized.append(task)

    now = utc_now()
    manifest: dict[str, Any] = {
        "version": 1,
        "source": source,
        "mode": mode,
        "created_at": now,
        "updated_at": now,
        "status": "pending",
        "coverage_complete": False,
        "metadata": metadata or {},
        "items": normalized,
    }
    _refresh_summary(manifest)
    _atomic_write_json(Path(path), manifest)
    return manifest


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a compile worklist."""
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError(f"Invalid compile todo manifest: {manifest_path}")
    return data


def _agent_output_path(wiki_pages: Path, output: str) -> Path:
    """Resolve one Agent output and keep it inside the canonical OKF pages."""
    output_path = Path(str(output))
    if not output_path.is_absolute():
        relative = str(output).lstrip("/")
        output_path = wiki_pages / (relative if relative.endswith(".md") else f"{relative}.md")
    resolved = output_path.resolve()
    try:
        resolved.relative_to(wiki_pages.resolve())
    except ValueError as exc:
        raise ValueError(f"Agent compiled output escapes wiki pages: {resolved}") from exc
    return resolved


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace a compiled Markdown page."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _finalize_agent_task_media(
    manifest: dict[str, Any],
    task: dict[str, Any],
    outputs: list[str],
) -> list[dict[str, Any]]:
    """Deterministically attach source-page images before Agent completion.

    Agent-mode compilation previously relied on prompt compliance alone.  This
    finalizer runs the same media attachment used by LLM mode and fails closed
    when an image-bearing study artifact has no page/section citation.
    """
    metadata = manifest.get("metadata", {})
    wiki_dir_value = metadata.get("wiki_dir")
    if manifest.get("mode") != "agent" or not wiki_dir_value:
        return []
    artifact_value = task.get("artifact_path")
    if not artifact_value:
        return []
    artifact_path = Path(str(artifact_value))
    if not artifact_path.is_file() or artifact_path.suffix.lower() not in {".md", ".markdown"}:
        return []

    # Lazy import avoids a module cycle during normal compile_v2 startup.
    import compile_v2

    source_content = artifact_path.read_text(encoding="utf-8")
    source_has_media = bool(
        compile_v2._source_page_image_map(source_content)
        or any(refs for _, refs in compile_v2._source_epub_section_map(source_content).values())
    )
    if not source_has_media:
        return []
    published_pages = Path(str(wiki_dir_value)) / "pages"
    wiki_pages = Path(metadata["staged_pages"]) if metadata.get("staged_pages") else published_pages
    records: list[dict[str, Any]] = []
    for output in outputs:
        output_path = _agent_output_path(wiki_pages, output)
        if not output_path.is_file():
            raise ValueError(f"Agent compiled output is missing: {output_path}")
        page_content = output_path.read_text(encoding="utf-8")
        cited_pages = compile_v2._extract_cited_pages(page_content)
        cited_sections = compile_v2._extract_cited_epub_sections(page_content)
        if (
            metadata.get("study_material") is True
            and source_has_media
            and not cited_pages
            and not cited_sections
        ):
            raise ValueError(
                f"{output_path}: image-bearing study output lacks an exact page/EPUB section "
                "citation; source images cannot be matched to the current concept"
            )
        media_path = _agent_output_path(published_pages, output)
        enriched = compile_v2._attach_source_media(page_content, source_content, media_path)
        if enriched != page_content:
            _atomic_write_text(output_path, enriched)
        image_targets = [
            compile_v2._clean_image_target(match.group("target"))
            for match in compile_v2.MARKDOWN_IMAGE_RE.finditer(enriched)
        ]
        for target in image_targets:
            local_path = compile_v2._local_image_path(target, media_path.parent)
            if local_path is not None and not local_path.is_file():
                raise ValueError(f"{output_path}: compiled image target is missing: {target}")
        visual_records, visual_errors = compile_v2.validate_compiled_visual_evidence(
            enriched,
            media_path,
            image_targets,
        )
        if visual_errors:
            raise ValueError(
                f"{output_path}: visual evidence validation failed: " + "; ".join(visual_errors)
            )
        records.append(
            {
                "output": str(output),
                "output_path": str(output_path),
                "output_sha256": sha256_file(output_path),
                "image_targets": image_targets,
                "visual_count": len(visual_records),
                "visual_ids": [
                    str(record.get("id", ""))
                    for record in visual_records
                    if str(record.get("id", "")).strip()
                ],
            }
        )
    return records


def _staged_concept_id(stage: Path, output: str) -> str:
    path = _agent_output_path(stage, output)
    relative = path.relative_to(stage.resolve())
    if relative.parts[0] == "assets" or path.name in {"index.md", "log.md"}:
        raise ValueError("A compile output must be a Concept ID")
    return relative.with_suffix("").as_posix()


def _agent_citation_error(wiki_pages: Path, output: str, task: dict) -> str | None:
    from okf import read_markdown

    page = _agent_output_path(wiki_pages, output)
    metadata, body, error = read_markdown(page)
    if (
        error
        or not str(metadata.get("type", "")).strip()
        or not (metadata.get("title") or metadata.get("name"))
        or not body.strip()
    ):
        return f"{output}: invalid staged concept: {error or 'type, title and body are required'}"
    if metadata.get("id", output) != output:
        return f"{output}: frontmatter id differs from the output Concept ID"
    citation = task["source_citation"]
    citations = metadata.get("source_citations")
    matches = (
        [
            item
            for item in citations or []
            if isinstance(item, dict) and item.get("artifact") == citation
        ]
        if isinstance(citations, list)
        else []
    )
    if not matches:
        return f"{output}: missing source_citations entry {citation}"
    if task.get("source_chars"):
        artifact_text = " ".join(Path(task["artifact_path"]).read_text(encoding="utf-8").split())
        if not any(
            (quote := " ".join(str(item.get("quote", "")).split())) and quote in artifact_text
            for item in matches
        ):
            return f"{output}: source citation quote does not match the task artifact"
    return None


def _verify_child(parent_wiki: Path, item: dict, child_path: Path) -> list[str]:
    child = load_manifest(child_path)
    metadata = child.get("metadata", {})
    if (
        Path(metadata.get("wiki_dir", ".")).resolve() != parent_wiki.resolve()
        or metadata.get("source_id") != item.get("source_id")
        or any(task.get("source_path") != item.get("source_path") for task in child["items"])
        or not child.get("coverage_complete")
        or not child.get("published_revision")
    ):
        raise ValueError("Child compile must publish this exact source snapshot in the same wiki")
    return sorted({output for task in child["items"] for output in task.get("outputs", [])})


def _publish_agent(manifest: dict, wiki: Path, stage: Path) -> str:
    import compile_v2
    import yaml
    from okf import read_markdown
    from raw_evidence import evidence_publication, verify_evidence_bundle

    metadata = manifest["metadata"]
    evidence_path = Path(metadata["evidence_manifest"])
    evidence = read_json(evidence_path)
    source_id = metadata["source_id"]
    outputs = sorted({output for item in manifest["items"] for output in item["outputs"]})
    live_pages = wiki / "pages"

    def prepare() -> dict[str, bytes | None]:
        receipt = evidence_path.parent / "published.json"
        if receipt.is_file():
            if not verify_evidence_bundle(evidence_path)["coverage_complete"]:
                raise ValueError("Published source evidence did not pass integrity verification")
            return {}
        pointer = evidence_publication(wiki, evidence_path, outputs)
        current = active_source(wiki, source_id)
        removed = set(current.get("outputs", [])) - set(outputs)
        updates = {}
        graph_pages = []
        changes: dict[str, bytes | None] = dict(pointer)
        for output in outputs:
            page = _agent_output_path(stage, output)
            destination = _agent_output_path(live_pages, output)
            frontmatter, body, error = read_markdown(page)
            if error:
                raise ValueError(error)
            if destination.is_file():
                prior, _, _ = read_markdown(destination)
                owners = compile_v2._page_source_ids(prior)
                if owners and owners != {source_id}:
                    raise ValueError(
                        f"{output} belongs to a different source. Choose a distinct Concept ID."
                    )
            frontmatter["id"] = output
            frontmatter["source_id"] = source_id
            frontmatter["source_version"] = evidence["source_version"]
            frontmatter.setdefault("provenance", evidence["source_name"])
            content = strip_secrets(
                "---\n"
                + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
                + "---\n"
                + body
            )
            updates[output] = frontmatter
            changes[destination.relative_to(wiki).as_posix()] = content.encode("utf-8")
            changes[
                (evidence_path.parent / "compiled_pages" / f"{output}.md")
                .relative_to(wiki)
                .as_posix()
            ] = content.encode("utf-8")
            graph_pages.append(
                {
                    "id": output,
                    "type": frontmatter["type"],
                    "name": frontmatter.get("title") or frontmatter["name"],
                    "path": str(destination),
                    "_content": content,
                }
            )
        for output in list(removed):
            destination = _agent_output_path(live_pages, output)
            frontmatter, _, _ = read_markdown(destination)
            if frontmatter.get("source_id") == source_id and not frontmatter.get("source_ids"):
                changes[destination.relative_to(wiki).as_posix()] = None
            else:
                removed.discard(output)
        entities, edges = compile_v2._graph_content(
            graph_pages, evidence["source_name"], wiki / "graph", removed, replace_edges=True
        )
        changes["graph/entities.json"] = json_bytes(entities)
        changes["graph/edges.json"] = json_bytes(edges)
        changes["pages/index.md"] = compile_v2._index_content(
            live_pages,
            updates,
            removed,
        ).encode("utf-8")
        log = compile_v2._log_content(live_pages / "log.md", evidence["source_name"], len(outputs))
        changes["pages/log.md"] = log.encode("utf-8")
        changes["audit.json"] = compile_v2._audit_content(
            wiki / "audit.json",
            "compile",
            {
                "source": evidence["source_name"],
                "source_id": source_id,
                "source_version": evidence["source_version"],
                "pages": outputs,
                "mode": "agent",
                "coverage_complete": True,
            },
        ).encode("utf-8")
        changes[receipt.relative_to(wiki).as_posix()] = json_bytes(
            {
                "revision": evidence["revision"],
                "outputs": outputs,
                "published_at": utc_now(),
            }
        )
        return changes

    publish_changes(wiki, prepare)
    return evidence["revision"]


def update_task(
    path: str | Path,
    task_id: str,
    status: str,
    *,
    outputs: list[str] | None = None,
    note: str = "",
    error: str = "",
    child: str | Path | None = None,
) -> dict[str, Any]:
    """Update one task and persist refreshed counters."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid task status: {status}")
    manifest_path = Path(path)
    manifest = load_manifest(manifest_path)
    evidence = manifest.get("metadata", {}).get("evidence_manifest")
    if manifest.get("published_revision") or (
        evidence and Path(evidence).with_name("published.json").is_file()
    ):
        raise ValueError("This worklist is published. Start a new compile to change it.")
    target_index = next(
        (index for index, item in enumerate(manifest["items"]) if item.get("id") == task_id),
        None,
    )
    target = manifest["items"][target_index] if target_index is not None else None
    if target is None:
        raise KeyError(f"Unknown task id: {task_id}")

    if status == "in_progress":
        unattempted_prior = [
            str(item.get("id"))
            for item in manifest["items"][:target_index]
            if item.get("status") not in {"completed", "failed", "blocked"}
        ]
        if unattempted_prior:
            prior_ids = ", ".join(unattempted_prior)
            raise ValueError(f"Tasks must run in order; finish earlier tasks first: {prior_ids}")
        target["attempts"] = int(target.get("attempts", 0)) + 1
        target["started_at"] = utc_now()
    elif status in {"completed", "failed", "blocked"} and target.get("status") != "in_progress":
        raise ValueError(f"{task_id} must be in_progress before it can become {status}")
    if status == "completed" and (review_pages := target.get("pdf_agent_review_pages")):
        records_path = manifest.get("metadata", {}).get("raw_evidence_records")
        reviewed = set()
        if records_path and Path(records_path).is_file():
            for line in Path(records_path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    if record.get("reviewed_visual", "").strip():
                        reviewed.add(record["page_number"])
        missing = sorted(set(review_pages) - reviewed)
        if missing:
            raise ValueError(
                f"Attach Agent visual observations for PDF pages {missing} before completion"
            )
    metadata = manifest.get("metadata", {})
    normalized_outputs = [str(value) for value in outputs] if outputs else []
    if status == "completed" and metadata.get("directory_worklist"):
        if not child:
            raise ValueError("A verified child worklist is required (complete --child)")
        child_path = Path(child).resolve()
        normalized_outputs = _verify_child(Path(metadata["wiki_dir"]), target, child_path)
        target["child_manifest"] = str(child_path)
    elif child:
        raise ValueError("Child worklists apply only to directory tasks")

    if status == "completed" and metadata.get("staged_pages") and normalized_outputs:
        stage = Path(metadata["staged_pages"])
        normalized_outputs = [_staged_concept_id(stage, output) for output in normalized_outputs]
        for output in normalized_outputs:
            if error_message := _agent_citation_error(stage, output, target):
                raise ValueError(error_message)
            staged_file = _agent_output_path(stage, output)
            original_content = staged_file.read_text(encoding="utf-8")
            cleaned_content = strip_secrets(original_content)
            if cleaned_content != original_content:
                _atomic_write_text(staged_file, cleaned_content)

    if status == "completed" and normalized_outputs and not metadata.get("directory_worklist"):
        target["media_fidelity"] = _finalize_agent_task_media(
            manifest,
            target,
            normalized_outputs,
        )
    if normalized_outputs:
        target["outputs"] = list(dict.fromkeys(normalized_outputs))
    if note:
        target.setdefault("notes", []).append(strip_secrets(note))
    target["error"] = strip_secrets(error)
    target["status"] = status
    if status in {"completed", "failed", "blocked"}:
        target["finished_at"] = utc_now()

    _refresh_summary(manifest)
    _atomic_write_json(manifest_path, manifest)
    return manifest


def verify_manifest(
    path: str | Path,
    *,
    require_outputs: bool = True,
) -> dict[str, Any]:
    """Verify that every planned task completed without source drift or omissions."""
    manifest_path = Path(path)
    manifest = load_manifest(manifest_path)
    errors: list[str] = []
    metadata = manifest.get("metadata", {})
    wiki_dir_value = metadata.get("wiki_dir")
    wiki = Path(wiki_dir_value).resolve() if wiki_dir_value else None
    published_pages = wiki / "pages" if wiki else None
    stage = Path(metadata["staged_pages"]) if metadata.get("staged_pages") else None
    wiki_pages = stage or published_pages

    if not manifest["items"]:
        errors.append("todo list is empty")

    for item in manifest["items"]:
        task_id = str(item.get("id", "unknown"))
        if item.get("status") != "completed":
            errors.append(f"{task_id}: status is {item.get('status', 'pending')}")
        if (require_outputs or stage) and not item.get("outputs"):
            errors.append(f"{task_id}: no compiled outputs recorded")
        elif metadata.get("directory_worklist") and wiki is not None:
            try:
                child_path = Path(item["child_manifest"])
                if _verify_child(wiki, item, child_path) != sorted(item["outputs"]):
                    errors.append(f"{task_id}: child outputs no longer match")
            except (KeyError, OSError, ValueError) as exc:
                errors.append(f"{task_id}: child verification failed: {exc}")
        elif manifest.get("mode") == "agent" and wiki_pages is not None:
            for output in item.get("outputs", []):
                try:
                    output_path = _agent_output_path(wiki_pages, str(output))
                except ValueError as exc:
                    errors.append(f"{task_id}: {exc}")
                    continue
                if not output_path.is_file():
                    errors.append(f"{task_id}: compiled output is missing: {output_path}")
                else:
                    if stage:
                        try:
                            if error := _agent_citation_error(stage, str(output), item):
                                errors.append(f"{task_id}: {error}")
                            staged_text = output_path.read_text(encoding="utf-8")
                            if staged_text != strip_secrets(staged_text):
                                errors.append(
                                    f"{task_id}: staged concept contains unredacted fields"
                                )
                        except (OSError, ValueError) as exc:
                            errors.append(f"{task_id}: source citation could not be checked: {exc}")
                    artifact = item.get("artifact_path")
                    if artifact and Path(str(artifact)).suffix.lower() in {".md", ".markdown"}:
                        try:
                            import compile_v2

                            source_content = Path(str(artifact)).read_text(encoding="utf-8")
                            page_content = output_path.read_text(encoding="utf-8")
                            expected = compile_v2._attach_source_media(
                                page_content,
                                source_content,
                                _agent_output_path(published_pages, str(output)),
                            )
                            if expected != page_content:
                                errors.append(
                                    f"{task_id}: source media finalization is incomplete: "
                                    f"{output_path}"
                                )
                        except (OSError, UnicodeDecodeError) as exc:
                            errors.append(f"{task_id}: media verification failed: {exc}")

        artifact = item.get("artifact_path")
        expected_hash = item.get("artifact_sha256")
        if artifact:
            artifact_path = Path(str(artifact))
            if not artifact_path.is_file():
                errors.append(f"{task_id}: source artifact is missing: {artifact_path}")
            elif expected_hash and sha256_file(artifact_path) != expected_hash:
                errors.append(f"{task_id}: source artifact checksum changed")

    if not errors and stage is not None and wiki is not None:
        try:
            manifest["published_revision"] = _publish_agent(manifest, wiki, stage)
        except (KeyError, OSError, ValueError) as exc:
            errors.append(f"Publication failed: {exc}")

    manifest["verification"] = {
        "checked_at": utc_now(),
        "ok": not errors,
        "errors": errors,
    }
    _refresh_summary(manifest)
    manifest["coverage_complete"] = not errors
    manifest["status"] = "completed" if not errors else "incomplete"
    _atomic_write_json(manifest_path, manifest)
    return manifest


def _print_manifest(manifest: dict[str, Any]) -> None:
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    """Manage a compile todo manifest from the command line."""
    parser = argparse.ArgumentParser(description="Manage compile completeness todo lists")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show the current todo list")
    show_parser.add_argument("manifest")

    start_parser = subparsers.add_parser("start", help="Mark a task in progress")
    start_parser.add_argument("manifest")
    start_parser.add_argument("task_id")

    complete_parser = subparsers.add_parser("complete", help="Mark a task completed")
    complete_parser.add_argument("manifest")
    complete_parser.add_argument("task_id")
    complete_target = complete_parser.add_mutually_exclusive_group(required=True)
    complete_target.add_argument("--output", action="append")
    complete_target.add_argument("--child")
    complete_parser.add_argument("--note", default="")

    fail_parser = subparsers.add_parser("fail", help="Mark a task failed or blocked")
    fail_parser.add_argument("manifest")
    fail_parser.add_argument("task_id")
    fail_parser.add_argument("--error", required=True)
    fail_parser.add_argument("--blocked", action="store_true")

    verify_parser = subparsers.add_parser("verify", help="Run the final completeness gate")
    verify_parser.add_argument("manifest")

    args = parser.parse_args()
    if args.command == "show":
        result = load_manifest(args.manifest)
    elif args.command == "start":
        result = update_task(args.manifest, args.task_id, "in_progress")
    elif args.command == "complete":
        result = update_task(
            args.manifest,
            args.task_id,
            "completed",
            outputs=args.output,
            note=args.note,
            child=args.child,
        )
    elif args.command == "fail":
        result = update_task(
            args.manifest,
            args.task_id,
            "blocked" if args.blocked else "failed",
            error=args.error,
        )
    else:
        result = verify_manifest(args.manifest)
        _print_manifest(result)
        if not result.get("coverage_complete"):
            raise SystemExit(1)
        return
    _print_manifest(result)


if __name__ == "__main__":
    main()
