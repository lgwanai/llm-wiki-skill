"""Lazy registry for OCR models exposed by the standalone CLI."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    """User-facing metadata and lazy factory for an OCR backend."""

    key: str
    name: str
    description: str
    factory: Callable[[], Any]
    probe: Callable[[], tuple[bool, str]]


def _path_probe(path: Path, label: str) -> tuple[bool, str]:
    exists = path.expanduser().exists()
    detail = f"{label}: {path.expanduser()}" if exists else f"missing {label}: {path.expanduser()}"
    return exists, detail


def _paddlevl() -> Any:
    from ocr._paddleocr_vl import PaddleOCRVL16

    return PaddleOCRVL16.from_config()


def _probe_paddlevl() -> tuple[bool, str]:
    from ocr._paddleocr_vl import inspect_paddleocr_vl_runtime

    report = inspect_paddleocr_vl_runtime()
    detail = "ready" if report["ready"] else "; ".join(report["errors"])
    return bool(report["ready"]), detail


def _ovis() -> Any:
    from ocr._ovis_ocr import OvisOCR2

    return OvisOCR2.from_config()


def _probe_ovis() -> tuple[bool, str]:
    from ocr._ovis_ocr import inspect_ovis_runtime

    report = inspect_ovis_runtime()
    detail = "ready" if report["ready"] else "; ".join(report["errors"])
    return bool(report["ready"]), detail


def _mineru() -> Any:
    from ocr._mineru_ocr import MinerUOCR

    return MinerUOCR.from_config()


def _probe_mineru() -> tuple[bool, str]:
    installed = importlib.util.find_spec("mineru") is not None
    return installed, "installed" if installed else "Python package mineru is not installed"


def _deepseek() -> Any:
    from ocr._deepseek_ocr2 import DeepSeekOCR2

    return DeepSeekOCR2.from_config()


def _probe_deepseek() -> tuple[bool, str]:
    from ocr._deepseek_ocr2 import DEFAULT_MODEL_PATH
    from ocr.config import get_model_config

    options = get_model_config("deepseek").get("options", {})
    model_path = Path(options.get("model_path", DEFAULT_MODEL_PATH))
    missing = [name for name in ("torch", "transformers") if importlib.util.find_spec(name) is None]
    if missing:
        return False, f"missing Python package(s): {', '.join(missing)}"
    return _path_probe(model_path, "model")


def _logics() -> Any:
    from ocr._logics_parsing import LogicsParsingOCR

    return LogicsParsingOCR.from_config()


def _probe_logics() -> tuple[bool, str]:
    from ocr._logics_parsing import DEFAULT_MODEL_PATH
    from ocr.config import get_model_config

    options = get_model_config("logics").get("options", {})
    model_path = Path(options.get("model_path", DEFAULT_MODEL_PATH))
    missing = [name for name in ("torch", "transformers") if importlib.util.find_spec(name) is None]
    if missing:
        return False, f"missing Python package(s): {', '.join(missing)}"
    return _path_probe(model_path, "model")


def _paddle() -> Any:
    from ocr._paddle_ocr import PaddleOCRWrapper

    return PaddleOCRWrapper.from_config()


def _probe_paddle() -> tuple[bool, str]:
    installed = importlib.util.find_spec("paddleocr") is not None
    return installed, "installed" if installed else "Python package paddleocr is not installed"


def _api() -> Any:
    from ocr._ocr_api import OCRApiBackend

    return OCRApiBackend.from_config()


def _probe_api() -> tuple[bool, str]:
    from ocr.config import get_model_config

    config = get_model_config("api")
    configured = bool(config.get("api_url") or config.get("api_provider"))
    return configured, "configured" if configured else "api_url or api_provider is not configured"


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "paddlevl",
        "PaddleOCR-VL-1.6",
        "Apple Silicon optimized document OCR",
        _paddlevl,
        _probe_paddlevl,
    ),
    ModelSpec("ovis", "OvisOCR2", "MLX document OCR with region crops", _ovis, _probe_ovis),
    ModelSpec(
        "mineru",
        "MinerU",
        "Document parsing with formulas and tables",
        _mineru,
        _probe_mineru,
    ),
    ModelSpec(
        "deepseek",
        "DeepSeek-OCR-2",
        "Vision-language document OCR",
        _deepseek,
        _probe_deepseek,
    ),
    ModelSpec("logics", "Logics-Parsing-v2", "Qwen3-VL document parsing", _logics, _probe_logics),
    ModelSpec(
        "paddle",
        "PaddleOCR PP-OCRv5",
        "Classic multilingual PaddleOCR",
        _paddle,
        _probe_paddle,
    ),
    ModelSpec("api", "OpenAI-compatible API", "Remote vision/OCR API", _api, _probe_api),
)


def get_model(name: str) -> ModelSpec:
    """Resolve a model key or raise a useful error."""
    for model in MODELS:
        if model.key == name:
            return model
    choices = ", ".join(model.key for model in MODELS)
    raise ValueError(f"unsupported OCR model {name!r}; choose one of: {choices}")


def create_backend(name: str | None = None) -> Any:
    """Instantiate the selected backend without importing other runtimes."""
    from ocr.config import get_default_model

    return get_model(name or get_default_model()).factory()


def list_models(check: bool = False) -> list[dict[str, Any]]:
    """Return registry metadata, optionally probing local readiness."""
    from ocr.config import get_default_model

    selected = get_default_model()
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        ready: bool | None = None
        detail = "not checked"
        if check:
            try:
                ready, detail = model.probe()
            except Exception as exc:
                ready, detail = False, str(exc)
        rows.append(
            {
                "key": model.key,
                "name": model.name,
                "description": model.description,
                "default": model.key == selected,
                "ready": ready,
                "detail": detail,
            }
        )
    return rows
