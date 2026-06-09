---
name: llm-wiki
description: >
  Build and maintain a personal knowledge base using the LLM Wiki v2 pattern.
  Trigger when user mentions: wiki, knowledge base, kb, memory system, knowledge
  management, organizing notes, ingesting research, structured knowledge, "remember
  this", "file away", "add to wiki", "second brain", "build knowledge base", "set
  up wiki", accumulating and structuring information that compounds over time.
COMMANDS: >
  /wiki-compile, /wiki-query, /wiki-lint, /wiki-embed, /wiki-bulk,
  /wiki-consolidate, /wiki-status, /wiki-init, /wiki-update, /wiki-ledger.
---

# LLM Wiki v2

Stop re-deriving. Start compiling.

RAG retrieves and forgets. A wiki accumulates and compounds. This skill turns
Claude into a disciplined knowledge librarian — reading sources, extracting entities,
building a typed knowledge graph, and maintaining everything as knowledge evolves.

100% compliant with [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and [Rohit's v2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2).

## Core Idea

```
RAG:    Source → [检索] → LLM 即时合成 → 回答 → 丢弃
Wiki:   Source → [编译] → Wiki 持久化 → 查询时直接使用已有知识
```

## Architecture

```
Raw Sources (.wiki/source/) — immutable, LLM reads never modifies
    ↓
Wiki (.wiki/pages/) — LLM maintains: entity pages, concept pages, index, log
    ↓
Schema (schema.md + wiki_config.yaml) — single source of truth for types & rules
```

## Commands

Use the installed shell CLI (`wiki ...`, or the alias `llm-wiki ...`) for all commands.

### `/wiki-compile <source>` — Ingest Source

LLM reads source document, extracts entities, builds typed knowledge graph.

```bash
wiki compile source.md
wiki compile docs/                 # recursively compile supported files
wiki compile docs/ --depth 1       # only direct files + one directory level
wiki compile diagram.png           # image source via image analysis/OCR config
wiki compile source.md --force  # re-compile + detect contradictions
```

**What happens:**
- Source sanitized (API keys, tokens, passwords, emails stripped)
- Directories are expanded recursively by default; `.wiki` and `.git` are skipped
- Images are converted to markdown before compile, with the original image path retained as source context
- LLM generates 10–20 structured Wiki pages (YAML frontmatter + Overview/Key Details/Relationships/Source Context)
- **Cross-document entity protection**: same-named entities from different sources auto-prefixed (e.g., `coursepl-专家评审组`), concept aggregation pages auto-created
- Entity types dynamically loaded from `schema.md` (single source of truth)
- index.md + log.md updated
- Knowledge graph built: entities.json + edges.json (12 relationship types with Chinese/English keyword extraction)
- audit.json records the operation

### `/wiki-query <question>` — Search & Answer

Hybrid search (BM25 + Graph + RRF fusion), LLM synthesizes answer with citations.

```bash
wiki query "What is X?"
wiki query "What is X?" --debug-search
wiki search doctor
wiki search eval .wiki/evals/retrieval.jsonl
wiki embed --chunks --force

# Fast mode — skip LLM synthesis (0.5s)
wiki query "专家评审组" --no-synthesis

# Output formats
wiki query "compare" --format table
wiki query "history" --format timeline
wiki query "export" --format json

# File answer back as new wiki page
wiki query "Explain X" --file-back
```

| Mode | Flag | Time | Output |
|------|------|------|--------|
| Fast | `--no-synthesis` | 0.5s | Ranked list + snippets |
| LLM | default | 2.7s | Synthesized answer + citations |

Chinese search via jieba segmentation. English via BM25 + Porter stemming.
Search index cached to disk (`.wiki/graph/.bm25_index.json`), auto-invalidated on page changes.

Retrieval quality features:

- Chunk-level search retrieves the relevant section instead of only the page start.
- Metadata search indexes `aliases`, `keywords`, `questions`, and `summary`.
- Chunk vector search retrieves semantically relevant sections when `wiki embed --chunks` has run.
- Query planning prioritizes ledger/graph/page streams by intent.
- Query rewriting adds lightweight lexical variants for recall.
- Lightweight reranking improves final ordering after RRF.
- Embedding index metadata prevents page/query embedding model mismatch.
- `wiki search doctor` reports stale embeddings, chunk coverage, and graph health.
- `wiki search eval` measures Recall@K and MRR from jsonl eval cases.

### `/wiki-lint` — Health Check

```bash
wiki lint              # Check only
wiki lint --auto-heal  # Check + fix
```

Checks: contradictions, stale claims, orphan pages, broken links, missing concepts.

### `/wiki-status` — Wiki Overview

```bash
wiki status
```

### `/wiki-init` — Initialize

```bash
wiki init
```

Creates `.wiki/` directory structure.

### `/wiki-update` — Update Skill

```bash
wiki update
```

Pulls latest code from GitHub, backs up old files to `backup/` (compressed with date stamp).

**What happens:**
- Current files compressed to `backup/llm-wiki-YYYYMMDD-HHMMSS.tar.gz`
- `git pull` from origin
- Reports files changed

### Other Commands

```bash
wiki embed --force          # Regenerate vector embeddings
wiki bulk stats             # Wiki analytics
wiki bulk clean --dry-run   # Preview orphan cleanup
python3 scripts/consolidate.py                 # Memory tier promotion + decay
```

### `/wiki-ledger` — 台账管理 (Ledger, DuckDB 后端)

结构化表格管理，基于 DuckDB 引擎，支持字段验证、唯一约束、自增序列、向量嵌入。

**创建表格（多轮对话）：**

Claude 会在创建前逐一确认：
1. 表格名称和用途
2. 字段定义（名称、类型、是否必填、备注）
3. 唯一键字段（哪个字段不能重复？）
4. 是否需要自动编号

```bash
# 创建表格
wiki ledger create "项目台账" \
  --fields '[{"name":"项目名称","type":"string","required":true},{"name":"负责人","type":"string","required":true},{"name":"预算","type":"number"}]' \
  --unique "项目名称" \
  --auto-increment \
  --description "项目管理台账"
```

**用户命名 vs 实际表名：**
- 用户给的是显示名称（如"项目台账"），可以中文
- 系统自动生成安全的实际表名（如 `table_a1b2c3d4` 或 `project_ledger`）
- 映射关系维护在 `.wiki/ledger/ledger.duckdb` 的 `_registry` 表中
- 所有命令都支持用显示名称或实际名称引用表

**插入数据（自然语言）：**

用户用自然语言描述数据，Claude 自动提取字段信息、校验类型、检查唯一约束：

```bash
# 单行插入
wiki ledger insert "项目台账" \
  --data '{"项目名称":"智能系统","负责人":"张三","预算":50}'

# 批量插入
wiki ledger insert "项目台账" \
  --data '[{"项目名称":"项目A","负责人":"李四"},{"项目名称":"项目B","负责人":"王五"}]'

# 容错模式（跳过错误行，继续处理）
wiki ledger insert "项目台账" --data '[...]' --batch
```

**查询和管理：**

```bash
wiki ledger list                # 列出所有表
wiki ledger show "项目台账"      # 查看表结构 + 前20行数据
wiki ledger stats               # 所有表统计
wiki ledger stats "项目台账"     # 单表统计
```

**修改表结构：**

```bash
# 添加字段
wiki ledger update-schema "项目台账" \
  --add '[{"name":"备注","type":"text"}]'

# 删除字段
wiki ledger update-schema "项目台账" --remove "旧字段"

# 重命名字段
wiki ledger update-schema "项目台账" --rename "旧名:新名"

# 修改字段类型（自动迁移数据）
wiki ledger update-schema "项目台账" \
  --modify '[{"name":"预算","type":"integer"}]'

# 删除表格
wiki ledger delete "项目台账"
```

**支持的数据类型：**

| 类型 | 说明 | 示例 |
|------|------|------|
| `string` | 单行文本 | "张三" |
| `text` | 多行文本 | "备注内容..." |
| `integer` | 整数 | 100 |
| `number` | 数字（含小数） | 50.5 |
| `boolean` | 布尔值 | true |
| `date` | 日期 | "2026-01-15" |
| `datetime` | 日期时间 | "2026-01-15T10:30:00" |

**存储结构（DuckDB）：**

```
.wiki/ledger/
├── ledger.duckdb              # DuckDB 数据库文件
│   ├── _registry             # 元数据表（显示名 → 实际名映射 + schema）
│   ├── _embeddings           # 向量嵌入表（支持语义检索）
│   ├── <actual_name>         # 用户表（SQL 类型列）
│   └── seq_<actual_name>     # 自增序列
└── registry.json / index.json  # 旧 JSON 格式（自动迁移后保留）
```

**表格数据参与 Wiki 检索：**
创建表格并插入数据后，`wiki query` 会自动搜索表格中的结构化数据，与 Wiki 页面结果合并返回。支持 BM25 关键词检索和向量语义检索两种模式。

```bash
# 生成表格向量嵌入（启用语义检索）
wiki ledger embed "项目台账"
wiki ledger embed   # 所有表
```

**典型工作流：**

```
用户: 帮我创建一个项目台账
Claude: [询问字段、唯一键、是否需要编号]
用户: 需要项目名称、负责人、开始日期、预算。项目名称唯一，要自动编号。
Claude: [调用 wiki ledger create]
用户: 帮我加一条，智能系统开发项目，张三负责，1月15开始，50万预算
Claude: [解析自然语言 → 结构化JSON → 调用 wiki ledger insert]
用户: 再加一个备注字段
Claude: [调用 wiki ledger update-schema --add]
```

## Configuration

Single config file: `wiki_config.yaml` (copy from `.example`). Config is gitignored.

```yaml
model:
  provider: deepseek
  model: "deepseek-v4-flash"
  api_key: "sk-xxx"

ocr:
  mode: local
  backend: mineru
  options:
    models_path: models/mineru/models
    lang: ch
    formula: true
    table: true

image_analysis:
  enabled: false                  # true to analyze image sources before OCR
  api_provider: openai            # siliconflow | openai | deepseek | paddleocr-vl
  api_url: ""                     # optional OpenAI-compatible API URL
  api_key: "${OPENAI_API_KEY}"
  api_model: gpt-4o
  ocr_fallback: true              # append OCR text for dense screenshots/docs

query:
  llm_synthesis: true          # true=LLM合成, false=仅搜索

retention:
  architecture: {half_life_days: 180}
  bug: {half_life_days: 20}

quality:
  auto_heal: true
  min_score: 0.4
```

## OCR Pipeline

Pluggable backends, default via `ocr.backend` config.

```bash
# Default (from config)
python3 scripts/ocr.py document.pdf

# Explicit backend
python3 scripts/ocr.py document.pdf --backend paddle
python3 scripts/ocr.py document.pdf --backend deepseek

# PDF → Wiki full pipeline
python3 scripts/ocr.py paper.pdf -o .wiki/source/paper/
wiki compile .wiki/source/paper/paper/auto/paper.md
```

| Backend | Engine | Strengths | GPU |
|---------|--------|-----------|-----|
| `mineru` ★ | MinerU 3.1 | Formula→LaTeX, table→HTML, multi-column, all formats | No (4GB RAM) |
| `paddle` | PaddleOCR 3.5 | 109 languages, doc unwarping, orientation fix | No |
| `deepseek` | DeepSeek-OCR | Grounding + image crop | GPU or API |

## Directory Structure

```
.wiki/
├── pages/
│   ├── concepts/          # Abstract ideas (cross-document)
│   ├── entities/          # Concrete things (source-prefixed)
│   └── index.md           # Human-readable catalog by type
├── graph/
│   ├── entities.json      # Entity registry
│   ├── edges.json         # Typed relationships (12 types)
│   ├── .bm25_index.json   # Disk-cached search index
│   └── embeddings.json    # Vector embeddings
├── source/                # Raw source documents (immutable)
├── memory/                # Consolidation tiers
├── audit.json             # Full operation log
├── log.md                 # Chronological log
└── schema.md              # Entity types, relationship types, quality rules
```

## Scripts

| Script | Purpose |
|--------|---------|
| `wiki.py` | Unified CLI |
| `compile_v2.py` | Source → wiki pages + graph |
| `query.py` | Search + synthesize + file-back (6 formats) |
| `search.py` | Hybrid search: BM25 + graph + RRF |
| `graph.py` | Knowledge graph: entities, edges, traversal |
| `lint.py` | Health check + auto-heal |
| `consolidate.py` | Memory tier promotion + decay |
| `crystallize.py` | Session → digest |
| `bulk.py` | Bulk operations |
| `ocr.py` | OCR interface (3 backends) |
| `_mineru_ocr.py` | MinerU wrapper |
| `_paddle_ocr.py` | PaddleOCR wrapper |
| `_deepseek_ocr.py` | DeepSeek-OCR wrapper |

## Key Features

### Cross-Document Entity Protection

Same-named entities from different sources never overwrite:

```
Source A → 专家评审组.md (members: A)
Source B → coursepl-专家评审组.md (auto-prefix, members: B)
        → concepts/专家评审组.md (auto-aggregated: lists both)
```

Query "专家评审组怎么构成?" → reads concept page → cross-document synthesis.
Query "A的专家组有谁?" → exact hit on `专家评审组.md`.

### 12 Relationship Types

`uses` | `depends_on` | `extends` | `improves_upon` | `contradicts` | `supersedes` | `caused_by` | `fixed_by` | `replaces` | `relates_to` | `part_of` | `implemented_by`

Extracted from wikilinks via 41 Chinese keywords + 12 English regex patterns.
LLM prompt enforces explicit relationship keyword prefix.

### Schema-Driven Types

Entity types loaded dynamically from `schema.md`. Update the schema to change
what types the LLM can classify — no code changes needed.

### Quality & Lifecycle

| Feature | Mechanism |
|---------|-----------|
| Confidence | YAML frontmatter `confidence` field, +0.05 per reinforcement |
| Forgetting | Ebbinghaus curves (arch 260d, bug 20d...) |
| Contradictions | Auto-detected on re-compile, severity scored |
| Self-healing | `lint --auto-heal` fixes orphans, broken links |
| Audit | Every operation logged with timestamp + reason |
| Privacy | 5 sensitive-data patterns stripped before LLM ingestion |

## Design Heritage

- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [Rohit's LLM Wiki v2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)

100% Karpathy v1 + 100% Rohit v2 core features.
