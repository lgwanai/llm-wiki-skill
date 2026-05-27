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
├── paddleocr/        # PaddleOCR models (auto-downloaded)
└── deepseek-ocr-v2/  # DeepSeek-OCR (optional, can use API)
```

## Download Models

### Quick Setup (Use Existing Models)

If you already have MinerU models installed elsewhere:

```bash
python scripts/download_models.py --setup-links
```

### Download All Models

```bash
python scripts/download_models.py --all
```

### Download Specific Models

```bash
# MinerU (required for default backend)
python scripts/download_models.py --mineru

# DeepSeek-OCR (optional - can use API)
python scripts/download_models.py --deepseek
```

## Model Backends

### MinerU (Default)

- High-precision PDF parsing
- Formula → LaTeX conversion
- Table → HTML conversion
- Pure CPU, no GPU required

Download size: ~2GB

### PaddleOCR

- 109 languages support
- Document unwarping
- Auto-downloaded on first use (~100MB per language)

### DeepSeek-OCR

- Vision-language model
- Can use API (no local model needed)
- Local inference requires GPU

## Configuration

Configure model paths in `wiki_config.yaml`:

```yaml
mineru:
  models_path: models/mineru/models
  lang: ch
  formula: true
  table: true

paddleocr:
  lang: ch
  use_doc_orientation_classify: true
  use_doc_unwarping: true

ocr:  # DeepSeek-OCR via API
  api_url: https://api.deepseek.com/v1/chat/completions
  api_key: your-api-key
  model: deepseek-v4-flash
```

## Environment Variables

```bash
# MinerU models path
export MINERU_MODELS_PATH=/path/to/models

# DeepSeek OCR API
export OCR_API_URL=https://api.deepseek.com/v1/chat/completions
export OCR_API_KEY=your-api-key
```
