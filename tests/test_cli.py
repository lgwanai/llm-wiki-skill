"""Tests for installable CLI entry points."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import cli as ocr_cli
from scripts import wiki


def test_ocr_module_entry_survives_spawn_without_package_shadowing(tmp_path):
    """A fresh spawn worker must resolve ``ocr/``, never ``scripts/ocr.py``."""
    project_root = Path(__file__).resolve().parent.parent
    probe = tmp_path / "spawn_probe.py"
    probe.write_text(
        """
import multiprocessing
from pathlib import Path

from ocr._mineru_ocr import MinerUOCR


def worker(queue):
    import ocr
    import ocr.cli

    queue.put(str(Path(ocr.__file__).resolve()))


if __name__ == "__main__":
    MinerUOCR.from_config()
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=worker, args=(queue,))
    process.start()
    process.join(30)
    if process.exitcode != 0:
        raise SystemExit(process.exitcode or 1)
    resolved = queue.get(timeout=5)
    if not resolved.endswith("/ocr/__init__.py"):
        raise SystemExit(f"wrong ocr package: {resolved}")
""".lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{project_root}{os.pathsep}{existing}" if existing else str(project_root)
    )

    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_console_scripts_declared():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["build-system"]["build-backend"] == "setuptools.build_meta"

    scripts = data["project"]["scripts"]

    assert scripts["wiki"] == "scripts.wiki:main"
    assert scripts["llm-wiki"] == "scripts.wiki:main"
    assert scripts["ocr"] == "ocr.cli:main"
    assert scripts["llm-wiki-ocr"] == "ocr.cli:main"


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
        lambda script_name, args: calls.append((script_name, args)) or (0, "started"),
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


def test_wiki_ocr_routes_to_canonical_cli(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(ocr_cli, "main", lambda args=None: calls.append(args or []) or 0)
    old_argv = sys.argv
    try:
        sys.argv = ["wiki", "ocr", "book.pdf", "--smoke-pages", "3", "--json"]
        wiki.main()
    finally:
        sys.argv = old_argv

    assert calls == [["book.pdf", "--smoke-pages", "3", "--json"]]


def test_wiki_ocr_reports_cleanly_when_ocr_unavailable(monkeypatch, capsys):
    """If the ocr package cannot be imported, the user gets a clear message and
    a non-zero exit instead of an unhandled ImportError traceback."""
    # Force `from ocr.cli import main` to fail (None in sys.modules -> ImportError).
    monkeypatch.setitem(sys.modules, "ocr.cli", None)
    old_argv = sys.argv
    sys.argv = ["wiki", "ocr", "book.pdf", "--json"]
    try:
        with pytest.raises(SystemExit) as exc_info:
            wiki.main()
    finally:
        sys.argv = old_argv

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "not available" in err.lower()
    assert "Install OCR dependencies" in err


def test_ocr_manifest_records_page_coverage_and_images(tmp_path, monkeypatch):
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF test")
    output = tmp_path / "output"
    output.mkdir()
    markdown = output / "book.md"
    markdown.write_text("# Book\n", encoding="utf-8")
    (output / "book_content_list.json").write_text(
        json.dumps([{"page_idx": 0}, {"page_idx": 1}, {"page_idx": 2}]),
        encoding="utf-8",
    )
    image = output / "images" / "figure.png"
    image.parent.mkdir()
    image.write_bytes(b"png")
    monkeypatch.setattr(ocr_cli, "_pdf_page_count", lambda path: 8)

    manifest, data = ocr_cli.write_ocr_manifest(
        source,
        markdown,
        backend="paddle",
        max_pages=3,
        elapsed_seconds=1.25,
    )

    assert manifest.name == "book_ocr_manifest.json"
    assert data["status"] == "complete"
    assert data["source_pages"] == 8
    assert data["parsed_pages"] == [1, 2, 3]
    assert data["coverage_complete"] is True
    assert data["images"] == [str(image.resolve())]


def test_ocr_manifest_uses_max_pages_when_source_pages_unknown(tmp_path, monkeypatch):
    """When the PDF page count is unknown but max_pages is set, fall back to
    max_pages so coverage_complete is computed rather than left null (which
    would silently yield status "complete")."""
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF test")
    output = tmp_path / "output"
    output.mkdir()
    markdown = output / "book.md"
    markdown.write_text("# Book\n", encoding="utf-8")
    (output / "book_content_list.json").write_text(
        json.dumps([{"page_idx": 0}, {"page_idx": 1}, {"page_idx": 2}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(ocr_cli, "_pdf_page_count", lambda path: None)

    _manifest, data = ocr_cli.write_ocr_manifest(
        source,
        markdown,
        backend="paddle",
        max_pages=3,
        elapsed_seconds=1.0,
    )

    assert data["source_pages"] is None
    assert data["expected_pages"] == 3
    assert data["parsed_pages"] == [1, 2, 3]
    assert data["coverage_complete"] is True
    assert data["status"] == "complete"


def test_ocr_batch_output_gives_each_source_its_own_subdir(tmp_path, monkeypatch):
    """In batch mode a shared --output must not collide: each source lands in
    its own {stem}_ocr subdirectory so MinerU results don't overwrite each other."""
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    for name in ("a.pdf", "b.pdf"):
        (batch_dir / name).write_bytes(b"%PDF fake")

    recorded_outputs: list[Path] = []

    class _FakeOcr:
        def ocr_pdf(self, source, output, max_pages=None):  # noqa: ANN001
            stem = Path(source).stem
            out_dir = Path(output)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{stem}.md").write_text("# page\n", encoding="utf-8")
            (out_dir / f"{stem}_content_list.json").write_text(
                json.dumps([{"page_idx": 0}]), encoding="utf-8"
            )
            recorded_outputs.append(out_dir)
            return str(out_dir / f"{stem}.md")

    monkeypatch.setattr(ocr_cli, "_load_backend", lambda name: _FakeOcr())
    monkeypatch.setattr(ocr_cli, "_pdf_page_count", lambda path: 2)

    code = ocr_cli.main(["--batch", str(batch_dir), "--output", str(out), "--backend", "paddle"])

    assert code == 0
    assert len(recorded_outputs) == 2
    assert {p.name for p in recorded_outputs} == {"a_ocr", "b_ocr"}
    assert all(p.parent == out for p in recorded_outputs)


def test_ocr_doctor_exit_code_is_machine_readable(monkeypatch, capsys):
    report = {
        "ready": False,
        "errors": ["wrong version"],
        "warnings": [],
    }
    monkeypatch.setattr(ocr_cli, "inspect_mineru_runtime", lambda: report)

    code = ocr_cli.main(["--doctor", "--json", "--backend", "mineru"])

    assert code == 2
    assert json.loads(capsys.readouterr().out)["errors"] == ["wrong version"]


def test_ocr_parser_accepts_paddlevl_as_default(monkeypatch):
    monkeypatch.setattr(
        ocr_cli,
        "get_ocr_config",
        lambda: {"mode": "local", "backend": "paddlevl"},
    )

    args = ocr_cli.build_parser().parse_args(["--doctor"])

    assert args.backend == "paddlevl"
