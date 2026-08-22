#!/usr/bin/env python3
"""PaddleOCR-VL-1.6 backend for Apple Silicon.

The runtime is intentionally isolated in its own virtual environment.  The
adapter renders paginated inputs in the main process, then invokes one worker
process so PaddleOCR's layout model and the MLX VLM are loaded only once per
document.
"""

from __future__ import annotations

import json
import logging
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_ROOT = Path.home() / "workspace" / "PaddleOCR-VL-1.6-MLX"
DEFAULT_PYTHON_PATH = DEFAULT_RUNTIME_ROOT / ".venv" / "bin" / "python"
DEFAULT_MODEL_PATH = Path.home() / ".paddlex" / "official_models" / "PaddleOCR-VL-1.6"
DEFAULT_LAYOUT_MODEL_PATH = Path.home() / ".paddlex" / "official_models" / "PP-DocLayoutV3"
DEFAULT_RUNNER_PATH = Path(__file__).with_name("paddleocr_vl_runner.py")
DEFAULT_SETUP_PATH = Path(__file__).with_name("paddleocr_vl_setup.py")


class PaddleOCRVL16:
    """Run PaddleOCR-VL-1.6 with PP-DocLayoutV3 and MLX-VLM."""

    def __init__(
        self,
        python_path: str | Path = DEFAULT_PYTHON_PATH,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        layout_model_path: str | Path = DEFAULT_LAYOUT_MODEL_PATH,
        runner_path: str | Path = DEFAULT_RUNNER_PATH,
        inference_backend: str = "mlx-vlm-server",
        server_url: str = "",
        device: str = "cpu",
        max_new_tokens: int = 4096,
        timeout_seconds: int = 1200,
        dpi: int = 200,
    ) -> None:
        self.python_path = Path(python_path).expanduser()
        self.model_path = Path(model_path).expanduser()
        self.layout_model_path = Path(layout_model_path).expanduser()
        self.runner_path = Path(runner_path).expanduser()
        self.inference_backend = inference_backend
        self.server_url = server_url
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.timeout_seconds = timeout_seconds
        self.dpi = dpi

    @classmethod
    def from_config(cls, path: Path | None = None) -> PaddleOCRVL16:
        """Create the backend from standalone OCR options."""
        from ocr.config import get_model_config

        config = get_model_config("paddlevl", path)
        options = config.get("options", {})
        return cls(
            python_path=options.get("python_path", DEFAULT_PYTHON_PATH),
            model_path=options.get("model_path", DEFAULT_MODEL_PATH),
            layout_model_path=options.get("layout_model_path", DEFAULT_LAYOUT_MODEL_PATH),
            runner_path=options.get("runner_path", DEFAULT_RUNNER_PATH),
            inference_backend=options.get("inference_backend", "mlx-vlm-server"),
            server_url=options.get("server_url", ""),
            device=options.get("device", "cpu"),
            max_new_tokens=int(options.get("max_new_tokens", 4096)),
            timeout_seconds=int(options.get("timeout_seconds", 1200)),
            dpi=int(options.get("dpi", config.get("pdf_dpi", 200))),
        )

    def _validate_runtime(self) -> None:
        missing = [
            str(path)
            for path in (
                self.python_path,
                self.model_path,
                self.layout_model_path,
                self.runner_path,
            )
            if not path.exists()
        ]
        if missing:
            raise RuntimeError(
                "PaddleOCR-VL-1.6 runtime is incomplete; missing "
                + ", ".join(missing)
                + ". Run `wiki ocr --doctor --json` for the repair command."
            )

    def _render_pdf(self, source: Path, pages_dir: Path, max_pages: int | None) -> list[Path]:
        """Render PDF pages to deterministic PNG files."""
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PyMuPDF is required for PaddleOCR-VL PDF input.") from exc

        pages_dir.mkdir(parents=True, exist_ok=True)
        images: list[Path] = []
        with fitz.open(str(source)) as document:
            page_count = min(document.page_count, max_pages or document.page_count)
            matrix = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            for page_index in range(page_count):
                image_path = pages_dir / f"page-{page_index + 1:03d}.png"
                document.load_page(page_index).get_pixmap(matrix=matrix, alpha=False).save(
                    str(image_path)
                )
                images.append(image_path)
        return images

    @staticmethod
    def _convert_office(source: Path, work_dir: Path) -> Path:
        """Convert Word or PowerPoint input to PDF with LibreOffice."""
        soffice = shutil.which("soffice")
        if not soffice:
            raise RuntimeError("LibreOffice/soffice is required to OCR Word or PowerPoint.")
        completed = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work_dir),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        candidates = sorted(work_dir.glob(f"{source.stem}*.pdf"))
        if completed.returncode != 0 or not candidates:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"LibreOffice conversion failed: {detail}")
        return candidates[0]

    def _run(self, inputs: list[Path], output_dir: Path, source_stem: str) -> Path:
        """Run one isolated PaddleOCR-VL worker for all ordered page images."""
        self._validate_runtime()
        if not inputs:
            raise RuntimeError("PaddleOCR-VL received zero pages.")
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.python_path),
            str(self.runner_path),
            "--output-dir",
            str(output_dir),
            "--source-stem",
            source_stem,
            "--model-path",
            str(self.model_path),
            "--layout-model-path",
            str(self.layout_model_path),
            "--inference-backend",
            self.inference_backend,
            "--device",
            self.device,
            "--max-new-tokens",
            str(self.max_new_tokens),
        ]
        if self.server_url:
            command.extend(["--server-url", self.server_url])
        for input_path in inputs:
            command.extend(["--input", str(input_path)])

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"PaddleOCR-VL-1.6 failed: {detail}")
        markdown = output_dir / f"{source_stem}.md"
        if not markdown.is_file():
            raise RuntimeError(f"PaddleOCR-VL-1.6 completed without Markdown: {markdown}")
        return markdown

    def ocr_pdf(
        self,
        pdf_path: str,
        output_dir: Path,
        max_pages: int | None = None,
    ) -> Path:
        """OCR a PDF, Office document, or image into page-bounded Markdown."""
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        source = Path(pdf_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        output_dir = Path(output_dir).expanduser()

        suffix = source.suffix.lower()
        pages_dir = output_dir / "rendered_pages"
        if suffix in {".doc", ".docx", ".ppt", ".pptx"}:
            output_dir.mkdir(parents=True, exist_ok=True)
            converted = self._convert_office(source, output_dir)
            inputs = self._render_pdf(converted, pages_dir, max_pages)
        elif suffix == ".pdf":
            inputs = self._render_pdf(source, pages_dir, max_pages)
        else:
            inputs = [source]
        logger.info("PaddleOCR-VL-1.6 processing %s page(s)", len(inputs))
        return self._run(inputs, output_dir, source.stem)

    def ocr_image(self, image_path: str) -> str:
        """OCR one image while retaining generated figure assets."""
        source = Path(image_path).expanduser().resolve()
        output_dir = source.with_name(f"{source.stem}_paddleocr_vl")
        markdown = self.ocr_pdf(str(source), output_dir, max_pages=1)
        return markdown.read_text(encoding="utf-8")


def inspect_paddleocr_vl_runtime(
    backend: PaddleOCRVL16 | None = None,
) -> dict[str, Any]:
    """Return a machine-readable readiness report for the isolated runtime."""
    runtime = backend or PaddleOCRVL16.from_config()
    errors: list[str] = []
    warnings: list[str] = []

    for label, path in (
        ("Python interpreter", runtime.python_path),
        ("runner", runtime.runner_path),
        ("PaddleOCR-VL-1.6 model", runtime.model_path),
        ("PP-DocLayoutV3 model", runtime.layout_model_path),
    ):
        if not path.exists():
            errors.append(f"{label} does not exist: {path}")

    required_model_files = (
        runtime.model_path / "model.safetensors",
        runtime.model_path / "config.json",
        runtime.model_path / "preprocessor_config.json",
        runtime.layout_model_path / "inference.pdiparams",
    )
    for path in required_model_files:
        if not path.is_file():
            errors.append(f"Required model file is missing: {path}")

    versions: dict[str, str | None] = {}
    python_version: str | None = None
    if runtime.python_path.is_file():
        probe = (
            "import importlib.metadata as m,json,platform;"
            "names=['paddleocr','paddlepaddle','paddlex','mlx-vlm','mlx'];"
            "print(json.dumps({'python':platform.python_version(),"
            "'packages':{n:m.version(n) for n in names}}))"
        )
        try:
            completed = subprocess.run(
                [str(runtime.python_path), "-c", probe],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if completed.returncode != 0:
                errors.append(
                    "Could not import PaddleOCR-VL runtime packages: "
                    + (completed.stderr.strip() or completed.stdout.strip())
                )
            else:
                payload = json.loads(completed.stdout.strip().splitlines()[-1])
                python_version = payload.get("python")
                versions = payload.get("packages", {})
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Could not inspect PaddleOCR-VL interpreter: {exc}")

    if platform.machine() != "arm64":
        warnings.append(
            "MLX acceleration requires Apple Silicon arm64; use inference_backend=native."
        )

    venv_path = runtime.python_path.parent.parent
    repair_command = (
        f"uv venv --python 3.12 {shlex.quote(str(venv_path))} && "
        f"uv pip install --python {shlex.quote(str(runtime.python_path))} "
        "'paddlepaddle==3.3.1' 'paddleocr[doc-parser]==3.7.0' "
        "'mlx-vlm>=0.6.3,<0.7' && "
        f"{shlex.quote(str(runtime.python_path))} {shlex.quote(str(DEFAULT_SETUP_PATH))} "
        f"--model-path {shlex.quote(str(runtime.model_path))} "
        f"--layout-model-path {shlex.quote(str(runtime.layout_model_path))}"
    )
    return {
        "ready": not errors,
        "backend": "paddlevl",
        "pipeline": "PaddleOCR-VL-1.6",
        "inference_backend": runtime.inference_backend,
        "machine": platform.machine(),
        "python": {
            "executable": str(runtime.python_path),
            "version": python_version,
        },
        "packages": versions,
        "model": {
            "path": str(runtime.model_path),
            "layout_path": str(runtime.layout_model_path),
        },
        "runner": str(runtime.runner_path),
        "errors": errors,
        "warnings": warnings,
        "repair_command": repair_command,
    }
