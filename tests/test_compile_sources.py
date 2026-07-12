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

    depth_0 = {
        p.relative_to(root).as_posix()
        for p in compile_v2.iter_source_files(root, max_depth=0)
    }
    depth_1 = {
        p.relative_to(root).as_posix()
        for p in compile_v2.iter_source_files(root, max_depth=1)
    }
    all_files = {p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root)}

    assert depth_0 == {"image.png", "root.md"}
    assert depth_1 == {"child/child.md", "image.png", "root.md"}
    assert all_files == {"child/child.md", "child/grandchild/deep.md", "image.png", "root.md"}


def test_paginated_documents_are_supported_sources(tmp_path):
    pdf = tmp_path / "brief.pdf"
    pptx = tmp_path / "deck.pptx"
    pdf.write_bytes(b"%PDF fake")
    pptx.write_bytes(b"fake pptx")

    assert compile_v2.is_supported_source(pdf)
    assert compile_v2.is_supported_source(pptx)


def test_paginated_document_without_ocr_preserves_every_page_for_agent(tmp_path, monkeypatch):
    source = tmp_path / "deck.pdf"
    original_bytes = b"%PDF fake"
    source.write_bytes(original_bytes)
    wiki_dir = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki_dir)

    def fake_render(path, storage_source_path=None):
        assert path != source
        assert path.name == source.name
        assert path.read_bytes() == original_bytes
        assert storage_source_path == source
        output_dir = wiki_dir / "source" / "document_images" / "deck-test"
        output_dir.mkdir(parents=True)
        page_1 = output_dir / "page-001.png"
        page_2 = output_dir / "page-002.png"
        page_1.write_bytes(b"page 1")
        page_2.write_bytes(b"page 2")
        return [page_1, page_2], "pdf-pages"

    monkeypatch.setattr(compile_v2, "_render_paginated_document_to_images", fake_render)
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: False)
    monkeypatch.setattr(compile_v2, "_image_analysis_available", lambda: False)

    content, readable = compile_v2._read_agent_visible_source(source)

    assert readable is True
    assert "> **Pages/slides rendered**: 2" in content
    assert "## Page 1" in content
    assert "## Page 2" in content
    assert "page-001.png" in content
    assert "page-002.png" in content
    assert "Agent must read this rendered page image" in content
    assert source.read_bytes() == original_bytes


def test_paginated_document_ocr_runs_for_every_page(tmp_path, monkeypatch):
    source = tmp_path / "handbook.pdf"
    source.write_bytes(b"%PDF fake")
    wiki_dir = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki_dir)

    output_dir = wiki_dir / "source" / "document_images" / "handbook-test"
    output_dir.mkdir(parents=True)
    pages = [
        output_dir / "page-001.png",
        output_dir / "page-002.png",
        output_dir / "page-003.png",
    ]
    for page in pages:
        page.write_bytes(b"image")

    monkeypatch.setattr(
        compile_v2,
        "_render_paginated_document_to_images",
        lambda path, storage_source_path=None: (pages, "pdf-pages"),
    )
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: True)
    monkeypatch.setattr(
        compile_v2,
        "_ocr_image_with_config",
        lambda image_path: f"OCR text for {image_path.name}",
    )

    content = compile_v2._read_paginated_document_for_compile(source)

    assert content.count("## Page ") == 3
    assert "OCR text for page-001.png" in content
    assert "OCR text for page-002.png" in content
    assert "OCR text for page-003.png" in content


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
    assert f"> **Original**: `{image.resolve()}`" in content
    assert "> **Stored at**:" in content
    assert "## Visual Analysis" in content
    assert "- Root" in content


def test_llm_mode_image_without_vision_or_ocr_hands_off(tmp_path, monkeypatch):
    """--mode llm with no vision API and no OCR → embed the image as last resort.

    No configured model produced text, so the compile must not fail hard; it
    hands the image (with a renderable link) to the consuming model.
    """
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake image bytes")

    images_dir = tmp_path / "source" / "images"
    monkeypatch.setattr(compile_v2, "SOURCE_IMAGES_DIR", images_dir)
    monkeypatch.setattr(
        compile_v2,
        "get_image_analysis_config",
        lambda: {"enabled": False, "ocr_fallback": True},
    )
    # Simulate "no OCR backend configured / usable".
    monkeypatch.setattr(
        compile_v2,
        "_ocr_image_with_config",
        lambda _image_path: (_ for _ in ()).throw(RuntimeError("no OCR backend")),
    )

    content = compile_v2.analyze_image_for_compile(image)  # for_agent=False → llm mode

    # Did not raise; emits a last-resort handoff with a renderable image link.
    assert "## Image Recognition Required" in content
    assert f"![{image.stem}]" in content
    assert "multimodal" in content
    # The stored copy is referenced so the link resolves inside the wiki.
    assert str((images_dir / "diagram.png").resolve()) in content


