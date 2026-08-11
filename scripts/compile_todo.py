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
    manifest["coverage_complete"] = bool(total) and completed == total
    if manifest["coverage_complete"]:
        manifest["status"] = "completed"
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
    wiki_pages = Path(str(wiki_dir_value)) / "pages"
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
        enriched = compile_v2._attach_source_media(page_content, source_content, output_path)
        if enriched != page_content:
            _atomic_write_text(output_path, enriched)
        image_targets = [
            compile_v2._clean_image_target(match.group("target"))
            for match in compile_v2.MARKDOWN_IMAGE_RE.finditer(enriched)
        ]
        for target in image_targets:
            local_path = compile_v2._local_image_path(target, output_path.parent)
            if local_path is not None and not local_path.is_file():
                raise ValueError(f"{output_path}: compiled image target is missing: {target}")
        records.append(
            {
                "output": str(output),
                "output_path": str(output_path),
                "output_sha256": sha256_file(output_path),
                "image_targets": image_targets,
            }
        )
    return records


def update_task(
    path: str | Path,
    task_id: str,
    status: str,
    *,
    outputs: list[str] | None = None,
    note: str = "",
    error: str = "",
) -> dict[str, Any]:
    """Update one task and persist refreshed counters."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid task status: {status}")
    manifest_path = Path(path)
    manifest = load_manifest(manifest_path)
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
    normalized_outputs = [str(value) for value in outputs] if outputs else []
    if status == "completed" and normalized_outputs:
        target["media_fidelity"] = _finalize_agent_task_media(
            manifest,
            target,
            normalized_outputs,
        )
    if normalized_outputs:
        existing = [str(value) for value in target.get("outputs", [])]
        target["outputs"] = list(dict.fromkeys(existing + normalized_outputs))
    if note:
        target.setdefault("notes", []).append(note)
    target["error"] = error
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
    wiki_dir_value = manifest.get("metadata", {}).get("wiki_dir")
    wiki_pages = Path(str(wiki_dir_value)) / "pages" if wiki_dir_value else None

    if not manifest["items"]:
        errors.append("todo list is empty")

    for item in manifest["items"]:
        task_id = str(item.get("id", "unknown"))
        if item.get("status") != "completed":
            errors.append(f"{task_id}: status is {item.get('status', 'pending')}")
        if require_outputs and not item.get("outputs"):
            errors.append(f"{task_id}: no compiled outputs recorded")
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
                    artifact = item.get("artifact_path")
                    if artifact and Path(str(artifact)).suffix.lower() in {".md", ".markdown"}:
                        try:
                            import compile_v2

                            source_content = Path(str(artifact)).read_text(encoding="utf-8")
                            page_content = output_path.read_text(encoding="utf-8")
                            expected = compile_v2._attach_source_media(
                                page_content,
                                source_content,
                                output_path,
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
    complete_parser.add_argument("--output", action="append", required=True)
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
