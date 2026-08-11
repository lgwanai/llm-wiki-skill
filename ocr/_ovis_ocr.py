#!/usr/bin/env python3
"""OvisOCR2 backend backed by the standalone Apple MLX project.

The OvisOCR2 runtime intentionally lives in its own virtual environment.  This
adapter invokes that environment instead of importing MLX into llm-wiki's
Python process, then validates its cropped-image references and normalizes the
output into the Markdown conventions consumed by the wiki compiler.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_PATH = Path("/Users/wuliang/workspace/OvisOCR2")
_PAGE_COMMENT_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)
_HTML_IMAGE_RE = re.compile(
    r"<img\s+[^>]*src=[\"'](?P<src>[^\"']+)[\"'][^>]*/?>",
    re.IGNORECASE,
)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\n]+)\)")
_BBOX_ASSET_RE = re.compile(
    r"(?P<src>(?:markdown/)?images/(?:page_\d{3}/)?" r"bbox_\d+_\d+_\d+_\d+\.jpg)",
    re.IGNORECASE,
)
_OFFICE_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx"}


class OvisOCR2:
    """Run the local OvisOCR2 MLX OCR pipeline through its own interpreter."""

    def __init__(
        self,
        project_path: str | Path = DEFAULT_PROJECT_PATH,
        python_path: str | Path | None = None,
        model_path: str | Path | None = None,
        dpi: int = 200,
        max_tokens: int = 8192,
        crop_padding_x: int = 0,
        crop_padding_y: int = 0,
        timeout_seconds: int = 3600,
    ) -> None:
        self.project_path = Path(project_path).expanduser().resolve()
        python_candidate = Path(
            python_path or self.project_path / ".venv" / "bin" / "python"
        ).expanduser()
        if not python_candidate.is_absolute():
            python_candidate = self.project_path / python_candidate
        # Keep the venv symlink path intact. Resolving it to the base Python
        # executable bypasses pyvenv.cfg and makes the MLX packages disappear.
        self.python_path = Path(os.path.abspath(python_candidate))

        model_candidate = Path(
            model_path or self.project_path / "models" / "OvisOCR2-MLX-4bit"
        ).expanduser()
        if not model_candidate.is_absolute():
            model_candidate = self.project_path / model_candidate
        self.model_path = model_candidate.resolve()
        self.script_path = self.project_path / "ocr_pdf.py"
        self.dpi = dpi
        self.max_tokens = max_tokens
        self.crop_padding_x = crop_padding_x
        self.crop_padding_y = crop_padding_y
        self.timeout_seconds = timeout_seconds

        if self.dpi < 1:
            raise ValueError("dpi must be at least 1")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        if not 0 <= self.crop_padding_x <= 250:
            raise ValueError("crop_padding_x must be between 0 and 250")
        if not 0 <= self.crop_padding_y <= 250:
            raise ValueError("crop_padding_y must be between 0 and 250")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1")

    @classmethod
    def from_config(cls, path: Path | None = None) -> OvisOCR2:
        """Create an adapter from the unified ``ocr.options`` config."""
        from scripts.config import get_ocr_config

        options = get_ocr_config().get("options", {})
        project_path = (
            options.get("project_path")
            or os.environ.get("OVIS_OCR_PROJECT_PATH")
            or DEFAULT_PROJECT_PATH
        )
        project = Path(project_path).expanduser()
        legacy_padding = options.get("crop_padding")
        return cls(
            project_path=project,
            python_path=(
                options.get("python_path")
                or os.environ.get("OVIS_OCR_PYTHON")
                or project / ".venv" / "bin" / "python"
            ),
            model_path=(
                options.get("model_path")
                or os.environ.get("OVIS_OCR_MODEL_PATH")
                or project / "models" / "OvisOCR2-MLX-4bit"
            ),
            dpi=int(options.get("dpi", get_ocr_config().get("pdf_dpi", 200))),
            max_tokens=int(options.get("max_tokens", 8192)),
            crop_padding_x=int(
                options.get(
                    "crop_padding_x",
                    legacy_padding if legacy_padding is not None else 0,
                )
            ),
            crop_padding_y=int(
                options.get(
                    "crop_padding_y",
                    legacy_padding if legacy_padding is not None else 0,
                )
            ),
            timeout_seconds=int(options.get("timeout_seconds", 3600)),
        )

    def _validate_runtime(self) -> None:
        missing: list[str] = []
        if not self.project_path.is_dir():
            missing.append(f"project directory: {self.project_path}")
        if not self.python_path.is_file():
            missing.append(f"Python interpreter: {self.python_path}")
        if not self.script_path.is_file():
            missing.append(f"OCR script: {self.script_path}")
        if not (self.model_path / "model.safetensors").is_file():
            missing.append(f"MLX model: {self.model_path}")
        if missing:
            raise RuntimeError(
                "OvisOCR2 runtime is incomplete; missing " + ", ".join(missing)
            )

    @staticmethod
    def _normalize_markdown(
        markdown: str,
        markdown_path: Path,
        *,
        absolute_assets: bool,
    ) -> str:
        """Normalize page markers and HTML crop tags for llm-wiki."""
        normalized = _PAGE_COMMENT_RE.sub(
            lambda match: f"## Page {match.group(1)}", markdown
        )

        def replace_image(match: re.Match[str]) -> str:
            target = match.group("src").strip()
            lowered = target.lower()
            if absolute_assets and not lowered.startswith(
                ("http://", "https://", "data:", "blob:", "file://")
            ):
                target = str((markdown_path.parent / target).resolve())
            return f"![OvisOCR2 crop]({target})"

        normalized = _HTML_IMAGE_RE.sub(replace_image, normalized)
        if absolute_assets:

            def absolutize_image(match: re.Match[str]) -> str:
                target = match.group("src").strip()
                lowered = target.lower()
                if not lowered.startswith(
                    ("http://", "https://", "data:", "blob:", "file://")
                ):
                    target = str((markdown_path.parent / target).resolve())
                return f"![{match.group('alt')}]({target})"

            normalized = _MARKDOWN_IMAGE_RE.sub(absolutize_image, normalized)
        return normalized.strip() + "\n"

    @staticmethod
    def _validate_crop_assets(markdown: str, markdown_path: Path) -> None:
        """Require every Ovis bbox reference to resolve to a non-empty file."""
        missing: list[Path] = []
        for match in _BBOX_ASSET_RE.finditer(markdown):
            target = markdown_path.parent / match.group("src")
            if not target.is_file() or target.stat().st_size == 0:
                missing.append(target)
        if missing:
            rendered = ", ".join(str(path) for path in dict.fromkeys(missing))
            raise RuntimeError(
                "OvisOCR2 Markdown references missing visual crops: " + rendered
            )

    def _run(
        self,
        input_path: str | Path,
        output_dir: Path,
        max_pages: int | None = None,
    ) -> Path:
        source = Path(input_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"OCR input not found: {source}")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if source.suffix.lower() in _OFFICE_SUFFIXES:
            with tempfile.TemporaryDirectory(prefix="ovis_office_") as temp_dir:
                converted = self._convert_office_to_pdf(source, Path(temp_dir))
                return self._run(converted, output_dir, max_pages=max_pages)
        self._validate_runtime()
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        command = [
            str(self.python_path),
            str(self.script_path),
            str(source),
            "--model",
            str(self.model_path),
            "--output-dir",
            str(output_dir),
            "--dpi",
            str(self.dpi),
            "--max-tokens",
            str(self.max_tokens),
            "--crop-padding-x",
            str(self.crop_padding_x),
            "--crop-padding-y",
            str(self.crop_padding_y),
        ]
        if max_pages is not None:
            command.extend(["--max-pages", str(max_pages)])

        logger.info("OvisOCR2 processing %s", source.name)
        try:
            result = subprocess.run(
                command,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"OvisOCR2 timed out after {self.timeout_seconds}s for {source}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise RuntimeError(f"OvisOCR2 failed for {source}: {detail}")

        markdown_path = output_dir / f"{source.stem}.md"
        if not markdown_path.is_file():
            candidates = sorted(output_dir.glob("*.md"))
            if not candidates:
                raise RuntimeError(
                    f"OvisOCR2 completed without a Markdown output in {output_dir}"
                )
            markdown_path = candidates[0]

        content = markdown_path.read_text(encoding="utf-8")
        self._validate_crop_assets(content, markdown_path)
        page_numbers = [int(value) for value in _PAGE_COMMENT_RE.findall(content)]
        markdown_path.write_text(
            self._normalize_markdown(content, markdown_path, absolute_assets=False),
            encoding="utf-8",
        )

        content_list = [{"page_idx": page_number - 1} for page_number in page_numbers]
        sidecar = markdown_path.with_name(f"{source.stem}_content_list.json")
        sidecar.write_text(
            json.dumps(content_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return markdown_path

    @staticmethod
    def _convert_office_to_pdf(source: Path, output_dir: Path) -> Path:
        """Convert Word/PowerPoint input for OvisOCR2's PDF/image interface."""
        macos_converter = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        converter = shutil.which("soffice") or shutil.which("libreoffice")
        if not converter and macos_converter.is_file():
            converter = str(macos_converter)
        if not converter:
            raise RuntimeError(
                "LibreOffice/soffice is required to OCR Word or PowerPoint with OvisOCR2"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                converter,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        candidates = sorted(output_dir.glob(f"{source.stem}*.pdf"))
        if result.returncode != 0 or not candidates:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise RuntimeError(f"LibreOffice conversion failed for {source}: {detail}")
        return candidates[0]

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: int | None = None,
    ) -> Path:
        """OCR a PDF and persist Markdown, page images, and cropped regions."""
        return self._run(pdf_path, output_dir, max_pages=max_pages)

    def ocr_image(self, image_path: str) -> str:
        """OCR one image while retaining OvisOCR2's cropped visual regions."""
        source = Path(image_path).expanduser().resolve()
        output_dir = source.parent / f"{source.stem}_ovisocr"
        markdown_path = self._run(source, output_dir, max_pages=1)
        return self._normalize_markdown(
            markdown_path.read_text(encoding="utf-8"),
            markdown_path,
            absolute_assets=True,
        )


