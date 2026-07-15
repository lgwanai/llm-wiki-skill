"""Compatibility tests for the MinerU 3.4.4 Python API adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ocr import _mineru_ocr as mineru_ocr
from ocr._mineru_ocr import MinerUOCR


def test_mineru_uses_existing_configured_local_models(tmp_path: Path, monkeypatch) -> None:
    models = tmp_path / "models"
    models.mkdir()
    config = tmp_path / "mineru.json"
    config.write_text(
        json.dumps({"models-dir": {"pipeline": str(models), "vlm": ""}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mineru_ocr, "MINERU_JSON", config)
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.delenv("MINERU_MODEL_SOURCE", raising=False)

    mineru_ocr._ensure_mineru_config()

    assert mineru_ocr.os.environ["MINERU_TOOLS_CONFIG_JSON"] == str(config)
    assert mineru_ocr.os.environ["MINERU_MODEL_SOURCE"] == "local"


def test_mineru_preserves_explicit_model_source(tmp_path: Path, monkeypatch) -> None:
    models = tmp_path / "models"
    models.mkdir()
    config = tmp_path / "mineru.json"
    config.write_text(
        json.dumps({"models-dir": {"pipeline": str(models)}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mineru_ocr, "MINERU_JSON", config)
    monkeypatch.setenv("MINERU_MODEL_SOURCE", "modelscope")

    mineru_ocr._ensure_mineru_config()

    assert mineru_ocr.os.environ["MINERU_MODEL_SOURCE"] == "modelscope"


def test_mineru_344_do_parse_contract(tmp_path: Path, monkeypatch) -> None:
    """The adapter uses the public call shape shipped by MinerU 3.4.4."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7 test")
    output_dir = tmp_path / "output"
    calls: dict[str, object] = {}

    def read_fn(path: Path) -> bytes:
        calls["read_path"] = path
        return path.read_bytes()

    def do_parse(**kwargs: object) -> None:
        calls["parse"] = kwargs
        markdown = Path(str(kwargs["output_dir"])) / "paper" / str(kwargs["backend"]) / "paper.md"
        markdown.parent.mkdir(parents=True)
        markdown.write_text("# Parsed by MinerU 3.4.4\n", encoding="utf-8")

    mineru_module = ModuleType("mineru")
    cli_module = ModuleType("mineru.cli")
    common_module = ModuleType("mineru.cli.common")
    common_module.read_fn = read_fn  # type: ignore[attr-defined]
    common_module.do_parse = do_parse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mineru", mineru_module)
    monkeypatch.setitem(sys.modules, "mineru.cli", cli_module)
    monkeypatch.setitem(sys.modules, "mineru.cli.common", common_module)

    result = MinerUOCR(
        backend="pipeline",
        lang="ch",
        formula=True,
        table=False,
    ).ocr_pdf(str(source), output_dir, max_pages=2)

    assert result.read_text(encoding="utf-8") == "# Parsed by MinerU 3.4.4\n"
    assert calls["read_path"] == source
    parse_call = calls["parse"]
    assert isinstance(parse_call, dict)
    assert parse_call["pdf_file_names"] == ["paper"]
    assert parse_call["pdf_bytes_list"] == [b"%PDF-1.7 test"]
    assert parse_call["p_lang_list"] == ["ch"]
    assert parse_call["backend"] == "pipeline"
    assert parse_call["formula_enable"] is True
    assert parse_call["table_enable"] is False
    assert parse_call["start_page_id"] == 0
    assert parse_call["end_page_id"] == 1
    assert parse_call["f_dump_md"] is True
    assert parse_call["f_dump_content_list"] is True


def test_mineru_rejects_non_positive_page_limit(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7 test")

    with pytest.raises(ValueError, match="at least 1"):
        MinerUOCR().ocr_pdf(str(source), tmp_path / "output", max_pages=0)
