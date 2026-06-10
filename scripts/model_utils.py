#!/usr/bin/env python3
"""model_utils.py — Model download and loading utilities for local embeddings.

Supports two backends:
  - modelscope: Download from ModelScope (魔搭), cache locally
  - huggingface: Load from HuggingFace Hub or local path

Usage:
    from model_utils import resolve_model_path, download_from_modelscope
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Optional

MODELSCOPE_CACHE_DIR = os.path.expanduser("~/.cache/modelscope/hub/models")


def download_from_modelscope(
    model_id: str,
    cache_dir: Optional[str] = None,
    force: bool = False,
) -> Path:
    """Download a model from ModelScope with progress display.

    Args:
        model_id: ModelScope model ID, e.g. "Qwen/Qwen3-Embedding-8B"
        cache_dir: Custom cache directory (default: ~/.cache/modelscope/hub/models)
        force: Force re-download even if cached

    Returns:
        Path to the local model directory
    """
    cache_dir = cache_dir or MODELSCOPE_CACHE_DIR
    local_path = Path(cache_dir) / model_id

    if local_path.exists() and not force:
        # Verify it's a complete model directory
        if (local_path / "config.json").exists() and any(
            local_path.glob("*.safetensors")
        ):
            print(f"  Model already cached: {local_path}", file=sys.stderr)
            return local_path

    print(f"  Downloading {model_id} from ModelScope...", file=sys.stderr)
    try:
        from modelscope import snapshot_download

        local_path_str = snapshot_download(
            model_id=model_id,
            cache_dir=cache_dir,
        )
        print(f"  Model downloaded to: {local_path_str}", file=sys.stderr)
        return Path(local_path_str)
    except ImportError:
        print(
            "  modelscope not installed. Install: pip install modelscope",
            file=sys.stderr,
        )
        raise
    except Exception as e:
        print(f"  ModelScope download failed: {e}", file=sys.stderr)
        raise


def resolve_model_path(
    model_name: str,
    backend: str = "modelscope",
    cache_dir: Optional[str] = None,
) -> str:
    """Resolve a model name to a local path, downloading if needed.

    Args:
        model_name: Model identifier:
            - For modelscope: "Qwen/Qwen3-Embedding-8B"
            - For huggingface: "sentence-transformers/all-MiniLM-L6-v2"
            - Local path: "/path/to/model" or "./relative/path"
        backend: "modelscope" or "huggingface" or "local"
        cache_dir: Cache directory for downloads

    Returns:
        Resolved path string (local path or HF model ID)
    """
    # If it's a local path, use directly
    if os.path.isabs(model_name) or model_name.startswith((".", "..")):
        path = Path(model_name).expanduser().resolve()
        if path.exists():
            return str(path)
        print(f"  Warning: local model path not found: {path}", file=sys.stderr)
        return model_name

    if backend == "local":
        return model_name

    if backend == "modelscope":
        try:
            return str(download_from_modelscope(model_name, cache_dir=cache_dir))
        except Exception:
            print(
                f"  Falling back to huggingface for {model_name}",
                file=sys.stderr,
            )
            return model_name

    # huggingface backend — return as-is (sentence-transformers handles it)
    return model_name


def get_device(device: str = "auto") -> str:
    """Resolve the best available device for embedding computation.

    Args:
        device: "auto", "mps", "cuda", or "cpu"

    Returns:
        Device string suitable for SentenceTransformer/SentenceTransformer
    """
    if device != "auto":
        return device

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass

    return "cpu"


def get_embedding_model(
    model_name: str,
    backend: str = "modelscope",
    device: str = "auto",
    trust_remote_code: bool = True,
) -> object:
    """Load and return a SentenceTransformer model, downloading if needed.

    Args:
        model_name: Model identifier (modelscope ID, HF ID, or local path)
        backend: "modelscope", "huggingface", or "local"
        device: "auto", "mps", "cuda", or "cpu"
        trust_remote_code: Whether to trust remote code (required for some models)

    Returns:
        SentenceTransformer model instance
    """
    from sentence_transformers import SentenceTransformer

    resolved_device = get_device(device)
    model_path = resolve_model_path(model_name, backend=backend)

    print(
        f"  Loading embedding model: {model_path} (device={resolved_device})",
        file=sys.stderr,
    )

    model = SentenceTransformer(
        model_path,
        device=resolved_device,
        trust_remote_code=trust_remote_code,
    )

    # Print model info
    try:
        dim = model.get_embedding_dimension()
    except AttributeError:
        dim = model.get_sentence_embedding_dimension()  # legacy API
    print(f"  Embedding dimension: {dim}", file=sys.stderr)
    return model


# ═══════════════════════════════════════════════════════════════════════
# MLX Model Support (jina-embeddings-v5-*-mlx, etc.)
# ═══════════════════════════════════════════════════════════════════════

_MLX_TOKENIZER_CACHE: dict[str, object] = {}


def _flat_to_tree(flat: dict) -> dict:
    """Convert flat safetensors keys to nested dict for MLX model.update().

    "model.layers.0.self_attn.q_proj.weight" becomes nested dict,
    with integer keys later converted to lists.
    """
    tree: dict = {}
    for key, value in flat.items():
        parts = key.split(".")
        d = tree
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = value
    return _dict_lists(tree)


def _dict_lists(node):
    """Post-process: convert dicts whose keys are all digits into lists."""
    import mlx.core as mx
    if isinstance(node, mx.array):
        return node
    if isinstance(node, dict):
        if node and all(k.isdigit() for k in node):
            max_i = max(int(k) for k in node)
            lst = [{} for _ in range(max_i + 1)]
            for k, v in node.items():
                lst[int(k)] = _dict_lists(v)
            return lst
        return {k: _dict_lists(v) for k, v in node.items()}
    return node


def _is_mlx_model(model_path: str) -> bool:
    """Check if a model directory contains a pure MLX model (model.py + model.safetensors)."""
    p = Path(model_path)
    return (p / "model.py").exists() and (p / "model.safetensors").exists()


class MLXEmbeddingWrapper:
    """Wrapper that provides a SentenceTransformer-compatible interface for MLX models.

    Supports:
      - jina-embeddings-v5-text-small-retrieval-mlx
      - Any MLX model with model.py + model.safetensors + tokenizer.json
    """

    def __init__(
        self,
        model_path: str,
        device: str = "mps",
        matryoshka_dim: Optional[int] = None,
    ):
        import importlib.util

        self.model_path = model_path
        self.matryoshka_dim = matryoshka_dim
        self._model = None
        self._tokenizer = None
        self._dim = None

    def _load(self):
        if self._model is not None:
            return

        model_dir = Path(self.model_path)

        # Dynamically load model.py as a module
        spec = importlib.util.spec_from_file_location(
            "_jina_mlx_model",
            str(model_dir / "model.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Load config
        import json
        config = json.loads((model_dir / "config.json").read_text())

        # Load weights via MLX native safetensors loading
        import mlx.core as mx

        weight_files = sorted(model_dir.glob("*.safetensors"))
        if not weight_files:
            raise FileNotFoundError(f"No safetensors found in {model_dir}")

        # Build flat weights dict
        flat_weights = {}
        for wf in weight_files:
            loaded = mx.load(str(wf), format="safetensors")
            flat_weights.update(loaded)

        # Convert flat keys (model.layers.0.self_attn.q_proj.weight)
        # into nested dicts for MLX model.update()
        weights = _flat_to_tree(flat_weights)

        # Build model
        model = module.JinaEmbeddingModel(config)
        model.update(weights)
        mx.eval(model.parameters())
        self._model = model

        # Load tokenizer
        from tokenizers import Tokenizer as Tkzr
        tokenizer_path = str(model_dir / "tokenizer.json")
        tokenizer_cache_key = tokenizer_path
        if tokenizer_cache_key not in _MLX_TOKENIZER_CACHE:
            _MLX_TOKENIZER_CACHE[tokenizer_cache_key] = Tkzr.from_file(tokenizer_path)
        self._tokenizer = _MLX_TOKENIZER_CACHE[tokenizer_cache_key]

        self._dim = config.get("hidden_size", 1024)

    def get_embedding_dimension(self) -> int:
        self._load()
        return self.matryoshka_dim or self._dim

    def encode(
        self,
        texts: list[str],
        convert_to_numpy: bool = True,
        show_progress_bar: bool = False,
        batch_size: int = 16,
    ):
        """Encode texts to embeddings. Compatible with SentenceTransformer.encode()."""
        import numpy as np

        self._load()

        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            emb = self._model.encode(
                batch,
                self._tokenizer,
                truncate_dim=self.matryoshka_dim,
            )
            all_embeddings.append(np.array(emb))

        result = np.concatenate(all_embeddings, axis=0)
        if convert_to_numpy:
            return result
        return result
