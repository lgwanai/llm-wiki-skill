"""Tests for embedding index metadata and compatibility."""

from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scripts.generate_embeddings as generate_embeddings


def test_load_embedding_index_accepts_legacy_format(tmp_path):
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps({"page-a": [1.0, 2.0]}), encoding="utf-8")

    meta, items = generate_embeddings.load_embedding_index(path)

    assert meta == {}
    assert items == {"page-a": [1.0, 2.0]}


def test_write_embedding_index_includes_meta(tmp_path, monkeypatch):
    path = tmp_path / "embeddings.json"
    monkeypatch.setattr(
        generate_embeddings,
        "get_embeddings_config",
        lambda: {
            "mode": "api",
            "api_model": "embed-test",
            "dimension": 3,
            "backend": "faiss",
        },
    )

    generate_embeddings.write_embedding_index({"page-a": [1.0, 2.0, 3.0]}, path)
    meta, items = generate_embeddings.load_embedding_index(path)

    assert meta["schema_version"] == generate_embeddings.EMBEDDING_SCHEMA_VERSION
    assert meta["mode"] == "api"
    assert meta["model"] == "embed-test"
    assert items["page-a"] == [1.0, 2.0, 3.0]


def test_embedding_index_status_detects_config_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "embeddings.json"
    path.write_text(
        json.dumps({
            "_meta": {
                "schema_version": generate_embeddings.EMBEDDING_SCHEMA_VERSION,
                "mode": "api",
                "model": "old-model",
                "dimension": 3,
            },
            "items": {"page-a": [1.0, 2.0, 3.0]},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        generate_embeddings,
        "get_embeddings_config",
        lambda: {
            "mode": "api",
            "api_model": "new-model",
            "dimension": 3,
            "backend": "faiss",
        },
    )

    status = generate_embeddings.embedding_index_status(path)

    assert status["stale"] is True
    assert status["mismatches"]["model"]["index"] == "old-model"
    assert status["mismatches"]["model"]["current"] == "new-model"


def test_write_embedding_index_detects_dict_embedding_dimension(tmp_path, monkeypatch):
    path = tmp_path / "chunk_embeddings.json"
    monkeypatch.setattr(
        generate_embeddings,
        "get_embeddings_config",
        lambda: {
            "mode": "api",
            "api_model": "embed-test",
            "dimension": 999,
            "backend": "faiss",
        },
    )

    generate_embeddings.write_embedding_index(
        {"chunk-a": {"embedding": [1.0, 2.0, 3.0, 4.0], "text": "x"}},
        path,
    )
    meta, items = generate_embeddings.load_embedding_index(path)

    assert meta["dimension"] == 4
    assert items["chunk-a"]["embedding"] == [1.0, 2.0, 3.0, 4.0]


def test_embeddings_file_env_override_is_used(tmp_path, monkeypatch):
    custom = tmp_path / "custom_embeddings.json"
    monkeypatch.setenv("EMBEDDINGS_FILE", str(custom))

    reloaded = importlib.reload(generate_embeddings)
    try:
        assert reloaded.EMBEDDINGS_FILE == custom
    finally:
        monkeypatch.delenv("EMBEDDINGS_FILE", raising=False)
        importlib.reload(generate_embeddings)
