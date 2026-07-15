---
name: llm-wiki
description: >
  Build and maintain a personal knowledge base using the LLM Wiki v2 pattern.
  Trigger when user mentions: wiki, knowledge base, kb, memory system, knowledge
  management, organizing notes, ingesting research, structured knowledge, "remember
  this", "file away", "add to wiki", "second brain", "build knowledge base", "set
  up wiki", accumulating and structuring information that compounds over time, or
  parsing PDF, Word, PowerPoint, EPUB, textbook, and exam sources before compiling
  them into traceable knowledge while preserving referenced images.
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
Raw Sources (.wiki/source/) — immutable, Agent reads never modifies
    ↓
Wiki (.wiki/pages/) — LLM maintains: entity pages, concept pages, index, log
    ↓
Schema (schema.md + wiki_config.yaml) — single source of truth for types & rules
```

## Dependencies

### `vision-skill` (optional, recommended for image sources)

Image-source compilation (`python scripts/compile_v2.py diagram.png`) recognizes images with
this precedence:

1. **vision-skill (preferred)** — the Agent invokes the `vision-skill` skill,
   which provides vision recognition (OCR, object detection, image
   description) via an OpenAI-compatible VL model. If `vision_skill.scripts_path`
   is set in `wiki_config.yaml`, the compile task also emits a concrete Python
   script command for the Agent:

   ```bash
   python <vision_skill.scripts_path>/vision_cli.py recognize \
     "<image>" --format markdown_note --wait
   ```

   Set `vision_skill.scripts_path` to the directory containing `vision_cli.py`
   from your vision-skill install. When left empty, the Agent invokes the skill
   by name only.

2. **OCR fallback** — if the vision-skill is not available, the configured
   `ocr` backend (mineru / paddle / deepseek / API) is used. OCR text is
   pre-extracted and attached to the compile task.

3. **Agent native capability** — if neither is available, the Agent reads the
   image directly with its own image-parsing capability.

The Python-side `image_analysis` vision API is **not** used in agent mode — it
is reserved for `--mode llm`, where no Agent is in the loop to invoke a skill.

## Commands

Run commands from the skill repository with Python scripts directly. Do **not**
assume the `wiki` / `llm-wiki` console scripts are installed; on Windows they
are often unavailable unless the user has completed CLI installation.

Use:

```bash
python scripts/<script>.py ...
```

On systems where `python` is not on PATH, use the platform launcher for the
same script, e.g. `py -3 scripts\<script>.py ...` on Windows or `python3
scripts/<script>.py ...` on Unix.

### `/wiki-compile <source>` — Ingest Source

Default mode is **Agent compile**. The current Agent reads the source directly,
decides the document type, and writes wiki pages according to `schema.md` and
the compile standard. No configured model/API key is required.

```bash
python scripts/compile_v2.py source.md
python scripts/compile_v2.py docs/                 # recursively compile supported files
python scripts/compile_v2.py docs/ --depth 1       # only direct files + one directory level
python scripts/compile_v2.py diagram.png           # vision-skill → OCR → Agent native (see Dependencies)
python scripts/compile_v2.py handbook.pdf          # every page rendered; OCR/vision/Agent fallback
python scripts/compile_v2.py handbook.docx         # Word pages rendered through PDF, with page provenance
python scripts/compile_v2.py slides.pptx           # every slide rendered; never first-slide-only
python scripts/compile_v2.py textbook.epub          # spine-ordered Markdown + extracted image links
python scripts/compile_v2.py source.md --force     # re-compile + detect contradictions
python scripts/compile_v2.py source.md --mode llm  # optional legacy path using configured model
```

**What happens:**
- Source sanitized (API keys, tokens, passwords, emails stripped)
- Directories are expanded recursively by default; `.wiki` and `.git` are skipped
- PDF/DOC/DOCX/PPT/PPTX are treated as paginated documents:
  - Render every page/slide to images first
  - If OCR is installed/configured, OCR each page image in order
  - If page rendering fails for a PDF, run the configured backend (MinerU by
    default) against the complete PDF before trying MarkItDown
  - MarkItDown output from a scanned PDF is partial evidence only; short,
    header-only, or page-incomplete output must never be compiled as the source
  - If OCR is unavailable, use configured vision/image analysis on each page image
  - If neither is available, preserve all page images under `.wiki/source/document_images/`
    and require the Agent to inspect them or ask the user
  - Never trust first-page-only extraction; every rendered page/slide must appear in the task output
  - Copy referenced/rendered images into `.wiki/pages/assets/` so the OKF bundle remains portable
  - For MinerU Markdown, retain the sibling `*_content_list.json`; compile restores page
    boundaries from its `page_idx` fields before creating knowledge pages
- EPUB follows its OPF spine order, extracts cover/chapter images into persistent assets,
  writes an auditable Markdown intermediate under `.wiki/source/epub_markdown/`, and
  keeps each image reference in the converted Markdown. Use `EPUB Section` and
  `EPUB locator` for provenance because reflowable EPUB has no reliable fixed page numbers;
  page unavailability must not block knowledge extraction.
- Other Office/document files use MarkItDown when available, otherwise Agent must inspect or ask for readable content
- Agent reads the content and dynamically routes it to one or more domain-expert lenses;
  source type (`doc`, `article`, `code`, `conversation`) is only a storage hint
- Legal/regulatory sources preserve article numbering and operative language, and organize
  applicability, exceptions, procedure, consequences, effective dates, and cross-references
- Sales/marketing policies preserve region, audience, product/channel, time window, thresholds,
  stacking/exclusions, approval, settlement, and expiry conditions as applicability matrices
- Academic sources preserve definitions, formulas, symbols, assumptions, derivations, evidence,
  limitations, citations, and concept/logic relationships
- Course outlines become reusable course knowledge maps linking audience, prerequisites,
  learning objectives, modules, knowledge points, activities, exercises, timing, and assessment
- Textbooks and exam papers become study-ready knowledge networks: textbook concepts retain
  definitions, formulas, prerequisites, examples, misconceptions, and related knowledge; exam
  questions retain stems, options, scores, answers, solutions, tested knowledge points, difficulty
  evidence, and error patterns, with bidirectional question—knowledge-point links. Every page
  must include `## 来源追溯` with original filename, one or more pages/page range, verbatim
  evidence, and corresponding images from cited/adjacent pages. Knowledge boundaries may cross
  pages and chunks; uncertain locations are marked `候选页范围/待核验` and never block extraction
