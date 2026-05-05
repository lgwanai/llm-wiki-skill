#!/usr/bin/env python3
"""
ocr_server.py — 本地 PaddleOCR-VL-1.5 推理服务

启动一个 HTTP 服务，接收图片/PDF 并返回 OCR 结果。
模型从 ~/.models/PaddleOCR-VL-1.5/ 加载。

Usage:
    python ocr_server.py                          # 默认端口 8765
    python ocr_server.py --port 8866              # 自定义端口
    python ocr_server.py --model ~/.models/PaddleOCR-VL-1.5  # 自定义模型路径
    python ocr_server.py --cpu                    # CPU 模式

API:
    POST /ocr/image   ← multipart file: image    → {"text": "...", "markdown": "..."}
    POST /ocr/pdf     ← multipart file: pdf      → {"pages": [{"num":1,"text":"..."}], "combined":"..."}
    GET  /health      → {"status": "ok", "model": "PaddleOCR-VL-1.5"}
"""

import argparse
import io
import json
import os
import sys
import traceback

import torch
from flask import Flask, request, jsonify

MODEL_PATH = os.path.expanduser("~/.models/PaddleOCR-VL-1.5")
MODEL: object = None
PROCESSOR: object = None
DEVICE = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"

app = Flask(__name__)


def load_model(model_path: str, device: str = DEVICE) -> tuple:
    """Load PaddleOCR-VL-1.5 model and processor from local path."""
    from transformers import AutoProcessor, AutoModelForImageTextToText

    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16 if device != "cpu" else torch.float32,
        trust_remote_code=True,
    ).to(device).eval()

    return model, processor


def ocr_image_bytes(image_bytes: bytes, filename: str = "image.png") -> str:
    """Run OCR on image bytes, return markdown text."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": img},
                {"type": "text", "text": "OCR:"},
            ],
        }
    ]

    prompt = PROCESSOR.apply_chat_template(messages, add_generation_prompt=True)
    inputs = PROCESSOR(text=prompt, images=[img], return_tensors="pt").to(DEVICE)

    with torch.inference_mode():
        generated_ids = MODEL.generate(**inputs, max_new_tokens=4096, do_sample=False)
    generated_ids = generated_ids[:, inputs["input_ids"].shape[1]:]
    result = PROCESSOR.batch_decode(generated_ids, skip_special_tokens=True)[0]

    return result.strip()


def ocr_pdf_bytes(pdf_bytes: bytes) -> dict:
    """Run OCR on PDF, return per-page and combined text."""
    try:
        import fitz
    except ImportError:
        return {"error": "PyMuPDF (fitz) not installed. Run: pip install PyMuPDF"}

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")

        text = ocr_image_bytes(img_bytes, f"page_{page_num+1}.png")
        pages.append({"num": page_num + 1, "text": text})

    combined = "\n\n".join(f"## Page {p['num']}\n{p['text']}" for p in pages)
    return {"pages": pages, "combined": combined, "page_count": len(pages)}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": "PaddleOCR-VL-1.5", "device": DEVICE})


@app.route("/ocr/image", methods=["POST"])
def ocr_image_endpoint():
    if "image" not in request.files:
        return jsonify({"error": "No 'image' file in request"}), 400

    file = request.files["image"]
    try:
        image_bytes = file.read()
        text = ocr_image_bytes(image_bytes, file.filename or "image.png")
        return jsonify({"text": text, "markdown": text})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/ocr/pdf", methods=["POST"])
def ocr_pdf_endpoint():
    if "pdf" not in request.files:
        return jsonify({"error": "No 'pdf' file in request"}), 400

    file = request.files["pdf"]
    try:
        pdf_bytes = file.read()
        result = ocr_pdf_bytes(pdf_bytes)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def main():
    global MODEL, PROCESSOR, DEVICE

    parser = argparse.ArgumentParser(description="PaddleOCR-VL-1.5 Local Server")
    parser.add_argument("--port", type=int, default=8765, help="Server port (default: 8765)")
    parser.add_argument("--model", default=MODEL_PATH,
                        help=f"Model path (default: {MODEL_PATH})")
    parser.add_argument("--cpu", action="store_true", help="Force CPU mode")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    args = parser.parse_args()

    if args.cpu:
        DEVICE = "cpu"

    if not os.path.exists(args.model):
        print(f"Model not found at {args.model}")
        print("Run download_models.py first:")
        print("  python scripts/download_models.py")
        sys.exit(1)

    print(f"Loading PaddleOCR-VL-1.5 from {args.model} ...")
    print(f"Device: {DEVICE}")
    MODEL, PROCESSOR = load_model(args.model, DEVICE)
    print(f"✓ Model loaded. Starting server on http://{args.host}:{args.port}")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
