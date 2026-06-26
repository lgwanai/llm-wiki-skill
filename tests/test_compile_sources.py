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
    source.write_bytes(b"%PDF fake")
    wiki_dir = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki_dir)

    def fake_render(path):
        assert path == source
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
        lambda path: (pages, "pdf-pages"),
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
