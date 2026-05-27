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

### 1. MinerU (Default)

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

Configure in `wiki_config.yaml`:

```yaml
# MinerU (default)
mineru:
  models_path: models/mineru/models
  lang: ch
  formula: true
  table: true

# DeepSeek-OCR-2
deepseek_ocr:
  model_path: models/deepseek-ocr-v2/model
  device: mps  # mps | cuda | cpu

# Logics-Parsing-v2
logics_parsing:
  model_path: models/logics-parsing-v2/model
  device: mps

# PaddleOCR
paddleocr:
  lang: ch
  use_doc_orientation_classify: true
```

## Usage

```bash
# Use default (MinerU)
python scripts/ocr.py document.pdf

# Use DeepSeek-OCR-2 (GPU/MPS required for local inference)
python scripts/ocr.py document.pdf --backend deepseek

# Use Logics-Parsing (GPU/MPS required)
python scripts/ocr.py document.pdf --backend logics

# Use PaddleOCR
python scripts/ocr.py document.pdf --backend paddle
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
