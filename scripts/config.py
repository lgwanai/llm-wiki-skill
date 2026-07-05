#!/usr/bin/env python3
"""config.py — Unified configuration loader for LLM Wiki v2.

Provides a small user-facing configuration surface:
- wiki_dir: Wiki storage location
- model: Chat model/API settings
- ocr: OCR mode/backend/API/options
- image_analysis: Optional vision model for image sources during compile
- query: Query behavior

Usage:
    from config import get_config, get_wiki_dir

    config = get_config()
    wiki_dir = get_wiki_dir()
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

_config_cache: dict | None = None
_wiki_dir_cache: Path | None = None
_project_root_cache: Path | None = None

CONFIG_FILENAME = "wiki_config.yaml"
CONFIG_ENV_VAR = "LLM_WIKI_CONFIG"

DEFAULT_CONFIG = {
    "wiki_dir": ".wiki",
    "model": {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "temperature": 0.3,
        "max_tokens": 32000,
        "num_ctx": 32768,
    },
    "ocr": {
        "mode": "local",
        "backend": "mineru",
        "api_provider": "",
        "api_url": "",
        "api_key": "",
        "api_model": "",
        "api_prompt": "Convert the document to clean markdown format.",
        "pdf_dpi": 150,
        "options": {},
    },
    "image_analysis": {
        "enabled": False,
        "api_provider": "",
        "api_url": "",
        "api_key": "",
        "api_model": "",
        "api_prompt": "",
        "ocr_fallback": True,
        "ocr_min_chars": 800,
    },
    "vision_skill": {
        "enabled": True,
        "scripts_path": "",
        "recognize_format": "markdown_note",
    },
    "query": {
        "llm_synthesis": True,
        "synthesis_mode": "agent",
        "default_format": "markdown",
        "max_results": 5,
        "search_streams": "metadata,bm25,graph,ledger",
        "llm_query_expansion": False,
    },
    "compile": {
        "mode": "agent",
    },
    "logging": {
        "level": "INFO",
    },
}


def find_config_file() -> Path | None:
    """Find config file in order: env var > cwd > parent dirs > home."""
    if CONFIG_ENV_VAR in os.environ:
        config_path = Path(os.environ[CONFIG_ENV_VAR])
        if config_path.exists():
            return config_path

    cwd = Path.cwd()
    for d in [cwd] + list(cwd.parents):
        config_path = d / CONFIG_FILENAME
        if config_path.exists():
            return config_path

    home_config = Path.home() / ".config" / "llm-wiki" / CONFIG_FILENAME
    if home_config.exists():
        return home_config

    return None


def find_local_config_file() -> Path | None:
    """Find a project-local config file in cwd or its parents."""
    cwd = Path.cwd()
    for d in [cwd] + list(cwd.parents):
        config_path = d / CONFIG_FILENAME
        if config_path.exists():
            return config_path
    return None


def get_project_root() -> Path:
    """Return the current wiki project root.

    Relative wiki_dir values are resolved from this root. This keeps one
    independent wiki/ledger per working project instead of binding data to
    the installed skill/script directory.
    """
    global _project_root_cache

    if _project_root_cache is not None:
        return _project_root_cache

    if "LLM_WIKI_PROJECT_DIR" in os.environ:
        _project_root_cache = Path(os.environ["LLM_WIKI_PROJECT_DIR"]).expanduser().resolve()
        return _project_root_cache

    local_config = find_local_config_file()
    if local_config:
        _project_root_cache = local_config.parent.resolve()
        return _project_root_cache

    cwd = Path.cwd()
    for d in [cwd] + list(cwd.parents):
        if (d / ".wiki").is_dir():
            _project_root_cache = d.resolve()
            return _project_root_cache

    _project_root_cache = cwd.resolve()
    return _project_root_cache


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        pattern = r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)'

        def replace_var(match):
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))

        return re.sub(pattern, replace_var, value)
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries (override takes precedence)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_config(config: dict) -> dict:
    """Normalize legacy config shapes into the compact schema.

    New config should use:
      model: {provider, api_key, base_url, model, temperature, max_tokens}
      ocr: {mode, backend, api_provider, api_*, pdf_dpi, options}

    Legacy llm/ollama/custom and top-level OCR backend sections are still
    accepted so existing wiki_config.yaml files keep working.
    """
    normalized = config.copy()

    model = normalized.get("model", {}).copy()
    if "llm" in normalized:
        legacy_llm = normalized.get("llm", {})
        if (
            legacy_llm.get("provider")
            and model.get("provider") == DEFAULT_CONFIG["model"]["provider"]
        ):
            model["provider"] = legacy_llm["provider"]
        for key, value in legacy_llm.items():
            if model.get(key) in (None, ""):
                model[key] = value
    provider = model.get("provider", "deepseek")
    if provider == "ollama":
        legacy = normalized.get("ollama", {})
        for key in ("base_url", "model", "temperature", "num_ctx"):
            if key in legacy and model.get(key) in (None, ""):
                model[key] = legacy[key]
    elif provider == "custom":
        legacy = normalized.get("custom", {})
        for key in ("base_url", "api_url", "api_key", "model"):
            if key in legacy and model.get(key) in (None, ""):
                model[key] = legacy[key]
    normalized["model"] = model

    ocr = normalized.get("ocr", {}).copy()
    if "backend" not in ocr and "ocr_mode" in normalized:
        ocr["backend"] = normalized["ocr_mode"]
    backend = ocr.get("backend", "mineru")
    options = ocr.get("options", {}) or {}
    legacy_sections = {
        "mineru": "mineru",
        "deepseek": "deepseek_ocr",
        "logics": "logics_parsing",
        "paddle": "paddleocr",
    }
    legacy_key = legacy_sections.get(backend)
    if legacy_key and legacy_key in normalized:
        options = _deep_merge(normalized.get(legacy_key, {}), options)
    ocr["options"] = options
    normalized["ocr"] = ocr

    return normalized


def load_config() -> dict:
    """Load configuration from file, with defaults as fallback."""
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    config = DEFAULT_CONFIG.copy()

    config_file = find_config_file()
    if config_file:
        try:
            with open(config_file, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            config = _deep_merge(config, user_config)
        except (yaml.YAMLError, OSError) as e:
            print(f"Warning: Failed to load config from {config_file}: {e}")

    config = _expand_env_vars(_normalize_config(config))

    _config_cache = config
    return config


def get_config() -> dict:
    """Get current configuration (cached)."""
    return load_config()


def get_wiki_dir() -> Path:
    """Get wiki directory path (resolved and absolute)."""
    global _wiki_dir_cache

    if _wiki_dir_cache is not None:
        return _wiki_dir_cache

    config = get_config()
    wiki_dir_str = config.get("wiki_dir", ".wiki")

    if "LLM_WIKI_DIR" in os.environ:
        wiki_dir_str = os.environ["LLM_WIKI_DIR"]

    wiki_dir = Path(wiki_dir_str).expanduser()

    if not wiki_dir.is_absolute():
        wiki_dir = get_project_root() / wiki_dir

    _wiki_dir_cache = wiki_dir.resolve()
    return _wiki_dir_cache


def get_llm_config() -> dict:
    """Get chat model configuration with provider-specific defaults."""
    config = get_config()
    model = config.get("model", {})
    provider = model.get("provider", "deepseek")

    base_url_defaults = {
        "deepseek": "https://api.deepseek.com",
        "openai": "https://api.openai.com",
        "ollama": "http://localhost:11434",
    }

    if provider == "ollama":
        return {
            "provider": "ollama",
            "base_url": model.get("base_url", "http://localhost:11434"),
            "model": model.get("model", "llama3.2"),
            "temperature": model.get("temperature", 0.3),
            "num_ctx": model.get("num_ctx", 32768),
            "api_key": None,
            "max_tokens": model.get("max_tokens", 32000),
        }

    if provider == "custom" or model.get("api_url"):
        return {
            "provider": "custom",
            "base_url": model.get("base_url", ""),
            "api_url": model.get("api_url", ""),
            "api_key": model.get("api_key", ""),
            "model": model.get("model", ""),
            "temperature": model.get("temperature", 0.3),
            "max_tokens": model.get("max_tokens", 32000),
        }

    return {
        "provider": provider,
        "base_url": model.get("base_url", base_url_defaults.get(provider, "")),
        "api_key": model.get("api_key", ""),
        "model": model.get("model", ""),
        "temperature": model.get("temperature", 0.3),
        "max_tokens": model.get("max_tokens", 32000),
    }


def get_api_url() -> str:
    """Get the complete API URL for chat completions."""
    llm = get_llm_config()
    provider = llm.get("provider", "deepseek")

    if provider == "ollama":
        return f"{llm['base_url'].rstrip('/')}/api/chat"

    if provider == "custom" and llm.get("api_url"):
        return llm["api_url"]

    base_url = llm.get("base_url", "").rstrip("/")
    return f"{base_url}/v1/chat/completions"


def get_query_config() -> dict:
    """Get query configuration."""
    config = get_config()
    return config.get("query", {
        "llm_synthesis": True,
        "default_format": "markdown",
        "max_results": 5,
        "search_streams": "metadata,bm25,graph,ledger",
        "llm_query_expansion": False,
    })


def get_ocr_config() -> dict:
    """Get unified OCR configuration."""
    config = get_config()
    ocr = config.get("ocr", {})

    return {
        "mode": ocr.get("mode", "local"),
        "backend": ocr.get("backend", "mineru"),
        "api_provider": ocr.get("api_provider", ""),
        "api_url": ocr.get("api_url", ""),
        "api_key": ocr.get("api_key", ""),
        "api_model": ocr.get("api_model", ""),
        "api_prompt": ocr.get(
            "api_prompt",
            "Convert the document to clean markdown format.",
        ),
        "pdf_dpi": ocr.get("pdf_dpi", 150),
        "options": ocr.get("options", {}) or {},
    }


def get_image_analysis_config() -> dict:
    """Get optional compile-time image analysis configuration."""
    config = get_config()
    image = config.get("image_analysis", {})

    return {
        "enabled": image.get("enabled", False),
        "api_provider": image.get("api_provider", ""),
        "api_url": image.get("api_url", ""),
        "api_key": image.get("api_key", ""),
        "api_model": image.get("api_model", image.get("model", "")),
        "api_prompt": image.get("api_prompt", image.get("prompt", "")),
        "ocr_fallback": image.get("ocr_fallback", True),
        "ocr_min_chars": image.get("ocr_min_chars", 800),
    }


def get_vision_skill_config() -> dict:
    """Get the vision-skill dependency configuration for image sources.

    Image files prefer the ``vision-skill`` (an Agent-side Claude Code skill)
    for recognition. OCR is the fallback; the Agent's own image-parsing
    capability is the last resort. ``scripts_path`` points at the vision-skill
    CLI (``vision_cli.py``) so the compile task can emit a concrete command.
    """
    config = get_config()
    vs = config.get("vision_skill", {})

    return {
        "enabled": vs.get("enabled", True),
        "scripts_path": vs.get("scripts_path", ""),
        "recognize_format": vs.get("recognize_format", "markdown_note"),
    }


def reset_config():
    """Reset configuration cache (for testing)."""
    global _config_cache, _wiki_dir_cache, _project_root_cache
    _config_cache = None
    _wiki_dir_cache = None
    _project_root_cache = None


def create_default_config(dest: Path | None = None) -> Path:
    """Create default config file from example."""
    if dest is None:
        dest = Path.cwd() / CONFIG_FILENAME

    example_path = Path(__file__).parent / "wiki_config.yaml.example"
    if example_path.exists():
        import shutil
        shutil.copy2(example_path, dest)
        return dest

    raise FileNotFoundError(f"Example config not found: {example_path}")


def validate_config(config: dict) -> list[str]:
    """Validate configuration against schema and return list of human-readable issues.

    Checks every section (model, ocr, query, image_analysis) for missing required
    fields, invalid enum values, and provider-specific requirements. Returns an
    empty list when configuration is valid.
    """
    issues: list[str] = []
    _v = _SchemaValidator(config, issues)

    # ── Top-level ──
    _v.check_type("wiki_dir", config.get("wiki_dir"), str)

    # ── Model ──
    model = config.get("model", {})
    if not isinstance(model, dict):
        issues.append("model: must be a dict, got " + type(model).__name__)
    else:
        _v.check_enum("model.provider", model.get("provider"), _VALID_PROVIDERS, "model")
        _v.check_type("model.model", model.get("model"), str, "model")
        _v.check_type("model.temperature", model.get("temperature"), (int, float), "model")
        _v.check_positive("model.max_tokens", model.get("max_tokens"), "model")

        provider = model.get("provider", "deepseek")
        if provider not in ("ollama",):
            key = model.get("api_key", "")
            if not key:
                issues.append(f"model.api_key: required for provider '{provider}' — "
                              f"set api_key or DEEPSEEK_API_KEY env var")
            elif not isinstance(key, str):
                issues.append("model.api_key: must be a string")
            elif key.startswith("${") and key.endswith("}"):
                # Env-var reference — check it resolves
                env_var = key[2:-1]
                if env_var not in os.environ:
                    issues.append(f"model.api_key: references ${{{env_var}}} but "
                                  f"env var '{env_var}' is not set")

        if provider == "ollama":
            _v.check_type("model.num_ctx", model.get("num_ctx"), int, "model")
            _v.check_positive("model.num_ctx", model.get("num_ctx"), "model")

    # ── Query ──
    query = config.get("query", {})
    if isinstance(query, dict):
        _v.check_type("query.max_results", query.get("max_results"), int, "query")
        _v.check_positive("query.max_results", query.get("max_results"), "query")
        streams = query.get("search_streams", "")
        if isinstance(streams, str) and streams not in ("all", "*"):
            for s in streams.split(","):
                s = s.strip()
                if s and s not in _VALID_SEARCH_STREAMS:
                    issues.append(f"query.search_streams: unknown stream '{s}' "
                                  f"(valid: {', '.join(sorted(_VALID_SEARCH_STREAMS))})")

    # ── OCR ──
    ocr = config.get("ocr", {})
    if isinstance(ocr, dict):
        _v.check_enum("ocr.mode", ocr.get("mode"), ("local", "api"), "ocr")
        _v.check_enum("ocr.backend", ocr.get("backend"),
                      ("mineru", "deepseek", "logics", "paddle", "api"), "ocr")
        if ocr.get("mode") == "api":
            _v.check_type("ocr.api_provider", ocr.get("api_provider"), str, "ocr")
            _v.check_type("ocr.api_model", ocr.get("api_model"), str, "ocr")

    # ── Image Analysis ──
    img = config.get("image_analysis", {})
    if isinstance(img, dict):
        if img.get("enabled"):
            _v.check_type("image_analysis.api_model", img.get("api_model"), str,
                          "image_analysis")
            _v.check_type("image_analysis.api_key", img.get("api_key"), str,
                          "image_analysis")

    # ── Compile ──
    compile_cfg = config.get("compile", {})
    if isinstance(compile_cfg, dict):
        _v.check_enum("compile.mode", compile_cfg.get("mode"), ("agent", "llm"), "compile")

    # ── Unknown top-level keys ──
    known_keys = {"wiki_dir", "model", "query", "ocr", "image_analysis",
                  "reranker", "embeddings", "quality", "logging", "compile"}
    for key in config:
        if key not in known_keys:
            issues.append(f"unknown top-level key '{key}' — valid keys: "
                          f"{', '.join(sorted(known_keys))}")

    return issues


# ── Schema validation helpers ─────────────────────────────────────────

_VALID_PROVIDERS = ("deepseek", "openai", "ollama", "custom")
_VALID_SEARCH_STREAMS = {"metadata", "bm25", "graph", "ledger", "chunk", "vector",
                         "chunk_vector"}


class _SchemaValidator:
    """Lightweight schema validator — no pydantic dependency needed."""

    def __init__(self, config: dict, issues: list[str]):
        self._cfg = config
        self._issues = issues

    def check_type(self, path: str, value, expected, section: str = ""):
        if value is None:
            return
        if not isinstance(value, expected):
            exp_name = getattr(expected, '__name__', str(expected))
            self._issues.append(
                f"{path}: expected {exp_name}, got {type(value).__name__}"
            )

    def check_enum(self, path: str, value, valid: tuple, section: str = ""):
        if value is None:
            return
        if value not in valid:
            self._issues.append(
                f"{path}: '{value}' is invalid — must be one of {list(valid)}"
            )

    def check_positive(self, path: str, value, section: str = ""):
        if value is None:
            return
        if not isinstance(value, (int, float)):
            return  # type error caught by check_type
        if value <= 0:
            self._issues.append(f"{path}: must be positive, got {value}")


def print_config():
    """Print effective compact configuration (for debugging)."""
    import json
    config = get_config()
    compact = {
        "wiki_dir": config.get("wiki_dir", ".wiki"),
        "model": get_llm_config(),
        "ocr": get_ocr_config(),
        "image_analysis": get_image_analysis_config(),
        "query": get_query_config(),
        "quality": config.get("quality", {}),
        "logging": config.get("logging", DEFAULT_CONFIG["logging"]),
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))
    print(f"\nWiki directory: {get_wiki_dir()}")
    print(f"API URL: {get_api_url()}")


if __name__ == "__main__":
    print("Current LLM Wiki Configuration:")
    print("=" * 50)
    print_config()
