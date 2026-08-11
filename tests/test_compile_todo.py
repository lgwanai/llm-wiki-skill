"""Tests for ordered, fail-closed compile worklists."""

from __future__ import annotations

import json
from pathlib import Path

import compile_todo
import compile_v2
import pytest


def _make_manifest(tmp_path: Path, task_count: int = 2) -> tuple[Path, list[Path]]:
    artifacts: list[Path] = []
    items = []
    for index in range(1, task_count + 1):
        artifact = tmp_path / f"part-{index}.md"
        artifact.write_text(f"# Part {index}\n\nComplete source text.", encoding="utf-8")
        artifacts.append(artifact)
        items.append(
            {
                "id": f"chunk-{index:04d}",
                "artifact_path": str(artifact),
                "artifact_sha256": compile_todo.sha256_file(artifact),
            }
        )
    manifest_path = tmp_path / "todolist.json"
    compile_todo.create_manifest(
        manifest_path,
        source="large-source.md",
        mode="test",
        items=items,
    )
    return manifest_path, artifacts


def test_todo_requires_ordered_execution_and_outputs(tmp_path: Path):
    manifest_path, _ = _make_manifest(tmp_path)

    with pytest.raises(ValueError, match="run in order"):
        compile_todo.update_task(manifest_path, "chunk-0002", "in_progress")

    compile_todo.update_task(manifest_path, "chunk-0001", "in_progress")
    compile_todo.update_task(
        manifest_path,
        "chunk-0001",
        "completed",
        outputs=["concepts/part-1"],
    )
    compile_todo.update_task(manifest_path, "chunk-0002", "in_progress")
    compile_todo.update_task(
        manifest_path,
        "chunk-0002",
        "completed",
        outputs=["concepts/part-2"],
    )

    verified = compile_todo.verify_manifest(manifest_path)
    assert verified["coverage_complete"] is True
    assert verified["summary"]["completed"] == 2
    assert verified["verification"]["errors"] == []


def test_todo_verification_fails_on_missing_output_or_source_drift(tmp_path: Path):
    manifest_path, artifacts = _make_manifest(tmp_path)
    compile_todo.update_task(manifest_path, "chunk-0001", "in_progress")
    compile_todo.update_task(manifest_path, "chunk-0001", "completed")
    compile_todo.update_task(manifest_path, "chunk-0002", "in_progress")
    compile_todo.update_task(
        manifest_path,
        "chunk-0002",
        "completed",
        outputs=["concepts/part-2"],
    )
    artifacts[1].write_text("changed after planning", encoding="utf-8")

    verified = compile_todo.verify_manifest(manifest_path)
    errors = "\n".join(verified["verification"]["errors"])
    assert verified["coverage_complete"] is False
    assert "chunk-0001: no compiled outputs recorded" in errors
    assert "chunk-0002: source artifact checksum changed" in errors


def test_agent_todo_verifies_recorded_concept_files_exist(tmp_path: Path):
    artifact = tmp_path / "part.md"
    artifact.write_text("# Complete source", encoding="utf-8")
    wiki = tmp_path / ".wiki"
    manifest_path = tmp_path / "agent-todolist.json"
    compile_todo.create_manifest(
        manifest_path,
        source="source.md",
        mode="agent",
        items=[
            {
                "id": "chunk-0001",
                "artifact_path": str(artifact),
                "artifact_sha256": compile_todo.sha256_file(artifact),
            }
        ],
        metadata={"wiki_dir": str(wiki)},
    )
    compile_todo.update_task(manifest_path, "chunk-0001", "in_progress")
    compile_todo.update_task(
        manifest_path,
        "chunk-0001",
        "completed",
        outputs=["concepts/missing"],
    )

    verified = compile_todo.verify_manifest(manifest_path)
    assert verified["coverage_complete"] is False
    assert "compiled output is missing" in "\n".join(verified["verification"]["errors"])


