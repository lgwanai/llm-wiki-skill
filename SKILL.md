---
name: llm-wiki
description: >
  Build and maintain a personal knowledge base using the LLM Wiki v2 pattern.
  Trigger when user mentions: wiki, knowledge base, kb, memory system, knowledge
  management, organizing notes, ingesting research, structured knowledge, "remember
  this", "file away", "add to wiki", "second brain", "build knowledge base", "set
  up wiki", accumulating and structuring information that compounds over time.
COMMANDS: /wiki-compile, /wiki-query, /wiki-lint, /wiki-embed, /wiki-bulk,
/wiki-consolidate, /wiki-status, /wiki-init, /wiki-update.
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

### `/wiki-compile <source>` — Ingest Source

LLM reads source document, extracts entities, builds typed knowledge graph.

```bash
python3 scripts/wiki.py compile source.md
python3 scripts/wiki.py compile source.md --force  # re-compile + detect contradictions
```

**What happens:**
- Source sanitized (API keys, tokens, passwords, emails stripped)
- LLM generates 10–20 structured Wiki pages (YAML frontmatter + Overview/Key Details/Relationships/Source Context)
- **Cross-document entity protection**: same-named entities from different sources auto-prefixed (e.g., `coursepl-专家评审组`), concept aggregation pages auto-created
- Entity types dynamically loaded from `schema.md` (single source of truth)
- index.md + log.md updated
- Knowledge graph built: entities.json + edges.json (12 relationship types with Chinese/English keyword extraction)
- audit.json records the operation

### `/wiki-query <question>` — Search & Answer

Hybrid search (BM25 + Graph + RRF fusion), LLM synthesizes answer with citations.

```bash
python3 scripts/wiki.py query "What is X?"

# Fast mode — skip LLM synthesis (0.5s)
python3 scripts/wiki.py query "专家评审组" --no-synthesis

# Output formats
python3 scripts/wiki.py query "compare" --format table
python3 scripts/wiki.py query "history" --format timeline
python3 scripts/wiki.py query "export" --format json

# File answer back as new wiki page
python3 scripts/wiki.py query "Explain X" --file-back
```

| Mode | Flag | Time | Output |
|------|------|------|--------|
| Fast | `--no-synthesis` | 0.5s | Ranked list + snippets |
| LLM | default | 2.7s | Synthesized answer + citations |

Chinese search via jieba segmentation. English via BM25 + Porter stemming.
Search index cached to disk (`.wiki/graph/.bm25_index.json`), auto-invalidated on page changes.

### `/wiki-lint` — Health Check

```bash
python3 scripts/wiki.py lint              # Check only
python3 scripts/wiki.py lint --auto-heal  # Check + fix
```

Checks: contradictions, stale claims, orphan pages, broken links, missing concepts.

### `/wiki-status` — Wiki Overview

```bash
python3 scripts/wiki.py status
```

### `/wiki-init` — Initialize

```bash
python3 scripts/wiki.py init
```

Creates `.wiki/` directory structure.

### `/wiki-update` — Update Skill

```bash
python3 scripts/wiki.py update
```

Pulls latest code from GitHub, backs up old files to `backup/` (compressed with date stamp).

**What happens:**
- Current files compressed to `backup/llm-wiki-YYYYMMDD-HHMMSS.tar.gz`
- `git pull` from origin
- Reports files changed

### Other Commands

```bash
python3 scripts/wiki.py embed --force          # Regenerate vector embeddings
python3 scripts/wiki.py bulk stats             # Wiki analytics
python3 scripts/wiki.py bulk clean --dry-run   # Preview orphan cleanup
python3 scripts/consolidate.py                 # Memory tier promotion + decay
```

## Configuration

Single config file: `wiki_config.yaml` (copy from `.example`). Config is gitignored.

```yaml
ocr_mode: mineru               # Default OCR: mineru | paddle | deepseek

mineru:
  backend: pipeline            # pipeline (CPU) | hybrid-auto-engine (GPU)
  lang: ch
  formula: true
  table: true

paddleocr:
  lang: ch
  use_doc_orientation_classify: true
  use_doc_unwarping: true

ocr:                           # DeepSeek-OCR (legacy)
  api_url: "http://127.0.0.1:12345/v1/chat/completions"
  api_key: "your-key"
  model: "DeepSeek-OCR-4bit"

llm:
  provider: deepseek
  api_key: "sk-xxx"
  model: "deepseek-v4-flash"

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

Three pluggable backends, default via `ocr_mode` config.

```bash
# Default (from config)
python3 scripts/ocr.py document.pdf

# Explicit backend
python3 scripts/ocr.py document.pdf --backend paddle
python3 scripts/ocr.py document.pdf --backend deepseek

# PDF → Wiki full pipeline
python3 scripts/ocr.py paper.pdf -o .wiki/source/paper/
python3 scripts/wiki.py compile .wiki/source/paper/paper/auto/paper.md
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
