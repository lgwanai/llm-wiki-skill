---
name: llm-wiki
description: >
  Build and maintain a personal knowledge base using the LLM Wiki v2 pattern.
  Trigger when user mentions: wiki, knowledge base, kb, memory system, knowledge
  management, organizing notes, ingesting research, structured knowledge, "remember
  this", "file away", "add to wiki", "second brain", "build knowledge base", "set
  up wiki", accumulating and structuring information that compounds over time.
  COMMANDS: /wiki-compile, /wiki-query, /wiki-lint, /wiki-embed, /wiki-bulk,
  /wiki-consolidate, /wiki-status, /wiki-init.
---

# LLM Wiki v2

Stop re-deriving. Start compiling.

RAG retrieves and forgets. A wiki accumulates and compounds. This skill turns
Claude into a disciplined knowledge librarian — reading sources, extracting entities,
building a typed knowledge graph, and maintaining everything as knowledge evolves.

## Core Idea

```
RAG:    Source → [检索] → LLM 即时合成 → 回答 → 丢弃
Wiki:   Source → [编译] → Wiki 持久化 → 查询时直接使用已有知识
```

The bottleneck in knowledge management is not reading or thinking — it's bookkeeping.
LLMs eliminate that bottleneck.

## Architecture

```
Raw Sources (.wiki/source/)     — immutable, LLM reads never modifies
    ↓
Wiki (.wiki/pages/)             — LLM maintains: entity pages, concept pages, index, log
    ↓
Schema (schema.md + wiki_config.yaml) — conventions, types, quality rules, co-evolved
```

## Commands

### `/wiki-compile <source>` — Ingest Source

Compile a source document into wiki pages. LLM reads, extracts entities, builds graph.

```bash
python3 scripts/wiki.py compile <source.md>

# Force re-compile (update existing pages + detect contradictions)
python3 scripts/wiki.py compile <source.md> --force
```

**What happens:**
- Source is sanitized (API keys, tokens, passwords, emails stripped)
- LLM generates 10-15 structured wiki pages with YAML frontmatter
- index.md updated (grouped by type: Concepts, Techniques, Models, Frameworks, Benchmarks)
- log.md appended with timestamped entry
- Knowledge graph built: entities → entities.json, edges → edges.json (12 relationship types)
- audit.json records the operation

### `/wiki-query <question>` — Search & Answer

Search wiki via BM25 + vector + graph, synthesize answer with citations.

```bash
python3 scripts/wiki.py query "What is X?"

# With output format
python3 scripts/wiki.py query "compare models" --format table
python3 scripts/wiki.py query "history" --format timeline
python3 scripts/wiki.py query "present findings" --format slides
python3 scripts/wiki.py query "export" --format json

# File answer back as a new wiki page
python3 scripts/wiki.py query "Explain X" --file-back
```

### `/wiki-lint` — Health Check

Detect and auto-fix wiki issues.

```bash
python3 scripts/wiki.py lint              # Check only
python3 scripts/wiki.py lint --auto-heal  # Check + fix
```

**Checks:** contradictions, stale claims, orphan pages, broken links, missing concepts.

### `/wiki-embed` — Vector Embeddings

Generate embeddings for semantic search.

```bash
python3 scripts/wiki.py embed           # Generate all
python3 scripts/wiki.py embed --force   # Regenerate all
```

Model: qwen3-embedding:8b (4096 dims) via Ollama @ localhost:11434.

### `/wiki-bulk <action>` — Bulk Operations

Governance for growing wikis. All operations audited and reversible.

```bash
python3 scripts/wiki.py bulk stats                  # Detailed analytics
python3 scripts/wiki.py bulk clean --dry-run        # Preview orphan cleanup
python3 scripts/wiki.py bulk merge --dry-run        # Preview duplicate merge
python3 scripts/wiki.py bulk export --type concept  # Export subset
python3 scripts/wiki.py bulk delete --stale --dry-run  # Preview stale deletion
```

### `/wiki-consolidate` — Memory Consolidation

Promote observations through memory tiers: Working → Episodic → Semantic → Procedural.

```bash
python3 scripts/consolidate.py
```

### `/wiki-status` — Wiki Overview

```bash
python3 scripts/wiki.py status
```

Shows: page counts, entity/edge counts, embedding coverage, file existence.

### `/wiki-init` — Initialize

```bash
python3 scripts/wiki.py init
```

Creates `.wiki/` directory structure with defaults.

## Directory Structure

