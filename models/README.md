# Models Directory

This directory contains OCR models for the LLM Wiki project.

## Structure

```
models/
├── mineru/           # MinerU PDF-Extract-Kit models
│   └── models/
│       ├── Layout/   # Layout detection
│       ├── MFR/      # Math formula recognition
│       ├── OCR/      # Text OCR
│       ├── TabCls/   # Table classification
│       └── TabRec/   # Table recognition
├── deepseek-ocr-v2/  # DeepSeek-OCR-2 Vision-Language model
│   └── model/        # ~6.3GB
├── logics-parsing-v2/ # Logics-Parsing Qwen3VL model
│   └── model/        # ~8.4GB
└── paddleocr/        # PaddleOCR models (auto-downloaded)
```

## Model Backends

### Default: PaddleOCR-VL-1.6 (external)

The official full-precision VLM is cached at
`/Users/wuliang/.paddlex/official_models/PaddleOCR-VL-1.6`, with PP-DocLayoutV3
beside it. The isolated Paddle/MLX runtime lives under
`/Users/wuliang/workspace/PaddleOCR-VL-1.6-MLX` and is intentionally not
duplicated in this directory.

### 1. MinerU (optional)

- High-precision PDF parsing
- Formula → LaTeX conversion
- Table → HTML conversion
- Pure CPU, no GPU required
- Model size: ~2GB

### 2. DeepSeek-OCR-2

- Vision-Language OCR model
- Document grounding and markdown conversion
- GPU/MPS/CPU support
- Model size: ~6.3GB

### 3. Logics-Parsing-v2

- Based on Qwen3VL
- Multi-modal document understanding
- HTML/Markdown output
- GPU/MPS/CPU support
- Model size: ~8.4GB

### 4. PaddleOCR

- 109 languages support
- Document unwarping
- Auto-downloaded on first use
- Model size: ~100MB per language

## Setup

Models are linked from external directories via symlinks:

```bash
# Check current links
ls -la models/*/

# Current structure:
# mineru/models -> ~/.cache/modelscope/.../PDF-Extract-Kit-1.0/models
# deepseek-ocr-v2/model -> ~/project/DeepSeek-OCR-2/models/DeepSeek-OCR-2
# logics-parsing-v2/model -> ~/project/Logics-Parsing/weights/Logics-Parsing-v2
```

## Configuration

Configure with the standalone `ocr` command. Settings are stored in
`~/.config/ocr/config.yaml`:

```bash
ocr use paddlevl
ocr config set paddlevl.options.model_path /path/to/PaddleOCR-VL-1.6
ocr config set deepseek.options.model_path /path/to/DeepSeek-OCR-2
ocr config set logics.options.model_path /path/to/Logics-Parsing-v2
ocr config set paddle.options.lang ch
```

## Usage

```bash
# List and select models
ocr list --check
ocr use paddlevl

# Use default (PaddleOCR-VL-1.6)
ocr document.pdf

# One-run override
ocr document.pdf --backend mineru
ocr document.pdf --backend deepseek

# Use Logics-Parsing (GPU/MPS required)
ocr document.pdf --backend logics

# Use PaddleOCR
ocr document.pdf --backend paddle
```

## Environment Variables

```bash
# MinerU
export MINERU_MODELS_PATH=models/mineru/models

# DeepSeek-OCR-2
export DEEPSEEK_OCR_MODEL_PATH=models/deepseek-ocr-v2/model

# Logics-Parsing
export LOGICS_PARSING_MODEL_PATH=models/logics-parsing-v2/model
```
