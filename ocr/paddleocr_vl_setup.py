#!/usr/bin/env python3
"""Download and verify PaddleOCR-VL-1.6 models for the isolated runtime."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

VLM_MODEL_ID = "PaddlePaddle/PaddleOCR-VL-1.6"
LAYOUT_MODEL_ID = "PaddlePaddle/PP-DocLayoutV3"


def _restore_staged_files(target: Path) -> None:
    """Restore files a ModelScope download may leave under ``._tmp``."""
    staged = target / "._tmp"
    if not staged.is_dir():
        return
    for source in staged.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(staged)
        destination = target / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _download(model_id: str, target: Path) -> None:
    """Download one ModelScope repository into a deterministic directory."""
    from modelscope import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(model_id, local_dir=str(target))
    _restore_staged_files(target)


def setup(model_path: Path, layout_model_path: Path) -> dict[str, object]:
    """Download missing weights and return a verification report."""
    vlm_required = (
        model_path / "model.safetensors",
        model_path / "config.json",
        model_path / "preprocessor_config.json",
    )
    layout_required = (layout_model_path / "inference.pdiparams",)
    if not all(path.is_file() for path in vlm_required):
        _download(VLM_MODEL_ID, model_path)
    if not all(path.is_file() for path in layout_required):
        _download(LAYOUT_MODEL_ID, layout_model_path)

    missing = [str(path) for path in (*vlm_required, *layout_required) if not path.is_file()]
    return {
        "ready": not missing,
        "model_path": str(model_path),
        "layout_model_path": str(layout_model_path),
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the model bootstrap CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--layout-model-path", type=Path, required=True)
    args = parser.parse_args(argv)
    report = setup(args.model_path.expanduser(), args.layout_model_path.expanduser())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