```
.wiki/
├── pages/
│   ├── concepts/          # Concept pages (architecture, mechanisms)
│   ├── entities/          # Entity pages (models, benchmarks, frameworks)
│   ├── sessions/          # Crystallized session digests
│   └── index.md           # Human-readable catalog by type
├── graph/
│   ├── entities.json      # Entity registry: id, type, confidence, sources, reinforcement
│   ├── edges.json         # Typed relationships: uses, depends_on, contradicts, ...
│   └── embeddings.json    # Vector embeddings for semantic search
├── source/                # Raw source documents (immutable)
├── memory/
│   ├── working.json       # Recent observations
│   ├── episodic.json      # Session summaries
│   └── semantic.json      # Cross-session facts
├── audit.json             # Full operation log (timestamp + what + why)
├── log.md                 # Chronological log (parseable with grep)
└── schema.md              # Entity types, relationship types, quality rules
```

## Scripts

| Script | Purpose |
|--------|---------|
| `wiki.py` | Unified CLI — all operations |
| `compile_v2.py` | Source → wiki pages + knowledge graph |
| `query.py` | Search + synthesize + file-back (6 output formats) |
| `lint.py` | Health check + auto-heal |
| `search.py` | Hybrid search: BM25 + vector + graph |
| `graph.py` | Knowledge graph: entities, edges, traversal |
| `consolidate.py` | Memory tier promotion + decay |
| `crystallize.py` | Session → digest pipeline |
| `bulk.py` | Bulk delete/export/merge/clean/stats |
| `generate_embeddings.py` | Vector embedding generation |
| `url2markdown.py` | URL → Markdown conversion |
| `ocr.py` | PDF/Image OCR |
| `_ollama.py` | Ollama embeddings (qwen3-embedding:8b) |
| `_qdrant.py` | Optional Qdrant vector database |
| `_agensgraph.py` | Optional AgensGraph graph database |

Dependencies: `query.py` → `search.py` → `graph.py` | `consolidate.py` → `crystallize.py`

## Knowledge Lifecycle

```
Source → Compile → Pages + Graph → Query → File-back
                → Log + Audit → Lint → Stale → Decay → Archive
                               → Consolidate → Working → Episodic → Semantic
                               → Crystallize → Session → Digest → Facts
```

### Stage Reference

| Stage | Command | What |
|-------|---------|------|
| Ingest | `wiki compile` | Read source, strip sensitive, build pages + graph |
| Graph | `graph show` | View entities, edges, typed relationships |
| Query | `wiki query --file-back` | Search + synthesize + save insights |
| Lint | `wiki lint --auto-heal` | Detect + fix contradictions, stale, orphans, broken links |
| Contradictions | `wiki compile --force` | Re-compile auto-detects conflicts, proposes resolution |
| Decay | automatic | Ebbinghaus curves: arch 260d, bug 20d, meeting 10d |
| Consolidate | `consolidate.py` | Promote: Working → Episodic → Semantic → Procedural |
| Crystallize | `crystallize.py` | Session → digest → facts → working memory |
| Bulk | `wiki bulk clean/merge/delete` | Governance for growing wikis |
| Embed | `wiki embed` | Generate 4096d vectors for semantic search |

### Relationship Types (12)

`uses` | `depends_on` | `extends` | `improves_upon` | `contradicts` | `supersedes` | `caused_by` | `fixed_by` | `replaces` | `relates_to` | `part_of` | `implemented_by`

### Confidence & Forgetting

| Entity Type | Half-life | Behavior |
|-------------|-----------|----------|
| architecture | 260 days | Slow decay |
| project | 130 days | Moderate decay |
| pattern | 87 days | Moderate decay |
| bug | 20 days | Fast decay |
| meeting | 10 days | Fast decay |
| preference | 527 days | Very slow decay |

Confidence starts at 0.85, +0.05 per source reinforcement (max 1.0).
Decay: retention < 0.5 → stale | < 0.15 → archived.

## Configuration

Single config file: `scripts/wiki_config.yaml` (copy from `.example`).

```yaml
llm:          # Compile + query
  api_key: "sk-xxx"
  model: "deepseek-v4-flash"
embeddings:   # Semantic search
  base_url: "http://localhost:11434"
  model: "qwen3-embedding:8b"
hooks:        # Automation
  on_new_source: {enabled: true}
retention:    # Decay curves
  architecture: {half_life_days: 180}
quality:      # Quality gates
  auto_heal: true
  min_score: 0.4
```

Optional backends (uncomment to enable): Qdrant @ localhost:6333, AgensGraph @ localhost:5433.

## Output Formats

| Format | Flag | Output |
|--------|------|--------|
| Markdown | `--format markdown` | Structured answer with wikilinks |
| Table | `--format table` | Comparison table |
| Timeline | `--format timeline` | Chronological events |
| Slides | `--format slides` | Marp presentation |
| JSON | `--format json` | Structured data export |
| Graph | `--format graph` | Dependency visualization |

## Design Heritage

- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — original three-layer pattern
- [Rohit's LLM Wiki v2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2) — production hardening

Full design compliance: 100% Karpathy v1 + 100% Rohit v2 core features.
