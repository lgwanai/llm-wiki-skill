"""Tests for the standalone OvisOCR2 MLX adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ocr import _ovis_ocr as ovis_ocr
from ocr._ovis_ocr import OvisOCR2


def _runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "OvisOCR2"
    python = project / ".venv" / "bin" / "python"
    script = project / "ocr_pdf.py"
    model = project / "models" / "OvisOCR2-MLX-4bit"
    python.parent.mkdir(parents=True)
    model.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    script.write_text("", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"model")
    return project, python, model


def _fake_ocr_run(
    command: list[str], **_kwargs: object
) -> subprocess.CompletedProcess[str]:
    output_dir = Path(command[command.index("--output-dir") + 1])
    source = Path(command[2])
    output_dir.mkdir(parents=True, exist_ok=True)
    images = output_dir / "markdown" / "images"
    images.mkdir(parents=True)
    (images / "bbox_1_2_3_4.jpg").write_bytes(b"crop")
    (output_dir / f"{source.stem}.md").write_text(
        "<!-- page 1 -->\n\n正文与公式 $x^2+y^2=1$\n\n"
        "![坐标图](markdown/images/bbox_1_2_3_4.jpg)\n",
        encoding="utf-8",
    )
    return subprocess.CompletedProcess(command, 0, stdout="Done", stderr="")


def test_ovis_pdf_normalizes_pages_crops_and_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    project, python, model = _runtime(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF")
    output = tmp_path / "output"
    monkeypatch.setattr(ovis_ocr.subprocess, "run", _fake_ocr_run)

    markdown = OvisOCR2(project, python, model).ocr_pdf(
        str(source), output, max_pages=1
    )

    content = markdown.read_text(encoding="utf-8")
    assert "## Page 1" in content
    assert "$x^2+y^2=1$" in content
    assert "![坐标图](markdown/images/bbox_1_2_3_4.jpg)" in content
    sidecar = json.loads(
        (output / "paper_content_list.json").read_text(encoding="utf-8")
    )
    assert sidecar == [{"page_idx": 0}]


def test_ovis_image_keeps_crop_assets_with_absolute_links(
    tmp_path: Path, monkeypatch
) -> None:
    project, python, model = _runtime(tmp_path)
    source = tmp_path / "scan.png"
    source.write_bytes(b"image")
    monkeypatch.setattr(ovis_ocr.subprocess, "run", _fake_ocr_run)

    content = OvisOCR2(project, python, model).ocr_image(str(source))

    crop = tmp_path / "scan_ovisocr" / "markdown" / "images" / "bbox_1_2_3_4.jpg"
    assert crop.is_file()
    assert f"![坐标图]({crop.resolve()})" in content


def test_ovis_rejects_markdown_with_missing_crop(tmp_path: Path, monkeypatch) -> None:
    project, python, model = _runtime(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF")

    def fake_missing_crop(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text(
            "![缺失配图](markdown/images/bbox_10_20_30_40.jpg)\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="Done", stderr="")

    monkeypatch.setattr(ovis_ocr.subprocess, "run", fake_missing_crop)

    try:
        OvisOCR2(project, python, model).ocr_pdf(str(source), tmp_path / "output")
    except RuntimeError as exc:
        assert "missing visual crops" in str(exc)
        assert "bbox_10_20_30_40.jpg" in str(exc)
    else:
        raise AssertionError("Expected missing crop validation to fail")


def test_ovis_keeps_legacy_html_crop_compatibility(tmp_path: Path) -> None:
    markdown_path = tmp_path / "result.md"
    content = '<img src="markdown/images/bbox_1_2_3_4.jpg" />'

    normalized = OvisOCR2._normalize_markdown(
        content,
        markdown_path,
        absolute_assets=False,
    )

    assert normalized == "![OvisOCR2 crop](markdown/images/bbox_1_2_3_4.jpg)\n"


def test_ovis_rejects_non_positive_page_limit(tmp_path: Path) -> None:
    project, python, model = _runtime(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF")

    try:
        OvisOCR2(project, python, model).ocr_pdf(
            str(source), tmp_path / "out", max_pages=0
        )
    except ValueError as exc:
        assert "at least 1" in str(exc)
    else:
        raise AssertionError("Expected a positive page-limit validation error")


def test_ovis_converts_office_documents_before_ocr(tmp_path: Path, monkeypatch) -> None:
    project, python, model = _runtime(tmp_path)
    source = tmp_path / "slides.pptx"
    source.write_bytes(b"pptx")

    monkeypatch.setattr(
        ovis_ocr.shutil,
        "which",
        lambda name: "/usr/local/bin/soffice" if name == "soffice" else None,
    )

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "/usr/local/bin/soffice":
            output_dir = Path(command[command.index("--outdir") + 1])
            (output_dir / "slides.pdf").write_bytes(b"%PDF")
            return subprocess.CompletedProcess(
                command, 0, stdout="converted", stderr=""
            )
        return _fake_ocr_run(command, **kwargs)

    monkeypatch.setattr(ovis_ocr.subprocess, "run", fake_run)

    markdown = OvisOCR2(project, python, model).ocr_pdf(
        str(source), tmp_path / "output", max_pages=1
    )

    assert markdown.name == "slides.md"
    assert "## Page 1" in markdown.read_text(encoding="utf-8")
