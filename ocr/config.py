"""Standalone configuration for the installable :mod:`ocr` package.

The OCR command must work outside an LLM Wiki checkout, so its user settings
live under ``~/.config/ocr/config.yaml`` (or ``$OCR_CONFIG``) and never depend
on the current working directory.
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

CONFIG_ENV_VAR = "OCR_CONFIG"
DEFAULT_MODEL = "paddlevl"

DEFAULT_CONFIG: dict[str, Any] = {
    "default_model": DEFAULT_MODEL,
    "models": {
        "paddlevl": {"pdf_dpi": 200, "options": {}},
        "ovis": {"pdf_dpi": 200, "options": {}},
        "mineru": {"pdf_dpi": 200, "options": {}},
        "deepseek": {"pdf_dpi": 200, "options": {}},
        "logics": {"pdf_dpi": 200, "options": {}},
        "paddle": {"pdf_dpi": 200, "options": {}},
        "api": {
            "mode": "api",
            "api_provider": "",
            "api_url": "",
            "api_key": "",
            "api_model": "",
            "api_prompt": "Convert the document to clean markdown format.",
            "pdf_dpi": 200,
            "options": {},
        },
    },
}


def get_config_path(path: str | Path | None = None) -> Path:
    """Return the explicit or platform-standard OCR config path."""
    if path is not None:
        return Path(path).expanduser()
    if configured := os.environ.get(CONFIG_ENV_VAR):
        return Path(configured).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "ocr" / "config.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load standalone OCR configuration, filling safe defaults."""
    config_path = get_config_path(path)
    if not config_path.is_file():
        return deepcopy(DEFAULT_CONFIG)
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"OCR config must contain a YAML mapping: {config_path}")
    return _deep_merge(DEFAULT_CONFIG, loaded)


def save_config(config: dict[str, Any], path: str | Path | None = None) -> Path:
    """Persist OCR configuration atomically enough for a local CLI setting."""
    config_path = get_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(f"{config_path.suffix}.tmp")
    temporary.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(config_path)
    return config_path


def get_default_model(path: str | Path | None = None) -> str:
    """Return the globally selected OCR model key."""
    return str(load_config(path).get("default_model", DEFAULT_MODEL))


def set_default_model(model: str, path: str | Path | None = None) -> Path:
    """Select and persist the global default OCR model."""
    from ocr.registry import get_model

    get_model(model)
    config = load_config(path)
    config["default_model"] = model
    return save_config(config, path)


def get_model_config(
    model: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Return normalized settings for one model."""
    config = load_config(path)
    selected = model or str(config.get("default_model", DEFAULT_MODEL))
    model_configs = config.get("models", {})
    settings = model_configs.get(selected, {}) if isinstance(model_configs, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError(f"OCR model config must be a mapping: {selected}")
    normalized = deepcopy(settings)
    normalized.setdefault("mode", "api" if selected == "api" else "local")
    normalized.setdefault("backend", selected)
    normalized.setdefault("pdf_dpi", 200)
    normalized.setdefault("options", {})
    return normalized


def set_config_value(
    dotted_key: str,
    value: Any,
    path: str | Path | None = None,
) -> Path:
    """Set a dotted config value such as ``models.ovis.options.model_path``."""
    keys = [part for part in dotted_key.split(".") if part]
    if not keys:
        raise ValueError("configuration key cannot be empty")
    if keys == ["default_model"]:
        from ocr.registry import get_model

        get_model(str(value))
    config = load_config(path)
    cursor: dict[str, Any] = config
    for key in keys[:-1]:
        child = cursor.setdefault(key, {})
        if not isinstance(child, dict):
            raise ValueError(f"configuration path is not a mapping: {key}")
        cursor = child
    cursor[keys[-1]] = value
    return save_config(config, path)
