---
name: llm-wiki
description: >
  Build and maintain a personal knowledge base using the llm-wiki 2.0 pattern.
  Use this skill whenever the user mentions building a wiki, knowledge base,
  personal kb, memory system, knowledge management, organizing notes, ingesting
  research, creating a structured knowledge repository, or wants to accumulate
  knowledge across sessions. Also trigger for "remember this", "file away",
  "add to wiki", "organize my knowledge", "build a second brain", "create a
  knowledge base", "set up a wiki", or any task involving accumulating and
  structuring information that compounds over time.
  
  COMMAND TRIGGERS: Also trigger for slash commands: /wiki-add, /wiki-update,
  /wiki-query, /wiki-lint, /wiki-consolidate, /wiki-status, /wiki-init.
---

# LLM Wiki v2 — Knowledge Base Builder

## Philosophy

Stop re-deriving. Start compiling. RAG retrieves and forgets. A wiki accumulates and
compounds. This skill turns Claude into a disciplined knowledge librarian that builds
a living, self-correcting knowledge base from your conversations, research sessions,
and ingested sources.

The core insight from Karpathy's original LLM Wiki: the bottleneck is bookkeeping,
and LLMs eliminate it. What this v2 adds is the machinery that keeps the wiki healthy
as it scales — lifecycle management, graph structure, automation, quality controls,
and collaboration patterns proven in production.

## Command Reference

Slash commands for wiki operations. When user invokes a command, execute the full pipeline.

### `/wiki-add <source>` — Add Source & Build Wiki

Add a source (URL, file path, or content) to the wiki. Automatically:
1. Detect input type (URL, file, raw content)
2. Convert to Markdown using appropriate tool
3. Store in `.wiki/source/`
4. Extract entities and build knowledge graph
5. Create wiki pages

**Usage:**
```
/wiki-add https://example.com/article
/wiki-add document.pdf
/wiki-add notes.md
/wiki-add "raw text content to remember"
```

**Automatic Tool Selection:**

| Input | Tool | Action |
|-------|------|--------|
| `https://...` | lightpanda + ReaderLM | Fetch → Markdown → Build |
| `*.pdf`, `*.png` | PaddleOCR-VL | OCR → Markdown → Build |
| `*.docx`, `*.xlsx` | markitdown | Convert → Markdown → Build |
| `*.py`, `*.js`, etc. | Direct read | Copy → Build |
| `*.md`, `*.txt` | Direct read | Copy → Build |
| Raw text | None | Store → Build |

**Execution:**
```bash
# URL
python scripts/url2markdown.py "<url>" --output .wiki/source/articles/slug.md
python scripts/ingest.py .wiki/source/articles/slug.md --type article --embed

# File (auto-detect type)
python scripts/ingest.py <file> --ocr-if-needed --embed

# Raw content
echo "<content>" | python scripts/ingest.py - --type article --embed
```

### `/wiki-update <target>` — Update Wiki Content

Update an existing entity, page, or source. Options:

| Target | Action |
|--------|--------|
| `entity/<name>` | Update entity page and graph |
| `source/<slug>` | Re-ingest source with new content |
| `<content>` | Append/update specific knowledge |

**Usage:**
```
/wiki-update entity/react-library
/wiki-update source/article-slug
/wiki-update "React 19 now supports server components"
```

