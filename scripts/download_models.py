#!/usr/bin/env python3
"""
download_models.py — 下载 PaddleOCR-VL-1.5 模型到 ~/.models/

从 HuggingFace 下载模型权重，存放到 ~/.models/PaddleOCR-VL-1.5/，
供本机所有程序共享使用。下载使用镜像加速。

Usage:
    python download_models.py                    # 默认下载到 ~/.models/
    python download_models.py --target /path/to  # 指定目录
    python download_models.py --mirror           # 使用 HF 镜像加速（国内）
"""

import argparse
import os
import sys
from pathlib import Path

MODEL_ID = "PaddlePaddle/PaddleOCR-VL-1.5"
DEFAULT_TARGET = os.path.expanduser("~/.models/PaddleOCR-VL-1.5")
HF_MIRROR = "https://hf-mirror.com"


def download_with_snapshot(target_dir: str, use_mirror: bool = False) -> None:
    """使用 huggingface_hub 的 snapshot_download 下载完整模型."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub not installed. Installing...")
        os.system(f"{sys.executable} -m pip install huggingface_hub -q")
        from huggingface_hub import snapshot_download

    endpoint = HF_MIRROR if use_mirror else None

    print(f"Downloading {MODEL_ID} → {target_dir}")
    if use_mirror:
        print(f"  Mirror: {HF_MIRROR}")

    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=target_dir,
        local_dir_use_symlinks=False,
        endpoint=endpoint,
        resume_download=True,
        max_workers=4,
    )


def download_with_git_lfs(target_dir: str, use_mirror: bool = False) -> None:
    """使用 git lfs clone 下载（备选方案）."""
    if os.system("which git-lfs > /dev/null 2>&1") != 0:
        print("git-lfs not found. Install with: brew install git-lfs")
        sys.exit(1)

    repo_url = f"https://huggingface.co/{MODEL_ID}"
    if use_mirror:
        repo_url = f"{HF_MIRROR}/{MOD_ID}"

    print(f"Cloning {MODEL_ID} → {target_dir} (git lfs)")
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    os.system(f'GIT_LFS_SKIP_SMUDGE=1 git clone "{repo_url}" "{target_dir}"')
    os.chdir(target_dir)
    os.system("git lfs pull")


def verify_download(target_dir: str) -> bool:
    """验证下载完整性 — 检查关键文件."""
    required = [
        "config.json",
        "model.safetensors.index.json",
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(target_dir, f))]
    if missing:
        print(f"⚠ Missing files: {missing}")
        return False

    size = sum(
        os.path.getsize(os.path.join(dirpath, filename))
        for dirpath, _, filenames in os.walk(target_dir)
        for filename in filenames
    )
    size_gb = size / (1024**3)
    print(f"✓ Model verified: {size_gb:.1f} GB at {target_dir}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Download PaddleOCR-VL-1.5 model")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help=f"Target directory (default: {DEFAULT_TARGET})")
    parser.add_argument("--mirror", action="store_true",
                        help="Use HF mirror for faster download in China")
    parser.add_argument("--git-lfs", action="store_true",
                        help="Use git-lfs clone instead of snapshot_download")
    args = parser.parse_args()

    if os.path.exists(args.target) and verify_download(args.target):
        print("Model already downloaded and verified. Use --target to change location.")
        return

    os.makedirs(args.target, exist_ok=True)

    if args.git_lfs:
        download_with_git_lfs(args.target, args.mirror)
    else:
        try:
            download_with_snapshot(args.target, args.mirror)
        except Exception as e:
            print(f"snapshot_download failed: {e}")
            print("Trying git-lfs clone as fallback...")
            download_with_git_lfs(args.target, args.mirror)

    if verify_download(args.target):
        print("\n✓ Download complete!")
        print(f"  Model location: {args.target}")
        print(f"  Next: start the OCR server with:")
        print(f"    python scripts/ocr_server.py")
    else:
        print("\n⚠ Download may be incomplete. Run again or use --git-lfs.")


if __name__ == "__main__":
    main()
