<p align="center">
  <a href="README.md">🇬🇧 English</a> &nbsp;|&nbsp;
  <a href="README_CN.md">🇨🇳 中文</a>
</p>

# llm-wiki

**A Living Knowledge Base That Compounds.** Not RAG — don't re-derive, compile once. The Agent reads your sources, builds a typed knowledge graph, and maintains it forever. Cross-references, contradiction detection, confidence decay — all automatic.

<p align="center">
  <img src="docs/benchmark_chart.png" alt="RAGAS Benchmark: llm-wiki vs Industry" width="100%">
</p>

> **Faithfulness 1.00** · **Answer Relevance 1.00** · **Answer Correctness 0.91** · **Context Recall 0.94**. Wiki-native pipeline (compile → search → synthesize). The default path needs no embedding model; Zvec and cross-encoder reranking are optional high-recall layers. [Full benchmark →](docs/BENCHMARK.md)

---

## Why llm-wiki

| | RAG | llm-wiki |
|---|-----|----------|
| **Approach** | Retrieve → Synthesize → Discard | Compile → Structure → Persist |
| **Knowledge** | Ephemeral, re-derived each query | Cumulative, compounds over time |
| **Cross-references** | None | Automatic entity linking + typed edges |
| **Contradictions** | Silent | Detected, flagged, resolved |
| **Staleness** | Manual cleanup | Automatic confidence decay + supersession |
| **Structure** | Flat chunks | Typed pages (concepts, techniques, models, events...) |
| **Search Speed** | 200–500ms (embedding API + vector DB) | **~41ms** (BM25 + metadata + graph, in-process) |

> *"The bottleneck in knowledge base maintenance isn't reading, isn't thinking — it's bookkeeping. LLMs don't fatigue, don't forget, and can touch 15 files at once."* — Andrej Karpathy

## Quick Start

```bash
pip install -e .
wiki config --init        # create wiki_config.yaml
wiki init                 # initialize .wiki/
wiki compile paper.md     # Agent reads source → structured pages
wiki query "What is X?"   # search → synthesize → answer with citations
```

Agent compile/query mode is the default and does not require an API key. Configure a
provider only when you explicitly want the optional `--mode llm` path.

**One source → 15+ structured pages with typed relationships:**

```bash
$ wiki compile deepseek-v4.md
Compiling deepseek-v4.md (262,658 chars)...
  Created: deepseek-v4.md (model)
  Created: multi-head-latent-attention.md (technique)
  Created: deepseek-moe.md (technique)
  Created: mmlu.md (benchmark)
  ... 15 pages, 84 typed edges (uses, improves_upon, relates_to) ...

$ wiki query "How does DeepSeek-V4 reduce inference memory?"
**Answer**: Uses Multi-head Latent Attention (MLA) to compress KV-cache 8x and
DeepSeekMoE with 256 experts (8 active per token), achieving 37B active params.
**Sources**: [Multi-head Latent Attention](/concepts/multi-head-latent-attention.md),
[DeepSeekMoE](/concepts/deepseek-moe.md)
```

## Install as Claude Code Skill

llm-wiki works standalone **and** as a Claude Code skill for hands-free knowledge management:

```bash
# 1. Clone and install
git clone https://github.com/anthropics/llm-wiki-skill.git ~/.claude/skills/llm-wiki
cd ~/.claude/skills/llm-wiki
pip install -e .

# 2. Register the skill
mkdir -p ~/.claude/skills
cp ~/.claude/skills/llm-wiki/SKILL.md ~/.claude/skills/llm-wiki-skill.md

# 3. Configure
wiki config --init
vim wiki_config.yaml  # set provider + API key
wiki init
```

> After activation, Claude auto-detects wiki intents — "remember this", "add to wiki", "what do we know about X" — and invokes the skill automatically.

## Search Performance

llm-wiki keeps a fast lexical/graph baseline with no embedding calls or remote vector DB round-trips. Optional local Zvec retrieval and reranking trade extra latency for semantic recall:

| Pipeline | Search Latency | Components |
|----------|---------------|------------|
| **llm-wiki baseline** | **~41ms avg*** | BM25F + metadata + graph + DuckDB (in-process) |
| **llm-wiki semantic** | machine/model dependent | Baseline + embedded Zvec HNSW + optional reranker |
| RAG (chunk+embed) | 200–500ms | Embedding API + vector DB |
| GraphRAG | 500ms–2s | Community detection + LLM summarization |

