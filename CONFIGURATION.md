# LLM Wiki v2 配置指南

配置文件只需要一份：`wiki_config.yaml`。运行 `wiki config --init` 会生成最小可用模板。

## 配置文件位置

查找优先级：

1. `LLM_WIKI_CONFIG` 指定的路径
2. 当前目录 `./wiki_config.yaml`
3. 父目录递归查找
4. `~/.config/llm-wiki/wiki_config.yaml`

## 推荐最小配置

```yaml
wiki_dir: .wiki

model:
  provider: deepseek
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com

ocr:
  mode: local
  backend: mineru
  options:
    models_path: models/mineru/models
    lang: ch

query:
  llm_synthesis: true
  max_results: 5
```

## 核心配置项

### `wiki_dir`

Wiki 数据目录。相对路径按当前项目根解析：优先使用当前目录/父目录中的 `wiki_config.yaml` 或已存在的 `.wiki`，否则使用当前工作目录。

```yaml
wiki_dir: .wiki
wiki_dir: ~/.wiki
wiki_dir: /data/wiki
```

也可以用环境变量覆盖：

```bash
export LLM_WIKI_DIR=/path/to/wiki
```

如果希望多个项目共享同一个知识库，请把 `wiki_dir` 写成绝对路径，或设置 `LLM_WIKI_DIR`。

### `model`

所有 LLM 调用统一使用 `model` 段，包括编译、查询和台账自然语言 SQL。

```yaml
model:
  provider: deepseek       # deepseek | openai | ollama | custom
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com
  temperature: 0.3
  max_tokens: 32000
```

OpenAI：

```yaml
model:
  provider: openai
  model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com
```

Ollama：

```yaml
model:
  provider: ollama
  model: llama3.2
  base_url: http://localhost:11434
  num_ctx: 32768
```

自定义 OpenAI-compatible endpoint：

```yaml
model:
  provider: custom
  api_url: http://localhost:8000/v1/chat/completions
  api_key: ${LLM_API_KEY}
  model: your-model
```

### `ocr`

OCR 统一使用一个 `ocr` 段。常规用户只需要改 `mode/backend/options`。

本地 OCR：

```yaml
ocr:
  mode: local
  backend: mineru          # mineru | deepseek | logics | paddle
  options:
    models_path: models/mineru/models
    lang: ch
    formula: true
    table: true
```

不同本地后端复用同一个 `options` 段：

```yaml
ocr:
  mode: local
  backend: deepseek
  options:
    model_path: models/deepseek-ocr-v2/model
    device: auto
```

API OCR：

```yaml
ocr:
  mode: api
  api_provider: siliconflow
  api_key: ${SILICONFLOW_API_KEY}
  pdf_dpi: 150
```

手动指定视觉 API：

```yaml
ocr:
  mode: api
  api_url: https://api.example.com/v1/chat/completions
  api_key: ${OCR_API_KEY}
  api_model: vision-model
  api_prompt: "Convert the document to clean markdown format."
```

### `query`

```yaml
query:
  llm_synthesis: true
  default_format: markdown
  max_results: 5
```

### `embeddings`

```yaml
embeddings:
  mode: local
  model: sentence-transformers/all-MiniLM-L6-v2
  dimension: 384
  backend: faiss
  cache_path: graph/embeddings.json
```

Ollama embedding：

```yaml
embeddings:
  mode: local
  model: ollama:nomic-embed-text
```

API embedding：

```yaml
embeddings:
  mode: api
  api_url: https://api.openai.com/v1/embeddings
  api_key: ${OPENAI_API_KEY}
  api_model: text-embedding-3-small
```

## 兼容旧配置

旧字段仍可读取，但不建议继续使用：

- `llm:` 会自动映射到 `model:`
- `ollama:` 和 `custom:` 会按 `model.provider` 合并
- `ocr_mode:` 会自动映射到 `ocr.backend`
- `mineru:`、`deepseek_ocr:`、`logics_parsing:`、`paddleocr:` 会自动合并到 `ocr.options`

新配置只写 `model` 和 `ocr`，不要再同时维护多套模型配置。
