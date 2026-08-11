"""Tests for compile source discovery and image source handling."""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.compile_v2 as compile_v2


def test_compile_import_path_prefers_real_ocr_package() -> None:
    project_root = Path(__file__).resolve().parent.parent
    scripts_dir = project_root / "scripts"

    assert sys.path.index(str(project_root)) < sys.path.index(str(scripts_dir))
    import ocr

    assert Path(ocr.__file__).resolve() == project_root / "ocr" / "__init__.py"


def test_ovis_image_uses_managed_temporary_document_route(monkeypatch) -> None:
    image = Path("/tmp/exam-page.png")
    monkeypatch.setattr(compile_v2, "get_ocr_config", lambda: {"backend": "ovis"})
    monkeypatch.setattr(
        compile_v2,
        "_ocr_pdf_with_config",
        lambda path: f"managed OCR for {path.name}",
    )
    monkeypatch.setattr(
        compile_v2,
        "_create_ocr_backend",
        lambda: pytest.fail("Ovis image OCR must not create a sibling work directory"),
    )

    assert compile_v2._ocr_image_with_config(image) == "managed OCR for exam-page.png"


def _write_test_epub(path: Path) -> bytes:
    """Create a minimal spine-ordered EPUB with cover and chapter images."""
    cover = b"cover-image-bytes"
    diagram = b"diagram-image-bytes"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>物理电子书</dc:title>
  </metadata>
  <manifest>
    <item id="cover" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="diagram" href="images/diagram.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>""",
        )
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>第一章 机械运动</h1>
<p>速度表示物体运动的快慢。</p>
<img src="../images/diagram.png" alt="速度图像"/>
</body></html>""",
        )
        archive.writestr("OEBPS/images/cover.jpg", cover)
        archive.writestr("OEBPS/images/diagram.png", diagram)
    return diagram


@pytest.mark.parametrize("suffix", [".pdf", ".pptx", ".docx", ".epub", ".html"])
def test_agent_compile_uses_verified_snapshot_and_preserves_original(tmp_path, monkeypatch, suffix):
    """All user-facing document formats must share the same source isolation."""
    wiki = tmp_path / ".wiki"
    source = tmp_path / f"important{suffix}"
    original = (b"valuable-source-data\x00" * 100_000) + suffix.encode()
    source.write_bytes(original)
    original_mtime = source.stat().st_mtime_ns

    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(
        compile_v2,
        "_read_agent_visible_source",
        lambda path: (f"snapshot-size={path.stat().st_size}", True),
    )

    result = compile_v2.create_agent_compile_task(str(source))

    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_mtime
    snapshots = list((wiki / "source" / "agent_inputs").rglob(source.name))
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.read_bytes() == original
    task = Path(result["agent_task"]).read_text(encoding="utf-8")
    assert str(snapshot) in task
    assert str(source) not in task
    assert "NEVER write to, replace, truncate" in task
    assert "NEVER use MarkItDown as the primary extractor for a scanned PDF" in task


def test_agent_snapshot_absorbs_accidental_133_byte_overwrite(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    source = tmp_path / "important.pdf"
    original = b"irreplaceable" * 200_000
    source.write_bytes(original)
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(compile_v2, "_read_agent_visible_source", lambda _path: ("", False))

    compile_v2.create_agent_compile_task(str(source))
    snapshot = next((wiki / "source" / "agent_inputs").rglob(source.name))

    # Simulate a misbehaving Agent/tool defeating chmod and writing its input.
    snapshot.chmod(0o600)
    snapshot.write_bytes(b"x" * 133)

    assert snapshot.stat().st_size == 133
    assert source.read_bytes() == original


def test_agent_directory_task_contains_only_snapshots(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    sources = tmp_path / "documents"
    sources.mkdir()
    originals = []
    for suffix in (".pdf", ".pptx", ".docx", ".html"):
        path = sources / f"important{suffix}"
        path.write_bytes((suffix.encode() + b"-original") * 100)
        originals.append(path)
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)

    result = compile_v2.create_agent_compile_task(str(sources))
    task = Path(result["agent_task"]).read_text(encoding="utf-8")

    for source in originals:
        assert str(source) not in task
        snapshots = list((wiki / "source" / "agent_inputs").rglob(source.name))
        assert len(snapshots) == 1
        assert snapshots[0].read_bytes() == source.read_bytes()


def test_compile_refuses_managed_output_as_source(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    page = wiki / "pages" / "important.md"
    page.parent.mkdir(parents=True)
    page.write_text("must not become its own output", encoding="utf-8")
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)

    with pytest.raises(ValueError, match="managed wiki output"):
        compile_v2.compile_path(str(page), mode="agent")

    assert page.read_text(encoding="utf-8") == "must not become its own output"


def test_readonly_copy_preserves_source_when_parser_truncates_copy_then_fails(tmp_path):
    source = tmp_path / "important.docx"
    original = b"office-package" * 10_000
    source.write_bytes(original)

    with pytest.raises(RuntimeError, match="parser failed"):
        with compile_v2._readonly_working_copy(source) as working_copy:
            working_copy.chmod(0o600)
            working_copy.write_bytes(b"x" * 133)
            raise RuntimeError("parser failed")

    assert source.read_bytes() == original


def test_readonly_copy_chains_original_error_when_source_also_changes(tmp_path):
    """When the body raises AND the source is mutated, the integrity error must
    chain the original error instead of masking it."""
    source = tmp_path / "doc.docx"
    source.write_bytes(b"original")

    with pytest.raises(RuntimeError, match="changed during read-only processing") as exc_info:
        with compile_v2._readonly_working_copy(source) as working_copy:
            working_copy.chmod(0o600)  # keep the temp copy deletable on cleanup
            # Mutate the real source out-of-band, then fail.
            source.write_bytes(b"tampered")
            raise RuntimeError("the real parse error")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "the real parse error"
    assert source.read_bytes() == b"tampered"


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
        p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root, max_depth=0)
    }
    depth_1 = {
        p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root, max_depth=1)
    }
    all_files = {p.relative_to(root).as_posix() for p in compile_v2.iter_source_files(root)}

    assert depth_0 == {"image.png", "root.md"}
    assert depth_1 == {"child/child.md", "image.png", "root.md"}
    assert all_files == {"child/child.md", "child/grandchild/deep.md", "image.png", "root.md"}


def test_paginated_documents_are_supported_sources(tmp_path):
    pdf = tmp_path / "brief.pdf"
    pptx = tmp_path / "deck.pptx"
    docx = tmp_path / "handbook.docx"
    pdf.write_bytes(b"%PDF fake")
    pptx.write_bytes(b"fake pptx")
    docx.write_bytes(b"fake docx")

    assert compile_v2.is_supported_source(pdf)
    assert compile_v2.is_supported_source(pptx)
    assert compile_v2.is_paginated_document_source(docx)


def test_epub_converts_spine_to_markdown_and_extracts_images(tmp_path, monkeypatch):
    source = tmp_path / "physics.epub"
    diagram = _write_test_epub(source)
    wiki = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)

    content, name = compile_v2.read_source_content(source)

    assert name == "physics.epub"
    assert "# 物理电子书" in content
    assert "## EPUB Section 1: 第一章 机械运动" in content
    assert "EPUB locator: `OEBPS/Text/chapter.xhtml`" in content
    assert "速度表示物体运动的快慢" in content
    image_targets = [
        compile_v2._clean_image_target(match.group("target"))
        for match in compile_v2.MARKDOWN_IMAGE_RE.finditer(content)
    ]
    assert len(image_targets) == 2
    extracted = [Path(target) for target in image_targets]
    assert all(path.is_file() for path in extracted)
    assert any(path.read_bytes() == diagram for path in extracted)
    markdown_files = list((wiki / "source" / "epub_markdown").rglob("physics.md"))
    assert len(markdown_files) == 1
    assert markdown_files[0].read_text(encoding="utf-8") == content


def test_epub_agent_task_persists_images_and_renders_markdown(tmp_path, monkeypatch):
    source = tmp_path / "physics.epub"
    original = _write_test_epub(source)
    source_bytes = source.read_bytes()
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(compile_v2, "PAGES_DIR", pages)

    result = compile_v2.create_agent_compile_task(str(source))
    task = Path(result["agent_task"]).read_text(encoding="utf-8")

    assert source.read_bytes() == source_bytes
    assert "## EPUB Section 1" in task
    assert "```text\n# 物理电子书" not in task
    copied = list((pages / "assets").rglob("*.png"))
    assert len(copied) == 1
    assert copied[0].read_bytes() == original
    # The agent task must show a portable relative link, not an absolute,
    # host-specific path the agent would copy verbatim into a wiki page.
    relative_link = os.path.relpath(copied[0], pages / "concepts").replace(os.sep, "/")
    assert relative_link in task
    assert str(copied[0].resolve()) not in task


def test_cited_epub_section_image_is_attached_to_compiled_page(tmp_path):
    pages = tmp_path / ".wiki" / "pages"
    page_path = pages / "concepts" / "speed.md"
    image = pages / "assets" / "book" / "speed.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"speed-image")
    source_content = (
        "# 物理电子书\n\n"
        "## EPUB Section 1: 第一章\n\n"
        "> EPUB locator: `OEBPS/Text/chapter.xhtml`\n\n"
        f"![速度图像]({image.resolve()})\n"
    )
    page_content = (
        "# 速度\n\n## 来源追溯\n\n"
        "- 原始资料：`physics.epub`\n"
        "- EPUB章节定位：EPUB Section 1\n"
    )

    rendered = compile_v2._attach_source_media(page_content, source_content, page_path)

    assert "## 来源图片" in rendered
    assert "../assets/book/speed.png" in rendered
    assert "EPUB Section 1" in rendered


def test_epub_traceability_uses_section_when_fixed_pages_do_not_exist():
    source_content = (
        "## EPUB Section 2: 机械运动\n\n" "> EPUB locator: `OEBPS/Text/motion.xhtml`\n\n正文。\n"
    )
    page_content = "# 速度\n\n内容。\n\n- EPUB Section 2\n"

    rendered = compile_v2._ensure_study_traceability(
        page_content,
        "physics.epub",
        source_content,
    )

    assert "- 页码：待核验" in rendered
    assert "重排格式无可靠固定页码" in rendered
    assert "EPUB Section 2（`OEBPS/Text/motion.xhtml`）" in rendered


def test_ocr_markdown_images_are_persisted_in_okf_bundle(tmp_path, monkeypatch):
    source = tmp_path / "ocr" / "textbook.md"
    image = source.parent / "images" / "apparatus.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-image")
    source.write_text("## Page 3\n\n![实验装置](images/apparatus.png)\n", encoding="utf-8")
    pages_dir = tmp_path / ".wiki" / "pages"
    monkeypatch.setattr(compile_v2, "PAGES_DIR", pages_dir)

    rewritten = compile_v2._persist_source_image_references(
        source.read_text(encoding="utf-8"), source
    )

    copied = list((pages_dir / "assets").rglob("apparatus.png"))
    assert len(copied) == 1
    assert copied[0].read_bytes() == b"png-image"
    # Persisted links must be portable: relative to the page location, never an
    # absolute, host-specific path that would break an exported bundle.
    relative_link = os.path.relpath(copied[0], pages_dir / "concepts").replace(os.sep, "/")
    assert relative_link in rewritten
    assert str(copied[0].resolve()) not in rewritten


def test_image_link_with_title_is_persisted(tmp_path, monkeypatch):
    source = tmp_path / "ocr" / "notes.md"
    image = source.parent / "images" / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-image")
    # A CommonMark title must not become part of the resolved filename.
    source.write_text('![实验装置](images/diagram.png "Figure 1: Apparatus")\n', encoding="utf-8")
    pages_dir = tmp_path / ".wiki" / "pages"
    monkeypatch.setattr(compile_v2, "PAGES_DIR", pages_dir)

    rewritten = compile_v2._persist_source_image_references(
        source.read_text(encoding="utf-8"), source
    )

    copied = list((pages_dir / "assets").rglob("diagram.png"))
    assert len(copied) == 1
    relative_link = os.path.relpath(copied[0], pages_dir / "concepts").replace(os.sep, "/")
    assert relative_link in rewritten
    assert "Figure 1" not in rewritten


def test_mineru_content_list_restores_page_boundaries(tmp_path):
    source = tmp_path / "physics.md"
    source.write_text(
        "# 第一章\n\n第一页内容。\n\n# 第二章\n\n第二页内容。\n",
        encoding="utf-8",
    )
    source.with_name("physics_content_list.json").write_text(
        json.dumps(
            [
                {"type": "text", "text": "第一章", "text_level": 1, "page_idx": 0},
                {"type": "text", "text": "第一页内容。", "page_idx": 0},
                {"type": "text", "text": "第二章", "text_level": 1, "page_idx": 1},
                {"type": "text", "text": "第二页内容。", "page_idx": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content, _ = compile_v2.read_source_content(source)

    assert content.startswith("## Page 1")
    assert content.count("## Page ") == 2
    assert content.index("## Page 2") < content.index("# 第二章")


def test_mineru_v2_content_list_restores_page_boundaries(tmp_path):
    source = tmp_path / "geography.md"
    image = tmp_path / "images" / "weather-map.png"
    image.parent.mkdir()
    image.write_bytes(b"map")
    source.write_text(
        "# 天气与气候\n\n天气符号。\n\n"
        "![](images/weather-map.png)\n\n# 世界气候\n\n气候分布。\n",
        encoding="utf-8",
    )
    source.with_name("geography_content_list_v2.json").write_text(
        json.dumps(
            [
                [
                    {
                        "type": "title",
                        "content": {
                            "title_content": [{"type": "text", "content": "天气与气候"}],
                            "level": 1,
                        },
                    },
                    {
                        "type": "image",
                        "content": {
                            "image_source": {"path": "images/weather-map.png"},
                            "image_caption": [
                                {"type": "text", "content": "某地天气图（教材原图）"}
                            ],
                        },
                    },
                ],
                [
                    {
                        "type": "title",
                        "content": {
                            "title_content": [{"type": "text", "content": "世界气候"}],
                            "level": 1,
                        },
                    }
                ],
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content, _ = compile_v2.read_source_content(source)

    assert content.startswith("## Page 1")
    assert content.count("## Page ") == 2
    assert content.index("## Page 2") < content.index("# 世界气候")
    assert "![某地天气图（教材原图）](images/weather-map.png)" in content


def test_agent_compile_uses_original_mineru_v2_sidecar_and_persists_images(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(compile_v2, "PAGES_DIR", pages)
    monkeypatch.setattr(compile_v2, "SCHEMA_PATH", wiki / "schema.md")

    source = tmp_path / "geography.md"
    image = tmp_path / "images" / "contour.png"
    image.parent.mkdir()
    image.write_bytes(b"contour")
    source.write_text(
        "# 等高线地形图\n\n等高线判读。\n\n![](images/contour.png)\n",
        encoding="utf-8",
    )
    source.with_name("geography_content_list_v2.json").write_text(
        json.dumps(
            [
                [
                    {
                        "type": "title",
                        "content": {
                            "title_content": [{"type": "text", "content": "等高线地形图"}],
                            "level": 1,
                        },
                    },
                    {
                        "type": "image",
                        "content": {"image_source": {"path": "images/contour.png"}},
                    },
                ]
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = compile_v2.create_agent_compile_task(str(source))
    manifest = json.loads(Path(result["todo"]).read_text(encoding="utf-8"))
    artifact = Path(manifest["items"][0]["artifact_path"]).read_text(encoding="utf-8")

    assert "## Page 1" in artifact
    assert "../assets/" in artifact
    assert len(list((pages / "assets").rglob("contour.png"))) == 1


def test_image_backed_markdown_creates_page_tasks_with_concrete_image_paths(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    monkeypatch.setattr(compile_v2, "PAGES_DIR", pages)
    monkeypatch.setattr(compile_v2, "SCHEMA_PATH", wiki / "schema.md")
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: True)
    ocr_calls: list[str] = []

    def fake_ovis_ocr(image_path: Path) -> str:
        ocr_calls.append(str(image_path))
        return (
            "## Page 1\n\n"
            "题目完整正文与条件均已识别。数学公式为 $x^2+y^2=1$，"
            "不得遗漏题号、选项、图注和单位。"
        )

    monkeypatch.setattr(compile_v2, "_ocr_image_with_config", fake_ovis_ocr)

    source = tmp_path / "content.md"
    images = tmp_path / "images"
    images.mkdir()
    (images / "page-001.jpg").write_bytes(b"one")
    (images / "page-002-a.jpg").write_bytes(b"two-a")
    (images / "page-002-b.jpg").write_bytes(b"two-b")
    source.write_text(
        "# 图片试卷\n\n## 第 1 页\n\n![](images/page-001.jpg)\n\n"
        "## 第 2 页\n\n![](images/page-002-a.jpg)\n![](images/page-002-b.jpg)\n",
        encoding="utf-8",
    )

    result = compile_v2.create_agent_compile_task(str(source))
    manifest = json.loads(Path(result["todo"]).read_text(encoding="utf-8"))
    task = Path(result["agent_task"]).read_text(encoding="utf-8")

    assert len(manifest["items"]) == 2
    assert [item["image_count"] for item in manifest["items"]] == [1, 2]
    assert all(item["requires_image_inspection"] for item in manifest["items"])
    assert all(Path(path).is_file() for item in manifest["items"] for path in item["image_paths"])
    assert len(ocr_calls) == 3
    assert all(item["ocr_backend"] == "ovis" for item in manifest["items"])
    assert all(item["ocr_status"] == "success" for item in manifest["items"])
    assert all(item["vision_fallback_allowed"] is False for item in manifest["items"])
    assert "`OvisOCR2` has already processed every source image" in task
    assert "vision_fallback_allowed=false" in task
    assert "vision_cli.py" not in task
    assert "Fallback precedence" not in task
    for item in manifest["items"]:
        artifact = Path(item["artifact_path"]).read_text(encoding="utf-8")
        assert "OvisOCR2 OCR Markdown (primary)" in artifact
        assert "$x^2+y^2=1$" in artifact
        assert "## Page 1" not in artifact
        assert "#### OvisOCR2 Page 1" in artifact


def test_cited_source_page_image_is_attached_to_compiled_page(tmp_path):
    pages_dir = tmp_path / ".wiki" / "pages"
    page_path = pages_dir / "concepts" / "density.md"
    images = []
    for page_number in (11, 12, 13):
        image = pages_dir / "assets" / "book" / f"page-{page_number:03d}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"page-{page_number}".encode())
        images.append(image)
    source_content = "\n".join(
        f"## Page {page_number}\n\n![Page {page_number}]({image.resolve()})\n\n正文。"
        for page_number, image in zip((11, 12, 13), images)
    )
    page_content = (
        "# 密度\n\n## 来源追溯\n\n" "- 原始资料：`八年级物理课本.pdf`\n- 页码：第 12 页\n"
    )

    rendered = compile_v2._attach_source_media(page_content, source_content, page_path)

    assert "## 来源图片" in rendered
    assert "../assets/book/page-012.png" in rendered
    assert "../assets/book/page-011.png" in rendered
    assert "../assets/book/page-013.png" in rendered
    assert "相邻页上下文" in rendered


def test_material_id_digits_are_not_mistaken_for_cited_pages():
    content = "## 来源追溯\n\n" "- 主要页码：`mat-中图版-七年级上册-2024秋版--e032993b#p89-98`\n"

    assert compile_v2._extract_cited_pages(content) == list(range(89, 99))


def test_attached_image_page_labels_do_not_expand_cited_page_range():
    content = (
        "## 来源追溯\n\n- 页码：mat-geo#p89-98\n\n"
        "## 来源图片\n\n"
        "![原始资料第 88 页（相邻页上下文）：天气符号](../assets/weather.png)\n"
        "![原始资料第 99 页（相邻页上下文）：气候图](../assets/climate.png)\n"
    )

    assert compile_v2._extract_cited_pages(content) == list(range(89, 99))


def test_study_page_keeps_knowledge_when_exact_page_is_unknown():
    source_content = "## Page 1\n\n正文一\n\n## Page 2\n\n正文二\n"

    rendered = compile_v2._ensure_study_traceability(
        "# 密度\n\n## 概述\n知识点。",
        "八年级物理课本.pdf",
        source_content,
    )

    assert "知识点" in rendered
    assert "页码：待核验" in rendered
    assert "候选页范围：第 1–2 页" in rendered
    assert "定位状态" in rendered


def test_study_traceability_records_source_and_exact_page():
    source_content = "## Page 1\n\n正文一\n\n## Page 2\n\n正文二\n"

    rendered = compile_v2._ensure_study_traceability(
        "# 密度\n\n原文定位在第 2 页。",
        "八年级物理课本.pdf",
        source_content,
    )

    assert "## 来源追溯" in rendered
    assert "`八年级物理课本.pdf`" in rendered
    assert "第 2 页" in rendered


def test_multi_page_ranges_expand_for_provenance_and_media():
    pages = compile_v2._extract_cited_pages("页码：第 10–12 页、第 15 页")

    assert pages == [10, 11, 12, 15]


def test_paginated_chunking_overlaps_previous_page_context():
    content = (
        "## Page 1\n\n第一页定义和条件。\n\n"
        "## Page 2\n\n第二页图片和推导。\n\n"
        "## Page 3\n\n第三页例题。\n"
    )

    chunks = compile_v2._split_by_headings(content, max_tokens=12, lang="zh")

    assert len(chunks) >= 2
    assert "Previous-page overlap" in chunks[1]
    assert "## Page 1" in chunks[1]
    assert "## Page 2" in chunks[1]


def test_same_knowledge_point_across_chunks_is_merged_without_losing_sources(monkeypatch):
    existing = {
        "id": "concepts/density",
        "facts": 1,
        "relationships": 0,
        "_content": (
            "---\ntype: concept\ntitle: 密度\n---\n# 密度\n\n" "## 来源追溯\n\n- 页码：第 10 页\n"
        ),
    }
    incoming = {
        "id": "concepts/density",
        "facts": 1,
        "relationships": 0,
        "_content": (
            "---\ntype: concept\ntitle: 密度\n---\n# 密度\n\n" "## 来源追溯\n\n- 页码：第 11 页\n"
        ),
    }
    monkeypatch.setattr(
        compile_v2,
        "llm_fuse_pages",
        lambda *_args: "# 密度\n\n跨页合并后的定义与图片说明。",
    )

    compile_v2._merge_cross_chunk_page(existing, incoming)

    assert "跨页合并后的定义与图片说明" in existing["_content"]
    assert "第 10 页" in existing["_content"]
    assert "第 11 页" in existing["_content"]
    assert existing["merged_chunks"] == 2


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
        "get_ocr_config",
        lambda: {"mode": "local", "backend": "paddle"},
    )
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


def test_ovis_pdf_compile_uses_one_document_run_and_keeps_page_images(tmp_path, monkeypatch):
    source = tmp_path / "handbook.pdf"
    source.write_bytes(b"%PDF fake")
    wiki_dir = tmp_path / ".wiki"
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki_dir)

    output_dir = wiki_dir / "source" / "document_images" / "handbook-test"
    output_dir.mkdir(parents=True)
    pages = [output_dir / "page-001.png", output_dir / "page-002.png"]
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
        "get_ocr_config",
        lambda: {"mode": "local", "backend": "ovis"},
    )
    calls: list[Path] = []

    def fake_ocr_pdf(path: Path) -> str:
        calls.append(path)
        return (
            "## Page 1\n\n第一页识别文本，内容足够用于有效性检查。"
            "\n\n## Page 2\n\n第二页识别文本，内容同样足够用于检查。"
        )

    monkeypatch.setattr(compile_v2, "_ocr_pdf_with_config", fake_ocr_pdf)
    monkeypatch.setattr(
        compile_v2,
        "_ocr_image_with_config",
        lambda _path: pytest.fail("OvisOCR2 PDF must not reload once per page"),
    )

    content = compile_v2._read_paginated_document_for_compile(source)

    assert len(calls) == 1
    assert "one model load" in content
    assert f"![Page 1]({pages[0].resolve()})" in content
    assert f"![Page 2]({pages[1].resolve()})" in content
    assert "第一页识别文本" in content
    assert "第二页识别文本" in content


def test_pdf_render_failure_uses_direct_ocr_before_markitdown(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    original = b"%PDF scanned source" * 10_000
    source.write_bytes(original)

    monkeypatch.setattr(
        compile_v2,
        "_render_paginated_document_to_images",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: True)

    def fake_direct_ocr(path):
        assert path != source
        assert path.read_bytes() == original
        return "# 完整 OCR\n\n" + "这是扫描 PDF 的正文。" * 20

    monkeypatch.setattr(compile_v2, "_ocr_pdf_with_config", fake_direct_ocr)
    monkeypatch.setattr(
        compile_v2,
        "_markitdown_to_markdown",
        lambda _path: pytest.fail("MarkItDown must not run after successful direct OCR"),
    )

    content = compile_v2._read_paginated_document_for_compile(source)

    assert "Direct OCR Succeeded" in content
    assert "这是扫描 PDF 的正文" in content
    assert "MarkItDown" in content  # explicit instruction not to replace OCR with it
    assert source.read_bytes() == original


def test_pdf_failed_ocr_labels_markitdown_as_partial_only(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF scanned source")
    monkeypatch.setattr(
        compile_v2,
        "_render_paginated_document_to_images",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )
    monkeypatch.setattr(compile_v2, "_ocr_backend_available", lambda: True)
    monkeypatch.setattr(
        compile_v2,
        "_ocr_pdf_with_config",
        lambda _path: (_ for _ in ()).throw(RuntimeError("mineru failed")),
    )
    monkeypatch.setattr(
        compile_v2,
        "_markitdown_to_markdown",
        lambda _path: "title and one official web link",
    )

    content = compile_v2._read_paginated_document_for_compile(source)

    assert "Direct OCR Failed" in content
    assert "mineru failed" in content
    assert "MarkItDown Partial Evidence (not compile-ready)" in content
    assert "Do not compile from this text alone" in content


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


def test_agent_mode_image_uses_ovis_without_invoking_vision(tmp_path, monkeypatch):
    """Agent mode: successful document OCR is primary and blocks vision routing."""
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
        lambda _image_path: "OvisOCR2 extracted complete exam text. " * 3,
    )

    content, readable = compile_v2._read_agent_visible_source(image)

    assert readable is True
    assert "Required path completed: OvisOCR2 OCR" in content
    assert "OvisOCR2 OCR Markdown (primary)" in content
    assert "Do not invoke vision-skill" in content
    assert "OvisOCR2 extracted complete exam text" in content
    assert "vision_cli.py" not in content
    assert "vision-skill (preferred)" not in content
    # Image link is present for the Agent.
    assert f"![{image.stem}]" in content


def test_agent_mode_image_without_ocr_keeps_native_fallback(tmp_path, monkeypatch):
    """Agent mode permits vision-skill only after OCR is unavailable."""
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
    assert "OCR was unavailable or insufficient" in content
    assert "vision-skill (OCR fallback only)" in content
    assert "Native capability" in content
    assert "did not return usable document text" in content
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
    assert "timestamp: 2026-07-05T00:00:00Z" in out
    # Inserted as a frontmatter key, not into the body.
    assert out.index("timestamp:") < out.index("---", 3)


def test_ensure_created_at_preserves_existing_date():
    page = "---\ntitle: Bar\ntimestamp: 2020-01-01T00:00:00Z\ntype: concept\n---\n\nbody"
    out = compile_v2._ensure_created_at(page, "2026-07-05")
    assert "timestamp: 2020-01-01T00:00:00Z" in out
    assert "2026-07-05" not in out  # not overwritten on update


def test_ensure_created_at_replaces_empty_value_without_duplicate():
    """Empty timestamp must be filled in place — no duplicate YAML keys."""
    page = "---\ntitle: Baz\ntimestamp:\ntype: concept\n---\n\nbody"
    out = compile_v2._ensure_created_at(page, "2026-07-05")
    assert out.count("timestamp:") == 1
    assert "timestamp: 2026-07-05T00:00:00Z" in out


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
