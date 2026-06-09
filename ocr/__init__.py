"""ocr — Image & PDF OCR with pluggable backends.

Backends:
    mineru  (default): MinerU v3.x — high-precision pipeline, formula→LaTeX, table→HTML.
    deepseek:          DeepSeek-OCR-2 — Vision-Language OCR, GPU/MPS/CPU.
    logics:            Logics-Parsing-v2 — Qwen3VL-based OCR, GPU/MPS/CPU.
    paddle:            PaddleOCR — PP-OCRv5, 109 languages, doc unwarping.
    api:               Generic API — OpenAI-compatible vision API.

Usage:
    from ocr._mineru_ocr import MinerUOCR
    from ocr._ocr_api import OCRApiBackend
    from ocr.cli import main
"""