**Execution:**
1. Find target in `.wiki/pages/entities/` or `.wiki/source/`
2. Load existing content
3. Merge new information (don't replace)
4. Update graph and confidence scores
5. Log operation

### `/wiki-query <query>` — Search Wiki

Search the wiki for information. Supports:
- Keyword search
- Semantic similarity (if embeddings exist)
- Graph traversal

**Usage:**
```
/wiki-query How does React handle state?
/wiki-query entity:react-library
/wiki-query type:decision
```

**Execution:**
```bash
python scripts/search.py "<query>" --hybrid
```

### `/wiki-lint` — Quality Check

Run quality checks on the wiki:
- Orphan pages
- Broken links
- Stale content
- Contradictions

**Usage:**
```
/wiki-lint
/wiki-lint --fix
```

**Execution:**
```bash
python scripts/lint.py [--fix]
```

### `/wiki-consolidate` — Memory Consolidation

Promote observations through memory tiers:
- Working → Episodic
- Episodic → Semantic
- Apply retention decay

**Usage:**
```
/wiki-consolidate
```

**Execution:**
```bash
python scripts/consolidate.py
```

### `/wiki-status` — Wiki Overview

Show wiki statistics and health:
- Entity count
- Source count
- Recent activity
- Quality score

**Usage:**
```
/wiki-status
```

### `/wiki-init` — Initialize New Wiki

Create `.wiki/` directory structure with defaults.

**Usage:**
```
/wiki-init
/wiki-init --template templates/schema.md
```

**Execution:**
```bash
mkdir -p .wiki/{source/{articles,documents,code,misc},pages/{entities,decisions,sessions,patterns},graph,memory,audit}
# Create default schema.md, config.json, index.md
```

## Directory Structure

All wiki files live under `.wiki/` in the project root:

```
.wiki/
├── schema.md              # The most important file. Defines entities, relationships,
│                          # ingest rules, quality standards, and consolidation schedule.
├── source/                # Raw sources converted to Markdown (input staging area)
│   ├── articles/          # Web articles, blog posts
│   ├── documents/         # DOCX, PPTX, XLSX, PDF files
│   ├── code/               # Code files, configurations
│   └── misc/               # Other text files
├── pages/                 # Wiki pages in markdown (human-readable content)
│   ├── entities/          # Entity pages (people, projects, libraries, concepts, files)
│   ├── decisions/         # Architecture decisions (ADR-style)
│   ├── sessions/          # Session digests (crystallized from working sessions)
│   ├── patterns/          # Procedural knowledge and workflows
│   └── index.md           # Human-readable catalog (supplementary to search)
├── graph/
│   ├── entities.json      # Structured entity registry with types, attributes, confidence
│   └── edges.json         # Typed relationships between entities
├── memory/
│   ├── working.json       # Recent observations, not yet processed
│   ├── episodic.json      # Session summaries, compressed from working memory
│   └── semantic.json      # Cross-session facts, consolidated from episodes
├── audit/
│   └── trail.jsonl        # Append-only log of all wiki operations
└── config.json            # Wiki configuration (retention curves, quality thresholds)
```

## Quick Start

### Initialize Wiki

```
/wiki-init
```

Or manually:
```bash
mkdir -p .wiki/{source/{articles,documents,code,misc},pages/{entities,decisions,sessions,patterns},graph,memory,audit}
```

### Add First Source

```
/wiki-add https://example.com/article
/wiki-add README.md
/wiki-add "Important: Project uses React 19 with server components"
```

### Query Wiki

```
/wiki-query What frameworks does this project use?
```

### Check Health

```
/wiki-status
/wiki-lint
```

## Source Conversion

When the user provides a source (file path, URL, or raw content), automatically select
the appropriate tool to convert it to Markdown and store in `.wiki/source/`.

### Input Type Detection

| Input Type | Detection Rule | Conversion Tool | Output Directory |
|------------|---------------|-----------------|------------------|
| URL | Starts with `http://` or `https://` | lightpanda + ReaderLM-v2 | `source/articles/` |
| PDF | `.pdf` extension | PaddleOCR-VL (remote) | `source/documents/` |
| Image | `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp` | PaddleOCR-VL (remote) | `source/documents/` |
| Office docs | `.docx`, `.pptx`, `.xlsx`, `.epub` | markitdown | `source/documents/` |
| HTML | `.html`, `.htm` | ReaderLM-v2 | `source/articles/` |
| Code | `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, etc. | Direct read | `source/code/` |
| Config | `.json`, `.yaml`, `.yml`, `.toml`, `.ini` | Direct read | `source/code/` |
| Text | `.md`, `.txt`, `.rst`, `.org` | Direct read | `source/misc/` |

### Conversion Pipeline

```
User Input → Detect Type → Convert to Markdown → Store in .wiki/source/ → Build Wiki
```

#### Step 1: URL → Markdown

Use `scripts/url2markdown.py` for web pages:

```bash
python scripts/url2markdown.py "https://example.com/article" \
  --output .wiki/source/articles/article-slug.md
```

**Requirements:**
- lightpanda installed (`which lightpanda`)
- Local LLM API configured in `scripts/wiki_config.yaml` (copy from `wiki_config.yaml.example`)

#### Step 2: Office Documents → Markdown

Use markitdown for DOCX, PPTX, XLSX, EPUB, HTML:

```bash
python scripts/ingest.py document.docx --convert-only \
  --output .wiki/source/documents/document.md
```

#### Step 3: Images/PDF → Markdown (OCR)

Use PaddleOCR-VL remote API for OCR:

```bash
python scripts/ingest.py image.png --ocr \
  --output .wiki/source/documents/image.md

python scripts/ingest.py document.pdf --ocr \
  --output .wiki/source/documents/document.md
```

#### Step 4: Code/Text → Markdown

Direct copy with metadata header:

```bash
python scripts/ingest.py code.py --copy \
  --output .wiki/source/code/code.py.md
```

### Full Ingest Workflow

After converting source to Markdown in `.wiki/source/`:

```bash
python scripts/ingest.py .wiki/source/articles/article.md \
  --type article --embed
```

This triggers:
1. Entity extraction (people, projects, libraries, concepts)
2. Knowledge graph construction
3. Wiki page creation in `pages/entities/`
4. Embedding generation for semantic search

## Core Workflows

### 1. Ingest — From Source to Structure

When the user provides a source (article, document, conversation, code, URL), or
when a session produces insights worth preserving:

**Automatic Pipeline:**

1. **Detect input type**: URL, file path, or raw content
2. **Convert to Markdown**: Use appropriate tool per the Source Conversion section
3. **Store source**: Save converted Markdown to `.wiki/source/` with proper categorization
4. **Parse the source**: Extract key claims, facts, decisions, and entities
5. **Filter sensitive data**: Strip API keys, tokens, passwords, PII before anything
   hits the wiki. See `references/privacy-governance.md`
6. **Extract entities**: Identify people, projects, libraries, concepts, files, decisions.
   Each gets a type, attributes, and relationships. See `references/knowledge-graph.md`
7. **Score confidence**: How many sources support each claim? How recently confirmed?
   Any contradictions? See `references/lifecycle.md`
8. **Check for existing knowledge**: Does this contradict, confirm, or supersede
   existing claims? Resolve before writing.
9. **Write to wiki**:
   - Entity pages in `pages/entities/` using `templates/entity-page.md`
   - Decision records in `pages/decisions/` (ADR format if applicable)
   - Update `graph/entities.json` and `graph/edges.json`
   - Add to `memory/working.json` as a new observation
10. **Log operation** to `audit/trail.jsonl`

**Tool Selection Summary:**

| Input | Tool | Command |
|-------|------|---------|
| URL | lightpanda + ReaderLM | `python scripts/url2markdown.py <url>` |
| PDF/Image | PaddleOCR-VL | `python scripts/ingest.py <file> --ocr` |
| Office docs | markitdown | `python scripts/ingest.py <file>` |
| Code/Text | Direct read | `python scripts/ingest.py <file>` |

### 2. Query — From Question to Answer

When the user asks a question that the wiki might answer:

1. **Parse intent**: What kind of answer? Fact check, explanation, connection discovery,
   impact analysis?
2. **Search strategy** (pick based on query type):
   - **Keyword match** → direct page lookup
   - **Semantic search** → vector similarity over page embeddings
   - **Graph traversal** → start at an entity, walk relationships
   - **Hybrid** → fuse results from all three (see `references/hybrid-search.md`)
3. **Synthesize answer**: Combine retrieved facts with source citations and confidence scores
4. **Crystallization check**: Is this answer worth filing back? If the query produced
   new insights, trigger the consolidate workflow. See `references/crystallization.md`
5. **Choose output format**: Raw markdown, comparison table, timeline, dependency graph,
   slide deck, or structured data export. See `references/output-formats.md`

### 3. Lint — Quality Assurance

Run lint proactively (not just when asked). Trigger on:
- After any batch of ingests (≥3 sources)
- Periodically (suggest running after significant wiki growth)
- When the user asks "is my wiki healthy?"

The lint pass checks:
1. **Orphan pages**: Pages with no incoming links → auto-link or flag
2. **Stale claims**: Facts past their retention threshold → mark as stale, propose update
3. **Broken references**: Wikilinks pointing to nonexistent pages → repair or flag
4. **Contradictions**: Two claims saying different things → propose resolution based on
   source authority and recency
5. **Quality scores**: Re-score existing content, flag below-threshold items

See `references/quality.md` for self-healing patterns.

### 4. Consolidate — Memory Lifecycle Management

Run consolidation periodically (after significant activity or on schedule):

1. **Working → Episodic**: Group recent observations into session summaries. Compress.
   Promote high-confidence, multi-source facts upward.
2. **Episodic → Semantic**: Cross-reference episodes. Extract facts confirmed across
   multiple sessions. Promote to long-lived semantic memory.
3. **Apply retention decay**: For each fact, apply Ebbinghaus decay curve. Facts that
   haven't been accessed or reinforced fade. Each access resets the curve.
4. **Supersession**: When new information replaces old, mark old as superseded, link
   to replacement, preserve history.
5. **Forgetting**: Deprioritize (don't delete) facts below threshold. Move to bottom
   of search results.

See `references/lifecycle.md` for the full lifecycle model.

## Implementation Spectrum

Pick your starting level based on current needs. The skill supports all five.

### Level 1 — Minimal Viable Wiki
- Raw sources → wiki pages
- `index.md` catalog
- Schema with ingest/query/lint workflows
- **Start here.** Gets you running in minutes.

### Level 2 — Add Lifecycle
- Confidence scoring on every claim
- Supersession when facts change
- Basic retention decay
- Working → episodic → semantic tiers
- **Add this when the wiki starts accumulating noise.**

### Level 3 — Add Structure
- Entity extraction from all sources
- Typed relationships (uses, depends on, caused, fixed, contradicts, supersedes)
- Knowledge graph (entities.json + edges.json)
- Graph traversal for queries
- **Add this when flat pages aren't enough for discovery.**

### Level 4 — Add Automation
- Hooks: auto-ingest on source drop, auto-lint on schedule, context injection
  on session start
- Consolidation pipeline runs automatically
- Quality scoring on all new content
- Self-healing during lint (auto-fix what can be auto-fixed)
- **Add this when maintenance becomes a burden.**

### Level 5 — Add Scale & Collaboration
- Hybrid search (BM25 + vector + graph)
- Mesh sync between agents
- Shared vs. private knowledge scoping
- Work coordination patterns
- Bulk governance operations
- **Add this for teams, multi-agent setups, or wikis with 500+ pages.**

See `references/implementation-spectrum.md` for detailed level-by-level setup guides.

## Reference Files

Load these when you need deep knowledge on a specific pattern:

| Reference | When to load |
|-----------|-------------|
| `references/lifecycle.md` | Setting up confidence scores, forgetting curves, consolidation tiers |
| `references/knowledge-graph.md` | Implementing entity extraction, typed relationships, graph traversal |
| `references/hybrid-search.md` | Building search that combines BM25, vectors, and graph queries |
| `references/automation.md` | Setting up hooks, schedules, context injection |
| `references/quality.md` | Implementing scoring, self-healing, contradiction resolution |
| `references/collaboration.md` | Multi-agent sync, shared/private scoping, coordination |
| `references/privacy-governance.md` | Filtering sensitive data, audit trails, bulk operations |
| `references/crystallization.md` | Distilling sessions into structured digests |
| `references/output-formats.md` | Comparison tables, timelines, dependency graphs, slide decks |
| `references/implementation-spectrum.md` | Detailed setup guides for each maturity level |

## Templates

Available templates for wiki content:

| Template | When to use |
|----------|------------|
| `templates/schema.md` | Initializing a new wiki — the most important file |
| `templates/entity-page.md` | Creating a new entity page (person, project, library, concept) |
| `templates/session-digest.md` | Crystallizing a working session into a structured summary |
| `templates/index.md` | Creating the human-readable wiki catalog |

## Scripts

Automation scripts in `scripts/`:

| Script | Purpose |
|--------|---------|
| `scripts/wiki.py` | Unified CLI for all wiki operations |
| `scripts/ingest.py` | Source ingestion + entity extraction |
| `scripts/url2markdown.py` | URL → HTML (lightpanda) → Markdown (ReaderLM) |
| `scripts/search.py` | Hybrid search over wiki pages, graph, embeddings |
| `scripts/lint.py` | Quality checks: orphans, staleness, contradictions |
| `scripts/consolidate.py` | Memory tier promotion + decay |
| `scripts/graph.py` | Build and query knowledge graph |

### `wiki.py` — Unified CLI

Primary entry point for all wiki operations:

```bash
python scripts/wiki.py add <source>     # Add source & build wiki
python scripts/wiki.py query <query>    # Search wiki
python scripts/wiki.py lint             # Quality check
python scripts/wiki.py status           # Wiki statistics
python scripts/wiki.py init             # Initialize structure
python scripts/wiki.py consolidate      # Memory consolidation
python scripts/wiki.py update <target>  # Update content
```

**`add` options:**
- `--no-embed`: Skip embedding generation
- `--type`: Source type (article, code, doc, conversation)

**`lint` options:**
- `--fix`: Auto-fix issues

**`query` options:**
- Default uses hybrid search (BM25 + vector + graph)

### Other Script Options

**`ingest.py` options:**
- `--type`: Source type (article, code, conversation, doc)
- `--stdin`: Read from stdin
- `--batch <dir>`: Process all files in a directory
- `--embed`: Generate embeddings for semantic search
- `--ocr`: Enable OCR for images/PDFs via PaddleOCR-VL
- `--convert-only`: Only convert to Markdown, skip entity extraction
- `--copy`: Copy text file with metadata header (for code/text files)
- `--output, -o`: Output file path (default: auto-detect from .wiki/source/)

**`url2markdown.py` options:**
- `--output FILE`: Save Markdown to file
- `--timeout N`: Lightpanda timeout in milliseconds (default: 30000)
- `--api-base URL`: Override LLM API base URL
- `--api-key KEY`: Override API key
- `--model NAME`: Override model name

## Schema Co-Evolution

The schema document (`schema.md`) is the most important file in the system. It encodes
what the LLM needs to know to be a disciplined knowledge worker. It and the LLM co-evolve
this document over time.

After every significant wiki operation, ask: "Does the schema need to change?" If a new
entity type emerged, a new relationship proved useful, or a quality rule needs tightening,
update the schema. The schema is transferable — share it with someone in a similar domain
and they get a running start.

## Principles

1. **Compounding over time**: Every source and session adds permanent value
2. **Confidence over certainty**: Every claim carries a score, not just a statement
3. **Structure enables discovery**: The graph catches connections keyword search misses
4. **Automation prevents rot**: Manual wikis die. Hooks keep them alive
5. **Human in the loop for curation, LLM for bookkeeping**: The LLM does the filing.
   The human sets direction and resolves conflicts.
6. **Privacy by default**: Filter sensitive data before it enters the wiki
7. **Knowledge has a lifecycle**: What matters today may not matter in six months
8. **The schema is transferable**: Your wiki's structure is reusable knowledge in itself