> \*The historical 41ms result is retained as a baseline, not a guarantee. Run the included benchmark on your own wiki; it now reports P50/P95 latency alongside recall and leakage metrics.

### Retrieval completeness and accuracy

Query uses field-weighted BM25F over Concept ID, title, tags, description, key facts,
headings, and body. Metadata, BM25F, graph, ledger, and optional vector results are
combined with intent-aware weighted reciprocal-rank fusion. Each stream over-fetches
candidates before scope/status filtering, so filtering does not silently starve the
final result count. Evidence-driven multi-hop retrieval decomposes compound questions into
answer subgoals, follows only the most relevant concept links, tracks path confidence, and
stops when the required evidence is covered (three hops by default). Coverage-aware top-k
selection avoids returning several near-duplicate pages while omitting one side of a comparison.
Long concepts remain intact in OKF storage; heading-bounded virtual sections receive their own
BM25 signal so an exact fact near the end of a page can rescue its canonical parent page.

Agents must call `wiki query` or `scripts/query.py`; they must not create temporary
Python/Shell/SQL search code or scan `.wiki/` manually. The official query command applies
ranking, graph, ledger, scope, lifecycle, multi-hop, and evidence-selection rules together.

DuckDB ledger matching executes over all declared columns and all rows instead of a
fixed Python sample. Independent graph, ledger, and vector streams run concurrently.
Search indexes are content-aware and invalidate when any nested OKF concept changes.
Metadata search consumes canonical `aliases`, `keywords`, `questions`, and tags. Education graph
queries use typed edges such as `tests`, `depends_on`, `has_example`, and `confuses_with`, with a
bounded two-hop traversal for question → knowledge point → prerequisite paths.

Cross-language expansion is local and model-free. It first learns phrase mappings from bilingual
titles, aliases, keywords, tags, and questions already present in the Wiki, then applies a small
operations/education fallback glossary. Project-specific mappings can be added without code:

```yaml
# .wiki/query_lexicon.yaml
terms:
  熔断窗口: circuit breaker window
  证据保留: [evidence retention, audit evidence retention]
```

Optional local semantic retrieval and reranking:

```yaml
query:
  max_results: 8
  parallel_search: true
  search_streams: metadata,bm25,graph,ledger,vector
  cross_language_expansion: true
  multi_hop_enabled: true
  multi_hop_max_hops: 3
  verify_answers: true

embeddings:
  enabled: true
  backend: zvec
  model_source: modelscope
  index_path: graph/zvec

reranker:
  enabled: false
  backend: flagembedding
  model: BAAI/bge-reranker-v2-m3
  candidate_count: 20
```

Install only the optional layer you use: `pip install -e '.[vector]'` or
`pip install -e '.[rerank]'`. If it is disabled or unavailable, query falls back to
the native retrieval path.

## Self-Looping Maintenance & Doctor

**Dream** auto-optimizes your wiki from query logs. **Doctor** lets you report issues and auto-fixes them.

```bash
# Dream — self-looping optimization (4 phases, directly modifies content)
wiki dream --foreground          # auto-merge duplicates, enrich metadata
                                 # git snapshots + quality gating + rollback

# Doctor — report issues and auto-repair
wiki doctor "专家评审组信息不完整，缺少成员名单"   # natural language feedback
wiki doctor --check coursepl-专家评审组            # diagnostic check
wiki doctor --recompile .wiki/source/doc.md        # recompile source
wiki doctor --re-ocr .wiki/source/slides.pptx      # re-OCR + recompile
wiki doctor --list                                 # outstanding issues
```

| Feature | Mechanism |
|---------|-----------|
| **Git snapshots** | Auto-commit before every modification in `.wiki/.git` — safe rollback |
| **Quality gating** | 3-dimension search assessment (rank/density/coverage) — auto-rollback if degraded |
| **Experience store** | SHA256-deduped lessons learned → loaded as context in future runs |
| **Doctor workflow** | classify (regex) → diagnose (wiki search) → repair (8 strategies) → verify → persist |

## Content-Aware Domain Experts

Compile does not force every source through a fixed chunking recipe. It reads the
document first, identifies its domain and intended retrieval tasks, then combines up
to three relevant expert lenses. Page count, fact count, and entity/concept ratio are
driven by the source rather than fixed quotas.

Built-in expert coverage includes:

