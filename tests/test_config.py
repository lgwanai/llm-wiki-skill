"""Tests for compact configuration normalization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.config as config


def test_new_model_config_is_primary():
    cfg = config._normalize_config({
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
        }
    })

    assert cfg["model"]["provider"] == "openai"
    assert cfg["model"]["model"] == "gpt-4o-mini"
    assert cfg["model"]["api_key"] == "sk-test"


def test_legacy_llm_ollama_merges_into_model():
    cfg = config._normalize_config({
        "llm": {"provider": "ollama"},
        "ollama": {"model": "qwen2.5", "base_url": "http://localhost:11434"},
    })

    assert cfg["model"]["provider"] == "ollama"
    assert cfg["model"]["model"] == "qwen2.5"
    assert cfg["model"]["base_url"] == "http://localhost:11434"


def test_legacy_llm_values_fill_default_model():
    cfg = config._normalize_config({
        "model": {
            "provider": "deepseek",
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        },
        "llm": {
            "provider": "openai",
            "api_key": "sk-old",
            "model": "gpt-4o",
        },
    })

    assert cfg["model"]["provider"] == "openai"
    assert cfg["model"]["api_key"] == "sk-old"


def test_legacy_ocr_backend_section_merges_into_options():
    cfg = config._normalize_config({
        "ocr_mode": "deepseek",
        "deepseek_ocr": {
            "model_path": "models/deepseek-ocr-v2/model",
            "device": "mps",
        },
    })

    assert cfg["ocr"]["backend"] == "deepseek"
    assert cfg["ocr"]["options"]["model_path"] == "models/deepseek-ocr-v2/model"
    assert cfg["ocr"]["options"]["device"] == "mps"


def test_new_ocr_options_override_legacy_section():
    cfg = config._normalize_config({
        "ocr": {
            "backend": "mineru",
            "options": {"lang": "en"},
        },
        "mineru": {
            "lang": "ch",
            "formula": True,
        },
    })

    assert cfg["ocr"]["options"]["lang"] == "en"
    assert cfg["ocr"]["options"]["formula"] is True


def test_relative_wiki_dir_defaults_to_current_project(tmp_path, monkeypatch):
    project = tmp_path / "project-a"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LLM_WIKI_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_CONFIG", raising=False)
    config.reset_config()

    assert config.get_wiki_dir() == project / ".wiki"


def test_subdirectory_uses_nearest_existing_wiki_root(tmp_path, monkeypatch):
    project = tmp_path / "project-b"
    home = tmp_path / "home"
    subdir = project / "src" / "pkg"
    home.mkdir()
    (project / ".wiki").mkdir(parents=True)
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LLM_WIKI_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_CONFIG", raising=False)
    config.reset_config()

    assert config.get_project_root() == project
    assert config.get_wiki_dir() == project / ".wiki"


def test_llm_wiki_dir_absolute_override(tmp_path, monkeypatch):
    project = tmp_path / "project-c"
    override = tmp_path / "shared-wiki"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LLM_WIKI_DIR", str(override))
    monkeypatch.delenv("LLM_WIKI_PROJECT_DIR", raising=False)
    config.reset_config()

    assert config.get_wiki_dir() == override


def test_image_analysis_defaults_disabled(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_WIKI_CONFIG", raising=False)
    monkeypatch.delenv("LLM_WIKI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_DIR", raising=False)
    config.reset_config()

    image = config.get_image_analysis_config()

    assert image["enabled"] is False
    assert image["api_url"] == ""
    assert image["ocr_fallback"] is True


def test_default_query_path_is_wiki_native(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_WIKI_CONFIG", raising=False)
    monkeypatch.delenv("LLM_WIKI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_DIR", raising=False)
    config.reset_config()

    query = config.get_query_config()

    assert query["llm_query_expansion"] is False
    # Wiki-native defaults: no embeddings, no chunks, no cross-encoders
    search_streams = query.get("search_streams", "")
    assert "bm25" in search_streams or "metadata" in search_streams


def test_image_analysis_api_url_is_exposed(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "wiki_config.yaml").write_text(
        """
image_analysis:
  enabled: true
  api_provider: custom
  api_url: http://localhost:8000/v1/chat/completions
  api_key: ${VISION_API_KEY}
  api_model: qwen-vl
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.delenv("LLM_WIKI_CONFIG", raising=False)
    monkeypatch.delenv("LLM_WIKI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("LLM_WIKI_DIR", raising=False)
    config.reset_config()

    image = config.get_image_analysis_config()

    assert image["enabled"] is True
    assert image["api_url"] == "http://localhost:8000/v1/chat/completions"
    assert image["api_key"] == "test-key"
    assert image["api_model"] == "qwen-vl"
