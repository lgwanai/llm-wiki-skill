"""Tests for installable CLI entry points."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import wiki
from ocr import cli as ocr_cli


def test_console_scripts_declared():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["build-system"]["build-backend"] == "setuptools.build_meta"

    scripts = data["project"]["scripts"]

    assert scripts["wiki"] == "scripts.wiki:main"
    assert scripts["llm-wiki"] == "scripts.wiki:main"


def test_wiki_help_entrypoint(capsys):
    with pytest.raises(SystemExit) as exc:
        old_argv = sys.argv
        try:
            sys.argv = ["wiki", "--help"]
            wiki.main()
        finally:
            sys.argv = old_argv

    assert exc.value.code == 0
    assert "LLM Wiki v2 CLI" in capsys.readouterr().out


def test_cmd_compile_passes_depth(monkeypatch):
    calls = []

    def fake_run_script(script_name: str, args: list[str]) -> tuple[int, str]:
        calls.append((script_name, args))
        return 0, "ok"

    monkeypatch.setattr(wiki, "run_script", fake_run_script)

    result = wiki.cmd_compile("docs", source_type="article", force=True, depth=1)

    assert result["success"] is True
    assert calls == [
        (
            "compile_v2.py",
            ["docs", "--type", "article", "--force", "--depth", "1"],
        )
    ]


def test_table_command_routes_to_table_script(monkeypatch, capsys):
    calls = []

    def fake_run_script(script_name: str, args: list[str]) -> tuple[int, str]:
        calls.append((script_name, args))
        return 0, "ok"

    monkeypatch.setattr(wiki, "run_script", fake_run_script)
    old_argv = sys.argv
    try:
        sys.argv = ["wiki", "table", "ask", "extracted_123", "total?", "--page", "2"]
        wiki.main()
    finally:
        sys.argv = old_argv

    assert calls == [
        ("table.py", ["ask", "extracted_123", "total?", "--page", "2", "--page-size", "20"])
    ]
    assert "ok" in capsys.readouterr().out


def test_dream_command_routes_to_worker(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        wiki,
        "run_script",
        lambda script_name, args: (calls.append((script_name, args)) or (0, "started")),
    )
    old_argv = sys.argv
    try:
        sys.argv = ["wiki", "dream", "--foreground"]
        wiki.main()
    finally:
        sys.argv = old_argv

    assert calls == [("dream.py", ["--foreground"])]
    assert "started" in capsys.readouterr().out


def test_ocr_output_dir_rejects_source_file_path(tmp_path):
    source = tmp_path / "slides.pdf"
    source.write_bytes(b"%PDF fake")

    with pytest.raises(ValueError, match="directory"):
        ocr_cli.resolve_output_dir(source, str(source), "slides_ocr")


def test_ocr_output_dir_rejects_source_like_requested_path(tmp_path):
    source = tmp_path / "slides.pdf"
    source.write_bytes(b"%PDF fake")

    with pytest.raises(ValueError, match="source-like"):
        ocr_cli.resolve_output_dir(source, str(tmp_path / "slides.pptx"), "slides_ocr")


def test_ocr_text_output_rejects_input_image_path(tmp_path):
    source = tmp_path / "diagram.png"
    source.write_bytes(b"image")

    with pytest.raises(ValueError, match="source file path"):
        ocr_cli.validate_output_file(source, source)
