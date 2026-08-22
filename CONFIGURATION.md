# LLM Wiki v2 配置指南

Wiki 使用 `wiki_config.yaml`；独立 OCR 使用 `~/.config/ocr/config.yaml`。
运行 `wiki config --init` 会生成最小可用 Wiki 模板。

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

OCR 已独立为系统模块，不再由项目内 `wiki_config.yaml` 决定默认模型。
全局配置位于 `~/.config/ocr/config.yaml`，可用 `OCR_CONFIG` 覆盖路径。

常用命令：

```bash
ocr list --check
ocr use paddlevl
ocr config show
ocr config set paddlevl.options.model_path /path/to/PaddleOCR-VL-1.6
ocr config set api.api_url https://api.example.com/v1/chat/completions
ocr config set api.api_key '${OCR_API_KEY}'
```

每个模型拥有独立的参数段：

```yaml
default_model: paddlevl
models:
  paddlevl:
    pdf_dpi: 200
    options:
      inference_backend: mlx-vlm-server
  deepseek:
    options:
      model_path: /path/to/DeepSeek-OCR-2
      device: mps
  api:
    mode: api
    api_url: https://api.example.com/v1/chat/completions
    api_key: ${OCR_API_KEY}
    api_model: vision-model
```

### `query`

```yaml
query:
  llm_synthesis: true
  synthesis_mode: agent
  default_format: markdown
  max_results: 5
  search_streams: metadata,bm25,graph,ledger
  llm_query_expansion: false
  cross_language_expansion: true
  multi_hop_enabled: true
  multi_hop_max_hops: 3
```

`multi_hop_max_hops` 最大为 5。默认值 3 会把复合问题拆成答案子目标，根据尚未满足的
子目标筛选后续知识链接，并对不同查询、不同跳次的分数进行归一化。全部子目标获得直接
证据、没有相关后续路径或达到跳数上限时停止。使用 `--single-hop` 可以进行诊断和 A/B
基准测试。

页面仍是规范存储单位，但每个 Markdown 标题段落会产生独立 BM25 信号；检索结果随后按
子目标覆盖度去重，避免比较问题的 Top-K 被同一侧的近重复页面占满。调试输出会显示每跳
覆盖率、缺失子目标和停止原因。

`cross_language_expansion` 不调用外部模型。它复用页面中的双语标题、别名、关键词和问题，
并读取可选的 `.wiki/query_lexicon.yaml`：

```yaml
terms:
  熔断窗口: circuit breaker window
  回滚审批: [rollback approval, rollback authorization]
```

`agent` is the default synthesis mode. Search runs locally over the compiled
wiki, then the current Agent answers from the retrieved pages. Use
`wiki query --mode llm` only when you explicitly want the configured model/API
to synthesize the answer.

### `compile`

```yaml
compile:
  mode: agent
```

`agent` is the default. The current Agent reads sources, decides whether each
source is `doc`, `article`, `code`, or `conversation`, and writes pages according
to `schema.md`. Use `wiki compile --mode llm` only when you explicitly want the
configured model/API path.

### `embeddings`

Embeddings are optional for experiments and benchmarks. They are not part of
the default LLM Wiki query path, which searches compiled pages and graph data
directly.

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

旧字段仍可由配置加载器读取，但 OCR 运行时以独立配置为准：

- `llm:` 会自动映射到 `model:`
- `ollama:` 和 `custom:` 会按 `model.provider` 合并
- 旧 `ocr_mode:`、`ocr:` 和各后端段仅保留解析兼容；请迁移到 `ocr use` / `ocr config`

新 Wiki 配置不再写 OCR 模型参数，避免项目配置与系统默认相互覆盖。
