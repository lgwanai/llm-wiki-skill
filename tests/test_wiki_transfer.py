from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from scripts import wiki_transfer

PROJECT = Path(__file__).resolve().parents[1]
PAGE = "---\ntype: Concept\ntitle: 晨星交接清单\n---\n\n晨星交接清单阐明新人交接流程。\n"


def _write(root: Path, name: str, content: str | bytes = PAGE) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def _wiki(wiki: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "scripts", *args],
        cwd=PROJECT,
        env={**os.environ, "LLM_WIKI_DIR": str(wiki)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_share_module_through_cli_and_search_in_recipient(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    pages = origin / "pages"
    page = PAGE + (
        "\n[转正](/concepts/probation.md#步骤)\n"
        "![流程图](../../assets/流程.png)\n"
        '[交接单](</assets/交接%20单.csv> "模板")\n'
    )
    _write(pages, "modules/入职/checklist.md", page)
    _write(pages, "concepts/probation.md")
    _write(pages, "assets/流程.png", b"image")
    _write(pages, "assets/交接 单.csv", b"csv")
    _write(pages, "assets/unrelated.png", b"unrelated")
    _write(pages, "sessions/internal.md")
    _write(pages, "index.md", "# Index\n")
    _write(pages, "log.md", "# Internal log\n")
    _write(origin, "source/private.pdf", b"raw source")
    _write(origin, "wiki_config.yaml", "api_key: test-key")
    archive = tmp_path / "onboarding.zip"

    exported = _wiki(
        origin, "export", str(archive), "--module", "modules/入职", "--page", "concepts/probation"
    )
    assert json.loads(exported.stdout)["exported"] == 2
    with ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            "modules/入职/checklist.md",
            "concepts/probation.md",
            "assets/流程.png",
            "assets/交接 单.csv",
        }

    receiver = tmp_path / "receiver"
    _write(receiver / "pages", "index.md", "# Recipient index\n")
    _write(receiver / "pages", "concepts/existing.md")
    assert json.loads(_wiki(receiver, "okf", "validate", str(archive)).stdout)["valid"]
    result = json.loads(_wiki(receiver, "import", str(archive)).stdout)
    assert (result["imported"], result["attachments"]) == (2, 2)
    dest = receiver / "pages"
    assert (dest / "modules/入职/checklist.md").read_bytes() == page.encode()
    assert (dest / "assets/流程.png").read_bytes() == b"image"
    assert (dest / "index.md").read_text() == "# Recipient index\n"
    assert (dest / "concepts/existing.md").exists()

    query = _wiki(receiver, "query", "流程图", "--no-synthesis")
    assert "modules/入职/checklist" in query.stdout

    repeat = json.loads(_wiki(receiver, "okf", "import", str(archive)).stdout)
    assert (repeat["imported"], repeat["attachments"], repeat["skipped"]) == (0, 0, 4)


def test_full_export_and_import_conflicts(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    pages = origin / "pages"
    _write(pages, "concepts/shared.md")
    _write(pages, "sessions/retrospective.md")
    _write(pages, "assets/figure.png", b"incoming")
    _write(pages, "log.md", "# Log\n")
    _write(pages, ".hidden", b"hidden")
    _write(origin, "ledger/project.csv", b"outside pages")
    archive = tmp_path / "all.zip"

    _wiki(origin, "okf", "export", str(archive))
    with ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            "concepts/shared.md",
            "sessions/retrospective.md",
            "assets/figure.png",
        }
    assert _wiki(origin, "export", str(archive), check=False).returncode == 1
    _wiki(origin, "export", str(archive), "--force")

    receiver = tmp_path / "receiver"
    dest = receiver / "pages"
    _write(dest, "assets/figure.png", b"recipient")
    rejected = _wiki(receiver, "import", str(archive), check=False)
    assert rejected.returncode == 1
    assert json.loads(rejected.stdout)["conflicts"] == ["assets/figure.png"]
    assert (dest / "assets/figure.png").read_bytes() == b"recipient"
    assert not (dest / "concepts/shared.md").exists()

    imported = json.loads(_wiki(receiver, "import", str(archive), "--force").stdout)
    assert imported["imported"] == 2
    assert imported["overwritten"] == 1
    assert (dest / "assets/figure.png").read_bytes() == b"incoming"


def test_import_refreshes_visual_index_when_only_attachments_change(tmp_path: Path) -> None:
    receiver = tmp_path / "receiver"
    page = PAGE + "\n![流程图](assets/figure.png)\n"
    _write(receiver / "pages", "checklist.md", page)
    _wiki(receiver, "query", "流程图", "--no-synthesis")
    cache = receiver / "graph" / ".visual_index.json"
    assert json.loads(cache.read_text())["records"][0]["image_path"] == ""

    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("checklist.md", page)
        bundle.writestr("assets/figure.png", b"figure")
    result = json.loads(_wiki(receiver, "import", str(archive)).stdout)
    assert (result["imported"], result["attachments"]) == (0, 1)

    _wiki(receiver, "query", "流程图", "--no-synthesis")
    assert json.loads(cache.read_text())["records"][0]["image_path"] == str(
        receiver / "pages" / "assets" / "figure.png"
    )


@pytest.mark.parametrize("name", ["../escape.md", "/escape.md", "C:/escape.md", "x\\escape.md"])
def test_zip_member_cannot_escape_destination(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("good.md", PAGE)
        bundle.writestr(name, PAGE)
    pages = tmp_path / "receiver" / "pages"
    with pytest.raises(ValueError, match="unsafe"):
        wiki_transfer.import_zip(pages, archive)
    assert not pages.exists()


def test_zip_rejects_links_and_invalid_pages_before_import(tmp_path: Path) -> None:
    archive = tmp_path / "invalid.zip"
    link = ZipInfo("assets/shortcut")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("good.md", PAGE)
        bundle.writestr(link, "/tmp/somewhere")
    pages = tmp_path / "receiver" / "pages"
    with pytest.raises(ValueError, match="non-regular"):
        wiki_transfer.import_zip(pages, archive, force=True)
    assert not pages.exists()

    with ZipFile(archive, "w") as bundle:
        bundle.writestr("concepts/", "")
        bundle.writestr("concepts/good.md", PAGE)
        bundle.writestr("bad.md", "missing frontmatter")
    assert not wiki_transfer.import_zip(pages, archive)["valid"]
    assert not pages.exists()

    with ZipFile(archive, "w") as bundle:
        bundle.writestr("concepts/", "")
        bundle.writestr("concepts/good.md", PAGE)
    outside = tmp_path / "outside"
    outside.mkdir()
    pages.mkdir(parents=True)
    try:
        (pages / "concepts").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("creating directory symlinks requires additional Windows privileges")
        raise
    with pytest.raises(ValueError, match="regular directory"):
        wiki_transfer.import_zip(pages, archive, force=True)
    assert not list(outside.iterdir())


def test_failed_write_restores_existing_files_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("assets/existing.png", b"replacement")
        bundle.writestr("modules/new.md", PAGE)
        bundle.writestr("zzz/failure.md", PAGE)
    pages = tmp_path / "receiver" / "pages"
    _write(pages, "assets/existing.png", b"original")
    link = os.link

    def fail_final_link(source: Path, destination: Path) -> None:
        if destination == pages / "zzz/failure.md":
            raise OSError("simulated write error")
        link(source, destination)

    monkeypatch.setattr(wiki_transfer.os, "link", fail_final_link)
    with pytest.raises(OSError, match="simulated write error"):
        wiki_transfer.import_zip(pages, archive, force=True)
    assert (pages / "assets/existing.png").read_bytes() == b"original"
    assert not (pages / "modules").exists()
    assert not (pages / "zzz").exists()


@pytest.mark.parametrize(
    "first, second",
    [
        ("concepts/Checklist.md", "concepts/checklist.md"),
        ("Concepts/a.md", "concepts/b.md"),
        ("concepts/café.md", "concepts/cafe\u0301.md"),
        ("concepts/leaf.md", "concepts/leaf.md/nested.md"),
    ],
)
def test_zip_rejects_nonportable_path_collisions(
    tmp_path: Path,
    first: str,
    second: str,
) -> None:
    archive = tmp_path / "collision.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr(first, PAGE)
        bundle.writestr(second, PAGE)
    pages = tmp_path / "receiver" / "pages"
    with pytest.raises(ValueError, match="conflicting bundle paths|file as parent"):
        wiki_transfer.import_zip(pages, archive)
    assert not pages.exists()