- Mixed or unfamiliar documents may combine lenses or infer a more suitable expert; compilation
  uses content-driven granularity rather than fixed page counts, fact quotas, or entity ratios
- The built-in expert catalog also covers finance/accounting, operations, product management,
  software architecture, project management, HR, procurement/supply chain, manufacturing/quality,
  risk/audit, healthcare, education, textbook/exam learning, customer service, corporate strategy,
  and data/metric governance
- Agent generates structured Wiki pages (YAML frontmatter + Key Facts/Overview/Questions/Details/Relationships/Source Context)
- If the Agent cannot read the source, it must stop and ask the user for readable content
- **Cross-document entity protection**: same-named entities from different sources auto-prefixed (e.g., `coursepl-专家评审组`), concept aggregation pages auto-created
- Entity types dynamically loaded from `schema.md` (single source of truth)
- index.md + log.md updated
- Knowledge graph built: entities.json + edges.json (12 relationship types with Chinese/English keyword extraction)
- audit.json records the operation

### `/wiki-query <question>` — Search & Answer

Wiki-native search (metadata + page BM25F + compiled graph + complete DuckDB ledger), then the
current Agent synthesizes from already-compiled pages with citations. No
configured model/API key is required by default. Referenced images are resolved from each
retrieved page, included in synthesis context, and exposed in `images` and
`source_details[].images` in query results.

```bash
python scripts/query.py "What is X?"
python scripts/query.py "What is X?" --debug-search
python scripts/query.py "What is X?" --mode llm   # optional legacy path using configured model
python scripts/search.py --doctor
python scripts/search.py --eval .wiki/evals/retrieval.jsonl
python scripts/benchmark.py evals/rag_benchmark_smoke.jsonl --method both -k 5
# reports Hit/Recall/MRR/NDCG, complete recall, forbidden leakage, and P50/P95

# Fast mode — skip synthesis (0.5s)
python scripts/query.py "专家评审组" --no-synthesis

# Output formats
python scripts/query.py "compare" --format table
python scripts/query.py "history" --format timeline
python scripts/query.py "export" --format json

# File answer back as new wiki page
python scripts/query.py "Explain X" --file-back
```

