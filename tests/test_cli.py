"""Tests for installable CLI entry points."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import wiki


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