def test_agent_mode_image_prefers_vision_skill_with_ocr_fallback(tmp_path, monkeypatch):
    """Agent mode: vision-skill is primary, OCR text is pre-extracted as fallback."""
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake image bytes")

    images_dir = tmp_path / "source" / "images"
    monkeypatch.setattr(compile_v2, "SOURCE_IMAGES_DIR", images_dir)
    monkeypatch.setattr(
        compile_v2,
        "get_vision_skill_config",
        lambda: {
            "enabled": True,
            "scripts_path": str(tmp_path / "vs-scripts"),
            "recognize_format": "markdown_note",
        },
    )
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: True)
    monkeypatch.setattr(
        compile_v2,
        "_ocr_image_with_config",
        lambda _image_path: "OCR fallback text",
    )

    content, readable = compile_v2._read_agent_visible_source(image)

    assert readable is True
    # Precedence header and vision-skill as tier 1.
    assert "vision-skill → OCR → your own capability" in content
    assert "vision-skill (preferred)" in content
    # Concrete CLI command emitted using the configured scripts_path.
    assert "vision_cli.py recognize" in content
    assert "--format markdown_note --wait" in content
    assert str(tmp_path / "vs-scripts" / "vision_cli.py") in content
    # OCR fallback text is attached.
    assert "### OCR Text (fallback)" in content
    assert "OCR fallback text" in content
    # Image link is present for the Agent.
    assert f"![{image.stem}]" in content


def test_agent_mode_image_without_ocr_keeps_native_fallback(tmp_path, monkeypatch):
    """Agent mode with vision-skill but no OCR backend: native capability is last resort."""
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"fake image bytes")

    images_dir = tmp_path / "source" / "images"
    monkeypatch.setattr(compile_v2, "SOURCE_IMAGES_DIR", images_dir)
    monkeypatch.setattr(
        compile_v2,
        "get_vision_skill_config",
        lambda: {"enabled": True, "scripts_path": "", "recognize_format": "markdown_note"},
    )
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: False)

    content, readable = compile_v2._read_agent_visible_source(image)

    assert readable is True
    assert "vision-skill (preferred)" in content
    assert "Native capability" in content
    assert "[No OCR backend configured" in content
    # No scripts_path → no CLI command, but the skill is still referenced by name.
    assert "vision_cli.py" not in content


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


def test_ensure_created_at_fills_missing(tmp_path):
    page = "---\nid: foo\ntype: concept\nname: Foo\n---\n\n# Foo\nbody"
    out = compile_v2._ensure_created_at(page, "2026-07-05")
    assert "created_at: 2026-07-05" in out
    # Inserted as a frontmatter key, not into the body.
    assert out.index("created_at:") < out.index("---", 3)


def test_ensure_created_at_preserves_existing_date():
    page = "---\nid: bar\ncreated_at: 2020-01-01\ntype: concept\n---\n\nbody"
    out = compile_v2._ensure_created_at(page, "2026-07-05")
    assert "created_at: 2020-01-01" in out
    assert "2026-07-05" not in out  # not overwritten on update


def test_ensure_created_at_replaces_empty_value_without_duplicate():
    """Empty created_at must be filled in place — no duplicate YAML keys."""
    page = "---\nid: baz\ncreated_at:\ntype: concept\n---\n\nbody"
    out = compile_v2._ensure_created_at(page, "2026-07-05")
    assert out.count("created_at:") == 1  # no duplicate key
    assert "created_at: 2026-07-05" in out


def test_ensure_created_at_handles_no_frontmatter():
    assert compile_v2._ensure_created_at("just body", "2026-07-05") == "just body"


def test_materialize_text_source_writes_and_sanitizes(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    path = compile_v2._materialize_text_source("hello world", "My Notes/evil")
    written = Path(path)
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == "hello world"
    # Path separators sanitized; no directory traversal.
    assert written.parent == wiki / "source"
    assert "/" not in written.stem and "\\" not in written.stem


def test_materialize_text_source_default_name_and_collision(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    p1 = compile_v2._materialize_text_source("first")
    p2 = compile_v2._materialize_text_source("second")  # same default prefix path? no — timestamp
    assert Path(p1).is_file()
    assert Path(p2).is_file()
    # Pre-create a collision and write again — must not overwrite.
    collide = wiki / "source" / "fixed.md"
    collide.parent.mkdir(parents=True, exist_ok=True)
    collide.write_text("orig", encoding="utf-8")
    p3 = compile_v2._materialize_text_source("new", "fixed")
    assert Path(p3).read_text(encoding="utf-8") == "new"
    assert collide.read_text(encoding="utf-8") == "orig"  # original preserved