- Legal/regulatory compliance, sales and marketing policy, finance/accounting
- Operations, product management, software architecture, and project management
- HR, procurement/supply chain, manufacturing/quality, risk/internal audit
- Academic research, curriculum design, textbook/exam learning, education, healthcare, and customer service
- Corporate strategy and data/metric governance

For example, regulations retain article numbering, operative language, applicability,
exceptions, effective dates, and cross-references. Commercial policies retain region,
audience, channel, time window, thresholds, exclusions, approvals, and settlement
conditions. Academic documents retain definitions, formulas, assumptions, derivations,
evidence, limitations, and citations. Textbooks compile into linked knowledge-point pages;
exam questions preserve stems, answers, solutions, scoring evidence, tested concepts, and
common mistakes, with bidirectional question—knowledge-point links. Every study knowledge
point records the original filename plus one or more pages/page ranges, and keeps relevant
figures from cited and adjacent pages. Knowledge is merged across page/chunk boundaries;
uncertain locations are marked for verification instead of suppressing the concept.
Mixed or unfamiliar sources can combine lenses
or infer a more suitable specialist dynamically.

Incremental compilation resolves canonical concept titles and aliases before writing. New evidence
is fused into the existing page; if semantic fusion is unavailable, a lossless fallback retains both
sources instead of overwriting either one. For textbooks and exam papers, post-processing verifies
that every recognized question links to its textbook knowledge points and that each knowledge-point
page contains the reverse question link, so both directions are materialized in the graph.

## Native Open Knowledge Format (OKF) Storage

