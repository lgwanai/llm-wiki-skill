"""Tests for the isolated PaddleOCR-VL-1.6 Apple Silicon adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ocr import _paddleocr_vl as paddlevl
from ocr import paddleocr_vl_setup
from ocr._paddleocr_vl import PaddleOCRVL16
from ocr.paddleocr_vl_runner import _prefix_assets


def _runtime(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    python = tmp_path / ".venv" / "bin" / "python"
    model = tmp_path / "models" / "PaddleOCR-VL-1.6"
    layout = tmp_path / "models" / "PP-DocLayoutV3"
    runner = tmp_path / "paddleocr_vl_runner.py"
    python.parent.mkdir(parents=True)
    model.mkdir(parents=True)
    layout.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    runner.write_text("", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"model")
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (layout / "inference.pdiparams").write_bytes(b"layout")
    return python, model, layout, runner


def test_paddlevl_image_uses_isolated_worker_and_keeps_page_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python, model, layout, runner = _runtime(tmp_path)
    source = tmp_path / "scan.png"
    source.write_bytes(b"image")
    output = tmp_path / "output"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        stem = command[command.index("--source-stem") + 1]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{stem}.md").write_text(
            "## Page 1\n\n识别正文与公式 $x^2+y^2=1$。\n",
            encoding="utf-8",
        )
        (output_dir / f"{stem}_content_list.json").write_text(
            json.dumps([{"page_idx": 0}]), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="complete", stderr="")

    monkeypatch.setattr(paddlevl.subprocess, "run", fake_run)
    backend = PaddleOCRVL16(python, model, layout, runner)

    markdown = backend.ocr_pdf(str(source), output, max_pages=1)

    assert "识别正文" in markdown.read_text(encoding="utf-8")
    assert json.loads((output / "scan_content_list.json").read_text()) == [{"page_idx": 0}]
    assert calls[0][0] == str(python)
    assert calls[0][calls[0].index("--inference-backend") + 1] == "mlx-vlm-server"
    assert calls[0][calls[0].index("--input") + 1] == str(source.resolve())


def test_paddlevl_runtime_doctor_checks_versions_and_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python, model, layout, runner = _runtime(tmp_path)
    backend = PaddleOCRVL16(python, model, layout, runner)
    payload = {
        "python": "3.12.13",
        "packages": {
            "paddleocr": "3.7.0",
            "paddlepaddle": "3.3.1",
            "paddlex": "3.7.2",
            "mlx-vlm": "0.6.15",
            "mlx": "0.32.1",
        },
    }
    monkeypatch.setattr(
        paddlevl.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    report = paddlevl.inspect_paddleocr_vl_runtime(backend)

    assert report["ready"] is True
    assert report["pipeline"] == "PaddleOCR-VL-1.6"
    assert report["packages"]["mlx-vlm"] == "0.6.15"
    assert report["model"]["layout_path"] == str(layout)


def test_paddlevl_rejects_non_positive_page_limit(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"image")

    with pytest.raises(ValueError, match="at least 1"):
        PaddleOCRVL16().ocr_pdf(str(source), tmp_path / "out", max_pages=0)


def test_paddlevl_runner_rewrites_page_local_assets() -> None:
    content = '<img src="imgs/figure.jpg" />\n![plot](imgs/plot.png)'

    rewritten = _prefix_assets(content, "page-002")

    assert 'src="page-002/imgs/figure.jpg"' in rewritten
    assert "](page-002/imgs/plot.png)" in rewritten


def test_paddlevl_setup_restores_modelscope_staged_file(tmp_path: Path) -> None:
    model = tmp_path / "PaddleOCR-VL-1.6"
    staged = model / "._tmp"
    staged.mkdir(parents=True)
    (staged / "preprocessor_config.json").write_text("{}", encoding="utf-8")

    paddleocr_vl_setup._restore_staged_files(model)

    assert (model / "preprocessor_config.json").read_text(encoding="utf-8") == "{}"
