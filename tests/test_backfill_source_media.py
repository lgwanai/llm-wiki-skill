import json

import backfill_source_media


def test_backfill_restores_images_to_legacy_compiled_pages(tmp_path):
    wiki = tmp_path / ".wiki"
    page = wiki / "pages" / "concepts" / "weather.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "# 天气\n\n## 来源追溯\n\n"
        "- 原始资料：`geography.md`（material_id: `mat-geo`）\n"
        "- 页码：mat-geo#p1\n",
        encoding="utf-8",
    )
    source = tmp_path / "geography.md"
    image = tmp_path / "images" / "weather.png"
    image.parent.mkdir()
    image.write_bytes(b"weather")
    source.write_text("# 天气\n\n![](images/weather.png)\n", encoding="utf-8")
    source.with_name("geography_content_list_v2.json").write_text(
        json.dumps([[{
            "type": "image",
            "content": {
                "image_source": {"path": "images/weather.png"},
                "image_caption": [{"type": "text", "content": "天气符号"}],
            },
        }]], ensure_ascii=False),
        encoding="utf-8",
    )

    preview = backfill_source_media.backfill_source_media(
        wiki_dir=wiki,
        source=source,
        material_id="mat-geo",
    )
    assert preview["matched_pages"] == 1
    assert not (wiki / "pages" / "assets").exists()

    applied = backfill_source_media.backfill_source_media(
        wiki_dir=wiki,
        source=source,
        material_id="mat-geo",
        apply=True,
    )
    second_apply = backfill_source_media.backfill_source_media(
        wiki_dir=wiki,
        source=source,
        material_id="mat-geo",
        apply=True,
    )

    assert applied["updated_pages"] == 1
    assert applied["images_added"] == 1
    assert second_apply["updated_pages"] == 0
    assert second_apply["images_added"] == 0
    rendered = page.read_text(encoding="utf-8")
    assert "## 来源图片" in rendered
    assert "天气符号" in rendered
    target = rendered.split("](", 1)[1].split(")", 1)[0]
    assert (page.parent / target).resolve().is_file()
