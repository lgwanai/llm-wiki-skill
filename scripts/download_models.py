#!/usr/bin/env python3
"""download_models.py — Setup OCR models for LLM Wiki.

Links or downloads OCR models to the project's models/ directory:
- MinerU: PDF-Extract-Kit models (Layout, OCR, MFR, TabCls, TabRec)
- DeepSeek-OCR-2: Vision-language model (~6.3GB)
- Logics-Parsing-v2: Qwen3VL-based OCR (~8.4GB)
- PaddleOCR: PP-OCRv5 models (auto-downloaded on first use)

Usage:
    python scripts/download_models.py --setup-links
    python scripts/download_models.py --info
"""

import argparse
import os
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


def _safe_is_symlink(path: Path) -> bool:
    """Check if path is a symlink, returning False on platforms that don't support it."""
    try:
        return path.is_symlink()
    except (OSError, NotImplementedError):
        return False


def _safe_readlink(path: Path) -> str:
    """Read a symlink target, returning empty string on failure."""
    try:
        return str(os.readlink(path))
    except (OSError, NotImplementedError, ValueError):
        return ""


def _safe_symlink_to(dst: Path, src: Path) -> bool:
    """Create a symlink at dst pointing to src.

    On Windows, symlink creation requires Developer Mode or admin privileges.
    If symlink fails, prints guidance for the user.

    Returns True on success, False on failure.
    """
    try:
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)
        return True
    except OSError as e:
        if platform.system() == "Windows":
            print(f"  ⚠ Symlink failed: {e}")
            print(f"     On Windows, symlinks require Developer Mode or admin rights.")
            print(f"     To enable: Settings → Privacy & Security → For Developers → Developer Mode")
            print(f"     Or run terminal as Administrator.")
        else:
            print(f"  ⚠ Symlink failed: {e}")
        return False
    except NotImplementedError:
        print(f"  ⚠ Symlinks not supported on this platform")
        return False


def show_info():
    """Show current model configuration."""
    print("=" * 60)
    print("LLM Wiki OCR Models Configuration")
    print("=" * 60)
    
    models = {
        "mineru": {
            "path": MODELS_DIR / "mineru" / "models",
            "required_files": ["Layout", "OCR", "MFR"],
            "size": "~2GB",
            "backend": "CPU",
        },
        "deepseek-ocr-v2": {
            "path": MODELS_DIR / "deepseek-ocr-v2" / "model",
            "required_files": ["config.json", "model-00001-of-000001.safetensors"],
            "size": "~6.3GB",
            "backend": "GPU/MPS/CPU",
        },
        "logics-parsing-v2": {
            "path": MODELS_DIR / "logics-parsing-v2" / "model",
            "required_files": ["config.json", "model-00001-of-00002.safetensors"],
            "size": "~8.4GB",
            "backend": "GPU/MPS/CPU",
        },
    }
    
    for name, info in models.items():
        path = info["path"]
        exists = path.exists()
        is_link = _safe_is_symlink(path) if exists else False
        link_target = _safe_readlink(path) if is_link else ""

        status = "✓" if exists else "✗"
        link_info = f" → {link_target}" if link_target else ""

        print(f"\n{status} {name}")
        print(f"  Path: {path}{link_info}")
        print(f"  Size: {info['size']}")
        print(f"  Backend: {info['backend']}")

        if exists:
            # Check for required files
            for req_file in info["required_files"]:
                if link_target:
                    req_path = Path(link_target) / req_file
                else:
                    req_path = path / req_file
                file_status = "✓" if req_path.exists() else "✗"
                print(f"  {file_status} {req_file}")
    
    print("\n" + "=" * 60)
    print("Quick Commands:")
    print("  python scripts/download_models.py --setup-links")
    print("  python scripts/ocr.py document.pdf --backend mineru")
    print("  python scripts/ocr.py document.pdf --backend deepseek")
    print("  python scripts/ocr.py document.pdf --backend logics")
    print("=" * 60)


def setup_links():
    """Setup symbolic links to existing model directories.

    On Windows, symlink creation requires Developer Mode or admin privileges.
    The function will guide users on how to enable this if symlinks fail.
    """
    print("Setting up model symlinks...")
    if platform.system() == "Windows":
        print("(Windows: symlinks require Developer Mode or admin rights)")
        print()

    # MinerU - link from ModelScope cache
    mineru_dst = MODELS_DIR / "mineru" / "models"
    mineru_src = Path.home() / ".cache" / "modelscope" / "hub" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1.0" / "models"

    if mineru_src.exists():
        mineru_dst.parent.mkdir(parents=True, exist_ok=True)
        if _safe_symlink_to(mineru_dst, mineru_src):
            print(f"✓ MinerU: {mineru_dst} → {mineru_src}")
    else:
        print(f"✗ MinerU source not found: {mineru_src}")
        print("  Install with: pip install mineru")

    # DeepSeek-OCR-2 - link from ~/project/DeepSeek-OCR-2
    deepseek_dst = MODELS_DIR / "deepseek-ocr-v2" / "model"
    deepseek_src = Path.home() / "project" / "DeepSeek-OCR-2" / "models" / "DeepSeek-OCR-2"

    if deepseek_src.exists():
        deepseek_dst.parent.mkdir(parents=True, exist_ok=True)
        if _safe_symlink_to(deepseek_dst, deepseek_src):
            print(f"✓ DeepSeek-OCR-2: {deepseek_dst} → {deepseek_src}")
    else:
        print(f"✗ DeepSeek-OCR-2 source not found: {deepseek_src}")

    # Logics-Parsing-v2 - link from ~/project/Logics-Parsing
    logics_dst = MODELS_DIR / "logics-parsing-v2" / "model"
    logics_src = Path.home() / "project" / "Logics-Parsing" / "weights" / "Logics-Parsing-v2"

    if logics_src.exists():
        logics_dst.parent.mkdir(parents=True, exist_ok=True)
        if _safe_symlink_to(logics_dst, logics_src):
            print(f"✓ Logics-Parsing-v2: {logics_dst} → {logics_src}")
    else:
        print(f"✗ Logics-Parsing-v2 source not found: {logics_src}")

    print("\nDone! Run --info to verify.")


def main():
    parser = argparse.ArgumentParser(description="Setup OCR models for LLM Wiki")
    parser.add_argument("--info", action="store_true", help="Show model configuration")
    parser.add_argument("--setup-links", action="store_true", help="Setup symlinks to existing models")
    args = parser.parse_args()
    
    if args.info:
        show_info()
    elif args.setup_links:
        setup_links()
    else:
        parser.print_help()
        print()
        print("Quick start:")
        print("  python scripts/download_models.py --info         # Show model status")
        print("  python scripts/download_models.py --setup-links  # Link existing models")


if __name__ == "__main__":
    main()