def test_agent_completion_attaches_and_verifies_cited_source_images(tmp_path: Path):
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages"
    image = pages / "assets" / "book" / "weather.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"weather-map")
    artifact = tmp_path / "part.md"
    artifact.write_text(
        f"## Page 12\n\n![天气图]({image.resolve()})\n\n天气与气候正文。\n",
        encoding="utf-8",
    )
    output = pages / "concepts" / "weather.md"
    output.parent.mkdir(parents=True)
    output.write_text(
        "---\ntype: concept\ntitle: 天气与气候\n---\n"
        "# 天气与气候\n\n## 来源追溯\n\n- 页码：第 12 页\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "agent-todolist.json"
    compile_todo.create_manifest(
        manifest_path,
        source="geography.md",
        mode="agent",
        items=[{
            "id": "chunk-0001",
            "artifact_path": str(artifact),
            "artifact_sha256": compile_todo.sha256_file(artifact),
        }],
        metadata={"wiki_dir": str(wiki), "study_material": True},
    )

    compile_todo.update_task(manifest_path, "chunk-0001", "in_progress")
    completed = compile_todo.update_task(
        manifest_path,
        "chunk-0001",
        "completed",
        outputs=["concepts/weather"],
    )

    compiled = output.read_text(encoding="utf-8")
    assert "## 来源图片" in compiled
    assert "../assets/book/weather.png" in compiled
    assert completed["items"][0]["media_fidelity"][0]["image_targets"]
    verified = compile_todo.verify_manifest(manifest_path)
    assert verified["coverage_complete"] is True


def test_image_bearing_study_output_requires_page_or_section_citation(tmp_path: Path):
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages"
    image = pages / "assets" / "book" / "map.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"map")
    artifact = tmp_path / "part.md"
    artifact.write_text(f"## Page 3\n\n![地图]({image.resolve()})\n", encoding="utf-8")
    output = pages / "concepts" / "map.md"
    output.parent.mkdir(parents=True)
    output.write_text("---\ntype: concept\ntitle: 地图\n---\n# 地图\n", encoding="utf-8")
    manifest_path = tmp_path / "agent-todolist.json"
    compile_todo.create_manifest(
        manifest_path,
        source="geography.md",
        mode="agent",
        items=[{
            "id": "chunk-0001",
            "artifact_path": str(artifact),
            "artifact_sha256": compile_todo.sha256_file(artifact),
        }],
        metadata={"wiki_dir": str(wiki), "study_material": True},
    )
    compile_todo.update_task(manifest_path, "chunk-0001", "in_progress")

    with pytest.raises(ValueError, match="lacks an exact page/EPUB section citation"):
        compile_todo.update_task(
            manifest_path,
            "chunk-0001",
            "completed",
            outputs=["concepts/map"],
        )


def test_agent_large_source_creates_complete_chunk_todolist(
    wiki_dir, monkeypatch: pytest.MonkeyPatch
):
    wiki = Path(wiki_dir) / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(compile_v2, "PAGES_DIR", wiki / "pages")
    monkeypatch.setattr(compile_v2, "ENTITIES_DIR", wiki / "pages" / "entities")
    monkeypatch.setattr(compile_v2, "CONCEPTS_DIR", wiki / "pages" / "concepts")
    monkeypatch.setattr(compile_v2, "INDEX_FILE", wiki / "pages" / "index.md")
    monkeypatch.setattr(compile_v2, "SCHEMA_PATH", wiki / "schema.md")
    monkeypatch.setattr(compile_v2, "get_chunk_threshold", lambda: 20)

    source = Path(wiki_dir) / "large-study.md"
    source.write_text(
        "\n\n".join(
            f"## Knowledge {index}\n" + ("complete explanation " * 600) for index in range(1, 7)
        ),
        encoding="utf-8",
    )

    result = compile_v2.create_agent_compile_task(str(source))
    todo_path = Path(result["todo"])
    manifest = json.loads(todo_path.read_text(encoding="utf-8"))
    task_text = Path(result["agent_task"]).read_text(encoding="utf-8")

    assert result["tasks_total"] > 1
    assert len(manifest["items"]) == result["tasks_total"]
    assert all(Path(item["artifact_path"]).is_file() for item in manifest["items"])
    assert all(item["status"] == "pending" for item in manifest["items"])
    assert "Completeness Todo Protocol" in task_text
    assert "coverage_complete: true" in task_text
    assert "Never infer completion from this preview" in task_text


def test_chunked_compile_does_not_publish_when_any_task_fails(
    wiki_dir, monkeypatch: pytest.MonkeyPatch
):
    wiki = Path(wiki_dir) / ".wiki"
    pages = wiki / "pages"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(compile_v2, "PAGES_DIR", pages)
    monkeypatch.setattr(compile_v2, "ENTITIES_DIR", pages / "entities")
    monkeypatch.setattr(compile_v2, "CONCEPTS_DIR", pages / "concepts")
    monkeypatch.setattr(compile_v2, "INDEX_FILE", pages / "index.md")

    output_path = pages / "concepts" / "first.md"
    calls = {"count": 0}

    def compile_one(chunk: str, *_args, **_kwargs):
        calls["count"] += 1
        if "SECOND" in chunk:
            raise RuntimeError("context task failed")
        return {
            "created_pages": [
                {
                    "id": "concepts/first",
                    "type": "concept",
                    "name": "First",
                    "path": str(output_path),
                    "facts": 1,
                    "relationships": 0,
                    "_content": "---\ntype: concept\ntitle: First\n---\n# First\n",
                }
            ],
            "updated_pages": [],
        }

    monkeypatch.setattr(compile_v2, "_compile_single_chunk", compile_one)

    with pytest.raises(RuntimeError, match="no pages published"):
        compile_v2._compile_chunked(
            ["FIRST", "SECOND"],
            "large.md",
            "doc",
            False,
            False,
            "en",
            ["concept"],
            "",
            "",
            [],
            "",
            "concept",
        )

    manifests = list((wiki / "compile_runs").glob("*/todolist.json"))
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["coverage_complete"] is False
    assert manifest["summary"]["completed"] == 1
    assert manifest["summary"]["failed"] == 1
    assert calls["count"] == 4  # first task once, failed task retried three times
    assert not output_path.exists()