llm-wiki stores knowledge natively as Google Knowledge Catalog's
[Open Knowledge Format v0.1 Draft](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle. `.wiki/pages/` is the bundle root; every non-reserved Markdown file is
an OKF concept, and its bundle-relative path is its Concept ID.

```bash
# Validate an OKF bundle
wiki okf validate path/to/bundle

# Merge another OKF bundle directly into the native bundle
wiki okf import path/to/bundle
wiki okf import path/to/bundle --force

# Copy the native bundle for distribution (no format conversion)
wiki okf export path/to/output-bundle
wiki okf export path/to/output-bundle --force

# One-time in-place migration from legacy llm-wiki metadata
wiki okf migrate
```

Compile writes OKF `type`, `title`, `description`, optional `resource`, `tags`, and
`timestamp` directly. Search and query derive identity from paths and read those fields
without a compatibility mapping. Relationships use standard Markdown links. Import
preserves hierarchy, bodies, reserved files, unknown types, broken links, and extension
fields. Export validates and copies the bundle as-is.

## Benchmark

We evaluate the **complete product pipeline** (compile → search → synthesize), not only components. The published baseline is the pure wiki-native path; optional Zvec and reranker configurations should be measured separately. Industry baselines come from published RAGAS/RGB/GraphRAG papers.

| System | Faithfulness | Answer Relevance | Context Recall | Answer Correctness |
|--------|-------------|-----------------|----------------|-------------------|
| Naive RAG (chunk+embed) | 0.72 | 0.78 | 0.68 | 0.65 |
| RAG + Reranker | 0.83 | 0.85 | 0.76 | 0.78 |
| RAGFlow (est.) | 0.86 | 0.84 | 0.79 | 0.80 |
| GraphRAG (Microsoft) | 0.88 | 0.87 | 0.84 | 0.83 |
| **llm-wiki ★** | **1.00** | **1.00** | **0.94** | **0.91** |

> **All scores are LLM-as-judge (RAGAS framework)** over 19 test cases across tech, business, and Chinese domains. Industry baselines from published papers — not identical test sets. llm-wiki: compile_v2 → BM25+metadata+graph → entity link → 3-signal rank → synthesize. **4 of 5 metrics surpass GraphRAG.**

→ [Full benchmark report with per-case breakdown](docs/BENCHMARK.md)

## OCR Backends

Seven pluggable OCR engines. PaddleOCR-VL-1.6 is the default on Apple Silicon:
PP-DocLayoutV3 provides layout and reading order while MLX-VLM accelerates the
official full-precision 0.9B recognition model.

| Backend | Engine | Highlights | HW | Size |
|---------|--------|-----------|-----|------|
| `paddlevl` ★ | PaddleOCR-VL-1.6 + MLX-VLM | Structured Markdown, text, formulas, tables, charts, seals | Apple Silicon | ~1.9 GB |
| `ovis` | OvisOCR2 MLX 4-bit | Markdown, LaTeX math, validated model-grounded figure crops | Apple Silicon | ~625 MB |
| `mineru` | MinerU 3.4.4 | Formula→LaTeX, table→HTML, multi-column, header/footer removal | CPU | ~2 GB |
| `deepseek` | DeepSeek-OCR-2 | Vision-Language OCR, document understanding | GPU/MPS/CPU | ~6.3 GB |
| `logics` | Logics-Parsing-v2 | Qwen3VL multimodal document parsing | GPU/MPS/CPU | ~8.4 GB |
| `paddle` | PaddleOCR 3.5 | 109 languages, deskew, document orientation | CPU | ~100 MB |
| `api` | OpenAI-compatible | Any vision-LLM endpoint, zero local model | API | — |

```bash
# Install once, then use from any directory
pipx install -e .
ocr list --check
ocr use paddlevl

# PaddleOCR-VL-1.6 (default, Apple Silicon)
ocr --doctor
ocr paper.pdf --smoke-pages 3
ocr paper.pdf

# One-run override (does not change the default)
ocr paper.pdf --backend mineru
ocr paper.pdf --backend deepseek
ocr paper.pdf --backend logics
ocr paper.pdf --backend paddle
ocr paper.pdf --backend api

# Batch directory
ocr --batch ./pdfs/

# PDF/Word/PPT → page images + OCR → compile pipeline
ocr paper.pdf -o .wiki/source/paper/
wiki compile .wiki/source/paper/paper.md
```

`ocr --doctor` is the authoritative preflight. For the default backend it
reports the dedicated Python interpreter, Paddle/MLX versions, layout model, and
local full-precision VLM path. `--smoke-pages N` processes exactly the first N
pages without requiring callers to activate the isolated virtual environment.

Every document run writes `<source>_ocr_manifest.json` next to the Markdown. The
manifest records the source hash, runtime, requested and parsed pages, coverage,
content-list path, referenced images, and elapsed time. Agents should use this file
as the success contract. Use `--json` when machine-readable command output is needed.

Local images referenced by OCR Markdown are copied into `.wiki/pages/assets/` during
compile. Compiled pages retain the relevant image links, and query results return the
resolved images together with their source concept. OvisOCR2 crop tags are normalized
to Markdown images and its adapter emits `*_content_list.json`; when that Markdown is
compiled, llm-wiki restores `## Page N` boundaries and source image captions for
page-accurate provenance. Agent-mode task completion then attaches images from the
exact cited pages (plus adjacent-page context) and verifies that every local target exists.

The standalone configuration is `~/.config/ocr/config.yaml` (override with
`OCR_CONFIG`). Use `ocr config show`, `ocr config get KEY`, and
`ocr config set MODEL.options.KEY VALUE` to configure each model independently.
The same interface is available as `python -m ocr`, `python -m ocr.cli`, `wiki ocr`, and
`llm-wiki-ocr`.
The default model is `/Users/wuliang/.paddlex/official_models/PaddleOCR-VL-1.6`;
the isolated runtime is `/Users/wuliang/workspace/PaddleOCR-VL-1.6-MLX/.venv`.
Legacy backend models remain supported under this repository's `models/` directory.

EPUB files enter the compile pipeline directly: `wiki compile textbook.epub`. Chapters
are converted to Markdown in OPF spine order and saved under
`.wiki/source/epub_markdown/`; cover and in-chapter images are extracted, their Markdown
references are rewritten to persistent local assets, and chapter/section locators are
retained for source tracing when fixed page numbers do not exist.

## Configuration

All settings in `wiki_config.yaml`. Create with `wiki config --init`.

```yaml
# ── LLM (API key required only for --mode llm) ──
llm:
  provider: deepseek           # deepseek | openai | ollama | custom
  api_key: ${DEEPSEEK_API_KEY}
  model: deepseek-v4-flash

# ── Search ──
query:
  max_results: 8
  parallel_search: true
  search_streams: metadata,bm25,graph,ledger
  multi_hop_enabled: true
  multi_hop_max_hops: 3
  verify_answers: true

# ── Optional: semantic vector search ──
embeddings:
  enabled: false                # pip install -e '.[vector]'
  backend: zvec
  model_source: modelscope
  index_path: graph/zvec

# ── Optional: cross-encoder reranker ──
reranker:
  enabled: false                # pip install -e '.[rerank]'
  backend: flagembedding
  model: BAAI/bge-reranker-v2-m3
  candidate_count: 20
```

OCR settings are intentionally separate from `wiki_config.yaml`; manage them
with `ocr use` and `ocr config` so the same default is used inside and outside a Wiki.

> `wiki_config.yaml` is gitignored. Environment variables (`${VAR}`) are expanded on load.

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Compile** | Agent reads sources, decides source type, writes schema-compliant wiki pages and graph |
| **Domain Experts** | Content-driven multi-expert compilation for legal, finance, operations, product, academic, training, and other domains |
| **Query** | BM25F + metadata + graph + complete DuckDB ledger search + optional Zvec/reranker → evidence-selected Agent synthesis |
| **Native OKF v0.1** | Compile, store, search, validate, merge, migrate, and distribute one canonical OKF bundle |
| **Lint** | Health scanning + auto-heal: contradictions, stale claims, orphans, broken links |
| **Lifecycle** | Ebbinghaus decay, confidence scoring, contradiction detection, supersession |
| **Memory Tiers** | Working → Episodic → Semantic → Procedural, automatic consolidation |
| **Ledger** | Structured table management with natural language → SQL (DuckDB) |
| **Multi-lingual** | Chinese/English dual retrieval engine (jieba + Porter stemming) |
| **Dream (Auto)** | Self-looping query-driven optimization with git snapshots, quality gating, and experience accumulation |
| **Doctor** | User feedback diagnosis + repair: classify → search → fix → verify |
| **Audit** | Immutable audit trail for every operation |

## Documentation

| Document | Content |
|----------|---------|
| [Architecture & Lifecycle](docs/ARCHITECTURE.md) | 3-layer design, 10-stage knowledge lifecycle |
| [Benchmark Details](docs/BENCHMARK.md) | RAGAS evaluation, industry comparison, per-case results |
| [CLI Reference](docs/CLI.md) | Complete command reference |
| [Improvement Plan](docs/IMPROVEMENT_PLAN.md) | Future roadmap and enhancement proposals |

## Project Structure

```
llm-wiki-skill/
├── scripts/           # Python automation (~30 scripts)
│   ├── wiki.py        # Unified CLI
│   ├── compile_v2.py  # LLM source → wiki compiler
│   ├── query.py       # Wiki-native search + answer synthesis
│   ├── search.py      # Metadata/BM25F/graph search and weighted fusion
│   ├── zvec_backend.py # Optional embedded vector index over OKF concepts
│   ├── rerank.py      # Optional cross-encoder reranking
│   ├── lint.py        # Health scan + auto-heal
│   ├── dream.py       # Self-looping maintenance (4-phase, auto mode)
│   ├── doctor.py       # User feedback diagnosis + auto-repair
│   ├── okf.py          # OKF v0.1 validation, import, and export
│   ├── ledger.py      # Structured table management (DuckDB)
│   └── ...
├── .wiki/             # Wiki data (LLM-generated)
│   ├── pages/         # Native OKF bundle root (concepts + index.md + log.md)
│   ├── graph/         # entities.json, edges.json, optional embeddings
│   ├── ledger/        # ledger.duckdb database
│   └── source/        # Original source files (immutable)
├── .claude/hooks/     # Automation hooks (optional)
├── tests/             # Test suite (206 tests)
├── templates/         # Page templates
└── references/        # Deep-dive docs
```

## Design

Based on [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and [Rohit's v2 extension](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2). 100% compliant with both specifications.

| Principle | Implementation |
|-----------|---------------|
| 3-layer architecture (Source→Wiki→Schema) | `source/` + `pages/` + `schema.md`/`wiki_config.yaml` |
| Ingest → Pages → Index → Log | `compile_v2.py` full pipeline |
| Same-name entity protection | Auto-prefix + concept aggregation pages |
| Query → Search → Synthesize → File-back | `query.py` + `--file-back` + 6 output formats |
| Lint → Auto-heal | `lint.py --auto-heal` |
| 12 typed relationships | `uses`, `depends_on`, `extends`, `contradicts`, `supersedes`... |
| Ebbinghaus forgetting curve | 6 entity half-lives (arch: 260d, bug: 20d...) |
| Memory consolidation | working → episodic → semantic → procedural |
| Privacy filtering | 5 sensitive patterns filtered before LLM sends |
| Dream self-looping | git snapshots + quality gating + rollback + SHA256-deduped experiences |
| Doctor diagnosis | regex classify → wiki search → strategy repair → verify → persist |

## License

MIT