| Mode | Flag | Time | Output |
|------|------|------|--------|
| Fast | `--no-synthesis` | 0.5s | Ranked list + snippets |
| Agent | default | local search + Agent | Synthesized answer + citations |
| LLM | `--mode llm` | model/API dependent | Configured-model synthesis |

Chinese search via jieba segmentation. English via BM25 + Porter stemming.
Search index cached to disk (`.wiki/graph/.bm25_index.json`), auto-invalidated on page changes.

Default retrieval quality features:

- Metadata search indexes OKF `title`, `description`, `tags`, `type`, and Concept ID.
- Page BM25F weights Concept ID, title, tags, description, key facts, headings, and body.
- Candidate streams over-fetch before scope/status filters and use intent-aware weighted RRF.
- Ledger search runs in DuckDB across all declared fields and rows; graph/ledger/vector can run concurrently.
- Graph search anchors natural-language questions to compiled entities and relationships.
- Query planning prioritizes ledger/graph/page streams by intent.
- Query rewriting adds only lightweight lexical variants by default.
- `python scripts/search.py --doctor` reports page, metadata, graph, and optional embedding health.
- `python scripts/search.py --eval <cases.jsonl>` measures Recall@K and MRR from jsonl eval cases.
- Embedded Zvec vector search and FlagEmbedding reranking are opt-in layers,
  not the default product path.

### `/wiki-lint` — Health Check

```bash
python scripts/lint.py              # Check only
python scripts/lint.py --auto-heal  # Check + fix
```

Checks: contradictions, stale claims, orphan pages, broken links, missing concepts.

### `/wiki-okf` — Native Open Knowledge Format v0.1 Storage