def inspect_ovis_runtime(project_path: str | Path | None = None) -> dict[str, Any]:
    """Return a machine-readable readiness report for the standalone runtime."""
    if project_path is None:
        backend = OvisOCR2.from_config()
    else:
        backend = OvisOCR2(project_path=project_path)

    errors: list[str] = []
    warnings: list[str] = []
    for label, candidate, expected_type in (
        ("project directory", backend.project_path, "directory"),
        ("Python interpreter", backend.python_path, "file"),
        ("OCR script", backend.script_path, "file"),
        ("MLX model", backend.model_path / "model.safetensors", "file"),
    ):
        exists = (
            candidate.is_dir() if expected_type == "directory" else candidate.is_file()
        )
        if not exists:
            errors.append(f"Missing {label}: {candidate}")

    python_version: str | None = None
    dependencies_ready = False
    if backend.python_path.is_file():
        try:
            version = subprocess.run(
                [str(backend.python_path), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            python_version = (version.stdout or version.stderr).strip() or None
            dependency_check = subprocess.run(
                [
                    str(backend.python_path),
                    "-c",
                    "import fitz, PIL, mlx_vlm; print('ready')",
                ],
                cwd=backend.project_path if backend.project_path.is_dir() else None,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            dependencies_ready = dependency_check.returncode == 0
            if not dependencies_ready:
                detail = (dependency_check.stderr or dependency_check.stdout).strip()
                errors.append(f"OvisOCR2 Python dependencies are unavailable: {detail}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"Could not inspect OvisOCR2 interpreter: {exc}")

    return {
        "ready": not errors,
        "backend": "ovis",
        "project": str(backend.project_path),
        "python": {
            "executable": str(backend.python_path),
            "version": python_version,
        },
        "script": str(backend.script_path),
        "model": {
            "path": str(backend.model_path),
            "exists": (backend.model_path / "model.safetensors").is_file(),
        },
        "dependencies_ready": dependencies_ready,
        "errors": errors,
        "warnings": warnings,
        "repair_command": (
            f"uv pip install --python {backend.python_path} "
            f"-r {backend.project_path / 'requirements.txt'}"
        ),
    }
