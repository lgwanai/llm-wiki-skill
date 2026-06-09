"""Tests for compile source discovery and image source handling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.compile_v2 as compile_v2


def test_iter_source_files_respects_depth_and_skips_wiki(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "root.md").write_text("# Root", encoding="utf-8")
    (root / "image.png").write_bytes(b"fake")
    child = root / "child"
    child.mkdir()
    (child / "child.md").write_text("# Child", encoding="utf-8")
    grandchild = child / "grandchild"
    grandchild.mkdir()
    (grandchild / "deep.md").write_text("# Deep", encoding="utf-8")
    wiki = root / ".wiki"
    wiki.mkdir()
    (wiki / "generated.md").write_text("# Generated", encoding="utf-8")

    depth_0 = {p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root, max_depth=0)}
    depth_1 = {p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root, max_depth=1)}
    all_files = {p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root)}

    assert depth_0 == {"image.png", "root.md"}
    assert depth_1 == {"child/child.md", "image.png", "root.md"}
    assert all_files == {"child/child.md", "child/grandchild/deep.md", "image.png", "root.md"}


def test_image_source_uses_analysis_and_keeps_source_path(tmp_path, monkeypatch):
    image = tmp_path / "diagram.webp"
    image.write_bytes(b"fake image")

    class FakeBackend:
        def ocr_image(self, image_path: str) -> str:
            assert image_path == str(image)
            return "- Root\n  - Child\n"

    import ocr._ocr_api as ocr_api

    monkeypatch.setattr(
        compile_v2,
        "get_image_analysis_config",
        lambda: {"enabled": True, "ocr_fallback": False, "api_provider": "openai"},
    )
    monkeypatch.setattr(
        ocr_api,
        "create_vision_backend",
        lambda settings, prompt: FakeBackend(),
    )

    content, source_name = compile_v2.read_source_content(image)

    assert source_name == "diagram.webp"
    assert f"> Source image: {image.resolve()}" in content
    assert "## Visual Analysis" in content
    assert "- Root" in content


def test_schema_type_loading_has_compile_defaults(tmp_path, monkeypatch):
    schema = tmp_path / "schema.md"
    schema.write_text(
        """
## Entity Types

| type | directory | description |
|------|-----------|-------------|
| `person` | entities | contributor |
| `concept` | concepts | abstract idea |

## Relationship Types

| Type | Direction | Meaning | Example |
|------|-----------|---------|---------|
| `uses` | A -> B | A uses B | example |
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(compile_v2, "SCHEMA_PATH", schema)

    entity_types, entity_lines, rel_lines = compile_v2.load_entity_types_from_schema()

    assert "person" in entity_types
    assert "process" in entity_types
    assert "**person**: contributor" in entity_lines
    assert "**uses**: A uses B" in rel_lines


def test_process_type_is_not_concept_like():
    assert "concept" in compile_v2.CONCEPT_LIKE_TYPES
    assert "process" not in compile_v2.CONCEPT_LIKE_TYPES
