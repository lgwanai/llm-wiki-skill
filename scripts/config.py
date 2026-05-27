#!/usr/bin/env python3
"""config.py — Unified configuration loader for LLM Wiki v2.

Provides single source of truth for all configuration:
- wiki_dir: Wiki storage location
- LLM settings: URL/local model switching
- Query settings
- OCR backends
- Retention policies

Usage:
    from config import get_config, get_wiki_dir
    
    config = get_config()
    wiki_dir = get_wiki_dir()
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

_config_cache: Optional[dict] = None
_wiki_dir_cache: Optional[Path] = None

CONFIG_FILENAME = "wiki_config.yaml"
CONFIG_ENV_VAR = "LLM_WIKI_CONFIG"

DEFAULT_CONFIG = {
    "wiki_dir": ".wiki",
    "llm": {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "temperature": 0.3,
        "max_tokens": 32000,
    },
    "query": {
        "llm_synthesis": True,
        "default_format": "markdown",
        "max_results": 5,
    },
    "logging": {
        "level": "INFO",
    },
}


def find_config_file() -> Optional[Path]:
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
    
    config = _expand_env_vars(config)
    
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
    
    wiki_dir = Path(wiki_dir_str)
    
    if not wiki_dir.is_absolute():
        config_file = find_config_file()
        if config_file:
            wiki_dir = config_file.parent / wiki_dir_str
        else:
            wiki_dir = Path.cwd() / wiki_dir_str
    
    _wiki_dir_cache = wiki_dir.resolve()
    return _wiki_dir_cache


def get_llm_config() -> dict:
    """Get LLM configuration with provider-specific defaults."""
    config = get_config()
    llm = config.get("llm", {})
    provider = llm.get("provider", "deepseek")
    
    base_url_defaults = {
        "deepseek": "https://api.deepseek.com",
        "openai": "https://api.openai.com",
        "ollama": "http://localhost:11434",
    }
    
    if provider == "ollama":
        ollama_config = config.get("ollama", {})
        return {
            "provider": "ollama",
            "base_url": ollama_config.get("base_url", "http://localhost:11434"),
            "model": ollama_config.get("model", "llama3.2"),
            "temperature": ollama_config.get("temperature", 0.3),
            "num_ctx": ollama_config.get("num_ctx", 32768),
            "api_key": None,
            "max_tokens": llm.get("max_tokens", 32000),
        }
    
    if provider == "custom":
        custom_config = config.get("custom", {})
        return {
            "provider": "custom",
            "base_url": custom_config.get("base_url", ""),
            "api_url": custom_config.get("api_url", ""),
            "api_key": custom_config.get("api_key", ""),
            "model": custom_config.get("model", ""),
            "temperature": llm.get("temperature", 0.3),
            "max_tokens": llm.get("max_tokens", 32000),
        }
    
    return {
        "provider": provider,
        "base_url": llm.get("base_url", base_url_defaults.get(provider, "")),
        "api_key": llm.get("api_key", ""),
        "model": llm.get("model", ""),
        "temperature": llm.get("temperature", 0.3),
        "max_tokens": llm.get("max_tokens", 32000),
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
    return config.get("query", DEFAULT_CONFIG["query"])


def get_ocr_config() -> dict:
    """Get OCR backend configuration."""
    config = get_config()
    return {
        "mineru": config.get("mineru", {}),
        "paddleocr": config.get("paddleocr", {}),
        "ocr": config.get("ocr", {}),
    }


def reset_config():
    """Reset configuration cache (for testing)."""
    global _config_cache, _wiki_dir_cache
    _config_cache = None
    _wiki_dir_cache = None


def create_default_config(dest: Optional[Path] = None) -> Path:
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
    """Validate configuration and return list of issues."""
    issues = []
    
    llm = config.get("llm", {})
    provider = llm.get("provider", "deepseek")
    
    if provider not in ("ollama",) and not llm.get("api_key"):
        issues.append(f"LLM API key required for provider '{provider}'")
    
    wiki_dir = config.get("wiki_dir")
    if wiki_dir:
        wiki_path = Path(wiki_dir)
        if not wiki_path.is_absolute():
            issues.append(f"wiki_dir '{wiki_dir}' is relative (resolved at runtime)")
    
    return issues


def print_config():
    """Print current configuration (for debugging)."""
    import json
    config = get_config()
    print(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"\nWiki directory: {get_wiki_dir()}")
    print(f"API URL: {get_api_url()}")


if __name__ == "__main__":
    print("Current LLM Wiki Configuration:")
    print("=" * 50)
    print_config()
