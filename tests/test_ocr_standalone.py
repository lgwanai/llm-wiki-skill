"""Tests for standalone OCR model selection and configuration."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

import ocr
from ocr import cli, registry
from ocr.config import get_default_model, get_model_config


def test_list_reports_supported_models(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "ocr.yaml"
    monkeypatch.setenv("OCR_CONFIG", str(config_path))

    assert cli.main(["list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    keys = [model["key"] for model in payload["models"]]
    assert keys == ["paddlevl", "ovis", "mineru", "deepseek", "logics", "paddle", "api"]
    assert payload["models"][0]["default"] is True


def test_public_module_api_is_lazy(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_CONFIG", str(tmp_path / "ocr.yaml"))

    assert ocr.get_default_model() == "paddlevl"
    assert [model["key"] for model in ocr.list_models()] == [
        "paddlevl",
        "ovis",
        "mineru",
        "deepseek",
        "logics",
        "paddle",
        "api",
    ]


def test_use_persists_global_default(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "ocr.yaml"
    monkeypatch.setenv("OCR_CONFIG", str(config_path))

    assert cli.main(["use", "ovis"]) == 0

    assert get_default_model() == "ovis"
    assert "Default OCR model: ovis" in capsys.readouterr().out
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_config_set_scopes_values_by_model(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "ocr.yaml"
    monkeypatch.setenv("OCR_CONFIG", str(config_path))

    assert cli.main(["config", "set", "ovis.options.model_path", "/models/ovis"]) == 0
    capsys.readouterr()
    assert cli.main(["config", "set", "paddlevl.options.max_new_tokens", "8192"]) == 0
    capsys.readouterr()

    assert get_model_config("ovis")["options"]["model_path"] == "/models/ovis"
    assert get_model_config("paddlevl")["options"]["max_new_tokens"] == 8192


def test_direct_file_parser_uses_selected_default(monkeypatch, tmp_path):
    config_path = tmp_path / "ocr.yaml"
    monkeypatch.setenv("OCR_CONFIG", str(config_path))
    assert cli.main(["use", "api"]) == 0

    args = cli.build_parser().parse_args(["scan.png"])
    assert args.backend == "api"


@pytest.mark.parametrize(
    "backend, path_env, weight",
    [
        ("deepseek", "DEEPSEEK_OCR_MODEL_PATH", "model-00001-of-00002.safetensors"),
        ("logics", "LOGICS_PARSING_MODEL_PATH", "pytorch_model.bin"),
    ],
)
def test_local_ocr_probe_requires_config_and_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str, path_env: str, weight: str,
) -> None:
    monkeypatch.setenv("OCR_CONFIG", str(tmp_path / "ocr.yaml"))
    model = tmp_path / "local-model"
    model.mkdir()
    monkeypatch.setenv(path_env, str(model))
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda _: object())

    probe = registry.get_model(backend).probe
    assert not probe()[0]
    (model / "config.json").write_text("{}", encoding="utf-8")
    assert not probe()[0]
    (model / weight).touch()
    assert not probe()[0]
    (model / weight).write_bytes(b"model fixture")
    assert probe()[0]
