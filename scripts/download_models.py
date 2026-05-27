#!/usr/bin/env python3
"""download_models.py — Download OCR models for LLM Wiki.

Downloads models to the project's models/ directory:
- MinerU: PDF-Extract-Kit models (Layout, OCR, MFR, TabCls, TabRec)
- DeepSeek-OCR: Vision-language model (optional, can use API instead)
- PaddleOCR: PP-OCRv5 models (downloaded automatically on first use)

Usage:
    python scripts/download_models.py --all
    python scripts/download_models.py --mineru
    python scripts/download_models.py --deepseek
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


def download_mineru_models():
    """Download MinerU PDF-Extract-Kit models from ModelScope."""
    mineru_dir = MODELS_DIR / "mineru"
    mineru_dir.mkdir(parents=True, exist_ok=True)
    
    print("Downloading MinerU models from ModelScope...")
    print("Target: models/mineru/models/")
    
    try:
        from modelscope import snapshot_download
        
        model_dir = snapshot_download(
            'OpenDataLab/PDF-Extract-Kit-1.0',
            cache_dir=str(mineru_dir)
        )
        
        models_path = mineru_dir / "models"
        if not models_path.exists():
            models_path.symlink_to(model_dir / "models")
        
        print(f"MinerU models downloaded to: {model_dir}")
        print("Models: Layout, OCR, MFR, TabCls, TabRec")
        
    except ImportError:
        print("ModelScope not installed. Alternative methods:")
        print()
        print("Method 1: Install mineru package (includes models)")
        print("  pip install mineru")
        print()
        print("Method 2: Manual download")
        print("  mkdir -p models/mineru/models")
        print("  cd models/mineru")
        print("  git clone https://modelscope.cn/OpenDataLab/PDF-Extract-Kit-1.0.git")
        print("  ln -s PDF-Extract-Kit-1.0/models models")
        print()
        print("Method 3: Use existing models")
        print("  ln -s ~/.cache/modelscope/hub/models/OpenDataLab/PDF-Extract-Kit-1.0/models models/mineru/models")


def download_deepseek_ocr_models():
    """Download DeepSeek-OCR model (optional - can use API instead)."""
    deepseek_dir = MODELS_DIR / "deepseek-ocr-v2"
    deepseek_dir.mkdir(parents=True, exist_ok=True)
    
    print("DeepSeek-OCR model download options:")
    print()
    print("Option 1: Use DeepSeek API (recommended)")
    print("  No local model needed. Configure in wiki_config.yaml:")
    print("  ocr:")
    print("    api_url: https://api.deepseek.com/v1/chat/completions")
    print("    api_key: your-api-key")
    print("    model: deepseek-v4-flash")
    print()
    print("Option 2: Local inference (requires GPU)")
    print("  Download from HuggingFace/ModelScope:")
    print("  modelscope download --model deepseek-ai/deepseek-vl")
    print()
    print("Option 3: Use local vLLM server")
    print("  pip install vllm")
    print("  vllm serve deepseek-ai/deepseek-vl")


def download_paddleocr_models():
    """PaddleOCR models are downloaded automatically on first use."""
    paddle_dir = MODELS_DIR / "paddleocr"
    paddle_dir.mkdir(parents=True, exist_ok=True)
    
    print("PaddleOCR models are auto-downloaded on first use.")
    print("Cache location: ~/.paddleocr/")
    print()
    print("To pre-download:")
    print("  python -c \"from paddleocr import PaddleOCR; PaddleOCR(lang='ch')\"")


def setup_models_links():
    """Create symbolic links for existing model directories."""
    
    # Link existing MinerU models from common cache locations
    mineru_models = MODELS_DIR / "mineru" / "models"
    if mineru_models.exists():
        print(f"MinerU models already linked: {mineru_models}")
        return
    
    common_paths = [
        Path.home() / ".cache" / "modelscope" / "hub" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1.0" / "models",
        Path.home() / ".mineru" / "models",
        PROJECT_ROOT.parent / "mineru" / "models",
    ]
    
    for path in common_paths:
        if path.exists():
            mineru_models.parent.mkdir(parents=True, exist_ok=True)
            mineru_models.symlink_to(path)
            print(f"Linked MinerU models: {mineru_models} -> {path}")
            return
    
    print("No existing MinerU models found. Run with --mineru to download.")


def main():
    parser = argparse.ArgumentParser(description="Download OCR models")
    parser.add_argument("--all", action="store_true", help="Download all models")
    parser.add_argument("--mineru", action="store_true", help="Download MinerU models")
    parser.add_argument("--deepseek", action="store_true", help="Show DeepSeek-OCR options")
    parser.add_argument("--paddleocr", action="store_true", help="Show PaddleOCR info")
    parser.add_argument("--setup-links", action="store_true", help="Setup symlinks to existing models")
    args = parser.parse_args()
    
    if args.all:
        download_mineru_models()
        download_deepseek_ocr_models()
        download_paddleocr_models()
    elif args.mineru:
        download_mineru_models()
    elif args.deepseek:
        download_deepseek_ocr_models()
    elif args.paddleocr:
        download_paddleocr_models()
    elif args.setup_links:
        setup_models_links()
    else:
        parser.print_help()
        print()
        print("Quick start:")
        print("  python scripts/download_models.py --setup-links  # Use existing models")
        print("  python scripts/download_models.py --mineru      # Download MinerU")


if __name__ == "__main__":
    main()