Validate, import, and export [Google Knowledge Catalog OKF v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
knowledge bundles:

```bash
python scripts/wiki.py okf validate path/to/bundle
python scripts/wiki.py okf import path/to/bundle
python scripts/wiki.py okf import path/to/bundle --force
python scripts/wiki.py okf export path/to/output-bundle
python scripts/wiki.py okf migrate
```

`.wiki/pages/` is the canonical OKF bundle, not a compatibility namespace. Compile writes
OKF fields directly; search/query derive Concept IDs from relative paths. Import merges
another bundle without metadata translation, export validates and copies the native bundle,
and `migrate` rewrites legacy page metadata in place.

### `/wiki-status` — Wiki Overview

```bash
python scripts/wiki.py status
```

### `/wiki-init` — Initialize

```bash
python scripts/wiki.py init
```

Creates `.wiki/` directory structure.

### `/wiki-update` — Update Skill

```bash
python scripts/update.py
```

Pulls latest code from GitHub, backs up old files to `backup/` (compressed with date stamp).

**What happens:**
- Current files compressed to `backup/llm-wiki-YYYYMMDD-HHMMSS.tar.gz`
- `git pull` from origin
- Reports files changed

### Other Commands

```bash
python scripts/bulk.py stats                  # Wiki analytics
python scripts/bulk.py clean --dry-run        # Preview orphan cleanup
python scripts/consolidate.py                 # Memory tier promotion + decay
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
python scripts/ledger.py create "项目台账" \
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
python scripts/ledger.py insert "项目台账" \
  --data '{"项目名称":"智能系统","负责人":"张三","预算":50}'

# 批量插入
python scripts/ledger.py insert "项目台账" \
  --data '[{"项目名称":"项目A","负责人":"李四"},{"项目名称":"项目B","负责人":"王五"}]'

# 容错模式（跳过错误行，继续处理）
python scripts/ledger.py insert "项目台账" --data '[...]' --batch
```

**查询和管理：**

```bash
python scripts/ledger.py list                # 列出所有表
python scripts/ledger.py show "项目台账"      # 查看表结构 + 前20行数据
python scripts/ledger.py stats               # 所有表统计
python scripts/ledger.py stats "项目台账"     # 单表统计
```

**修改表结构：**

```bash
# 添加字段
python scripts/ledger.py update-schema "项目台账" \
  --add '[{"name":"备注","type":"text"}]'

# 删除字段
python scripts/ledger.py update-schema "项目台账" --remove "旧字段"

# 重命名字段
python scripts/ledger.py update-schema "项目台账" --rename "旧名:新名"

# 修改字段类型（自动迁移数据）
python scripts/ledger.py update-schema "项目台账" \
  --modify '[{"name":"预算","type":"integer"}]'

# 删除表格
python scripts/ledger.py delete "项目台账"
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
创建表格并插入数据后，`python scripts/query.py` 会自动搜索表格中的结构化数据，与 Wiki 页面结果合并返回。支持 BM25 关键词检索和向量语义检索两种模式。

```bash
# 表格检索 / 自然语言问答
python scripts/ledger.py search "项目"
python scripts/wiki.py ledger ask "项目台账" "预算最高的是哪个项目？"
```

**典型工作流：**

```
用户: 帮我创建一个项目台账
Claude: [询问字段、唯一键、是否需要编号]
用户: 需要项目名称、负责人、开始日期、预算。项目名称唯一，要自动编号。
Claude: [调用 python scripts/ledger.py create]
用户: 帮我加一条，智能系统开发项目，张三负责，1月15开始，50万预算
Claude: [解析自然语言 → 结构化JSON → 调用 python scripts/ledger.py insert]
用户: 再加一个备注字段
Claude: [调用 python scripts/ledger.py update-schema --add]
```

## Configuration

Single config file: `wiki_config.yaml` (copy from `.example`). Config is gitignored.

```yaml
compile:
  mode: agent                  # default; no configured LLM required

# Optional only for `python scripts/compile_v2.py --mode llm` or query synthesis
# model:
#   provider: deepseek
#   model: "deepseek-v4-flash"
#   api_key: "sk-xxx"

ocr:
  mode: local
  backend: mineru
  options:
    models_path: models/mineru/models
    lang: ch
    formula: true
    table: true

image_analysis:                    # --mode llm only; agent mode uses vision_skill below
  enabled: false                  # true to analyze image sources before OCR
  api_provider: openai            # siliconflow | openai | deepseek | paddleocr-vl
  api_url: ""                     # optional OpenAI-compatible API URL
  api_key: "${OPENAI_API_KEY}"
  api_model: gpt-4o
  ocr_fallback: true              # append OCR text for dense screenshots/docs

vision_skill:                     # agent-mode image sources: vision-skill → OCR → Agent
  enabled: true
  scripts_path: ""                # dir containing vision_cli.py; empty = invoke skill by name only
  recognize_format: markdown_note              # vision_cli --format preset

query:
  llm_synthesis: true
  synthesis_mode: agent        # agent=默认由当前 Agent 合成, llm=使用配置模型

retention:
  architecture: {half_life_days: 180}
  bug: {half_life_days: 20}

quality:
  auto_heal: true
  min_score: 0.4
```

## OCR Pipeline

Pluggable backends, default via `ocr.backend` config.

Use the unified command below. Do not inspect MinerU ad hoc, write a temporary OCR
harness, or guess which Python environment is active. The preflight and manifest are
the stable contracts for Agent use.

```bash
# 1. Preflight once per interpreter/environment
python scripts/ocr.py --doctor --json

# 2. For a new or previously failing document, verify exactly three pages
python scripts/ocr.py document.pdf --smoke-pages 3 --json

# 3. Run the full document
python scripts/ocr.py document.pdf -o .wiki/source/document/ --json

# Explicit backend
python scripts/ocr.py document.pdf --backend paddle
python scripts/ocr.py document.pdf --backend deepseek

# PDF → Wiki full pipeline
python scripts/ocr.py paper.pdf -o .wiki/source/paper/
python scripts/compile_v2.py .wiki/source/paper/paper/pipeline/paper.md
```

For MinerU, `--doctor` must report `ready: true` and version `>=3.4.4,<4` before
parsing. If it fails, run the exact `repair_command` returned by the report in the
reported Python interpreter. Never silently fall back to another interpreter.

For PDF, Word, and PowerPoint runs, read the automatically generated
`<source>_ocr_manifest.json` rather than inferring success from process output. Treat
`coverage_complete: false` as an incomplete parse. A null coverage value is not a
reason to discard extracted knowledge; retain the content and mark page provenance as
pending verification. The manifest's Markdown, content-list, page, and image fields
are the inputs to compile and source registration.

| Backend | Engine | Strengths | GPU |
|---------|--------|-----------|-----|
| `mineru` ★ | MinerU 3.4.4 | Formula→LaTeX, table→HTML, multi-column, all formats | No (4GB RAM) |
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
| `wiki.py` | Unified script entry for init/status and grouped commands |
| `compile_v2.py` | Source → wiki pages + graph |
| `query.py` | Search + synthesize + file-back (6 formats) |
| `search.py` | Hybrid search: BM25 + graph + RRF |
| `graph.py` | Knowledge graph: entities, edges, traversal |
| `lint.py` | Health check + auto-heal |
| `consolidate.py` | Memory tier promotion + decay |
| `crystallize.py` | Session → digest |
| `bulk.py` | Bulk operations |
| `ocr/cli.py` | Stable OCR interface, preflight, smoke test, and manifest |
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

Extracted from standard Markdown concept links and their surrounding relationship prose.
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

## Dream Self-Looping

The dream **directly modifies content** — no human confirmation needed.
It's an unattended self-looping system with git snapshots, quality gating,
auto-rollback, and experience accumulation:

```bash
python scripts/dream.py --foreground   # Run synchronously
python scripts/dream.py                # Run in background
```

### What happens

```
Phase 1 (Light Sleep)     ← updates page metadata from today's queries
Phase 2 (Audit)           ← aggregates 7d logs → feeds Phase 3+4
Phase 3 (Purify)          ← detects duplicates → merges → quality check → keep/rollback
Phase 4 (Enrich)          ← enriches low-density pages → quality check → keep/rollback
```

### Safety guarantees

| Guard | Mechanism |
|-------|-----------|
| **Git snapshots** | Every modification is preceded by a `git commit` in `.wiki/.git`. |
| **Quality gating** | Before/after search results are compared across 3 dimensions (rank preservation, density, coverage). |
| **Auto-rollback** | If quality degrades below threshold (-0.15), `git checkout` restores the pre-modification state. |
| **Experience accumulation** | Degradations and lessons are recorded to `.wiki/dream/experiences.md` with deduplication. |

### Quality metrics

| Metric | Weight | What it measures |
|--------|--------|-----------------|
| Rank preservation | 0.40 | Did target pages maintain/improve search rank? |
| Density improvement | 0.30 | Did page content become richer? |
| Coverage score | 0.30 | Are all expected pages still findable? |

### Experience store

`.wiki/dream/experiences.md` — lessons learned from dream runs.  Each experience
is SHA256-deduplicated; repeated lessons increment a recurrence counter instead
of creating duplicates.  Max 100 entries; oldest single-occurrence entries
evicted first.  Experiences are loaded as context for future dream runs.

## Doctor Command

Report issues and trigger automatic diagnosis + repair:

```bash
# Natural language feedback (primary interface)
python scripts/doctor.py "专家评审组的信息不完整，缺少成员名单和评审流程"

# Targeted diagnosis
python scripts/doctor.py --check coursepl-专家评审组

# Direct repair actions
python scripts/doctor.py --recompile .wiki/source/doc.md
python scripts/doctor.py --re-ocr .wiki/source/slides.pptx

# Issue tracking
python scripts/doctor.py --list                        # List outstanding issues
python scripts/doctor.py --resolve iss-20260627-001    # Mark resolved
```

### Issue types and repair strategies

| Category | Detection keywords | Repair |
|----------|-------------------|--------|
| `missing_info` | 遗漏, 缺少, 缺失, 不全, 没有, 找不到 | Search sources → recompile |
| `incorrect_info` | 错误, 不对, 不正确, 识别错, 写错了 | Compare source → mark for review |
| `uncompiled` | 未编译, 没编译, 没入库, 没导入 | Locate source → compile |
| `ocr_missed` | OCR遗漏, PPT遗漏, 扫描不全, 解析遗漏 | Re-OCR → recompile |
| `search_quality` | 搜不到, 检索不到, 查不到, 排名低 | Update metadata (keywords, aliases) |
| `contradiction` | 矛盾, 冲突, 不一致 | Mark contradiction flags |
| `outdated` | 过时, 过期, 旧信息, 不再适用 | Mark stale status |

### Workflow

```
User feedback → classify (regex) → diagnose (wiki search) →
repair (strategy-specific) → verify (re-search) → persist (issues.json)
```

Issues are tracked in `.wiki/doctor/issues.json` for cross-session follow-up.

## Design Heritage

- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [Rohit's LLM Wiki v2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)

100% Karpathy v1 + 100% Rohit v2 core features.
