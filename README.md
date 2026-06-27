<p align="center">
  <a href="README.md">🇬🇧 English</a> &nbsp;|&nbsp;
  <a href="README_CN.md">🇨🇳 中文</a>
</p>

# llm-wiki

**A Living Knowledge Base That Compounds.** Not RAG — don't re-derive, compile once. The Agent reads your sources, builds a typed knowledge graph, and maintains it forever. Cross-references, contradiction detection, confidence decay — all automatic.

<p align="center">
  <img src="docs/benchmark_chart.png" alt="RAGAS Benchmark: llm-wiki vs Industry" width="100%">
</p>

> **Faithfulness 1.00** · **Answer Relevance 1.00** · **Answer Correctness 0.91** · **Context Recall 0.94**. Wiki-native pipeline (compile → search → synthesize). No embeddings, no chunks, no cross-encoders. [Full benchmark →](docs/BENCHMARK.md)

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
vim wiki_config.yaml      # set your API key
wiki init                 # initialize .wiki/
wiki compile paper.md     # Agent reads source → structured pages
wiki query "What is X?"   # search → synthesize → answer with citations
```

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
**Sources**: [[multi-head-latent-attention]], [[deepseek-moe]]
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

llm-wiki's wiki-native architecture delivers sub-50ms search latency — no embedding calls, no vector DB round-trips:

| Pipeline | Search Latency | Components |
|----------|---------------|------------|
| **llm-wiki** | **~41ms avg** | BM25 + metadata + graph (in-process) |
| RAG (chunk+embed) | 200–500ms | Embedding API + vector DB |
| GraphRAG | 500ms–2s | Community detection + LLM summarization |

> ⚡ **41ms search latency** — 5–50× faster than embedding-based RAG. Compiled once, queried instantly. [Full benchmark →](docs/BENCHMARK.md)

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

## Benchmark

We evaluate the **complete product pipeline** (compile → search → synthesize), not components. **No embeddings, no chunks, no cross-encoders** — pure wiki-native architecture. Industry baselines from published RAGAS/RGB/GraphRAG papers.

| System | Faithfulness | Answer Relevance | Context Recall | Answer Correctness |
|--------|-------------|-----------------|----------------|-------------------|
| Naive RAG (chunk+embed) | 0.72 | 0.78 | 0.68 | 0.65 |
| RAG + Reranker | 0.83 | 0.85 | 0.76 | 0.78 |
| RAGFlow (est.) | 0.86 | 0.84 | 0.79 | 0.80 |
| GraphRAG (Microsoft) | 0.88 | 0.87 | 0.84 | 0.83 |
| **llm-wiki ★** | **1.00** | **1.00** | **0.94** | **0.91** |

> **All scores are LLM-as-judge (RAGAS framework)** over 19 test cases across tech, business, and Chinese domains. Industry baselines from published papers — not identical test sets. llm-wiki: compile_v2 → BM25+metadata+graph → entity link → 3-signal rank → synthesize. **4 of 5 metrics surpass GraphRAG.**

→ [Full benchmark report with per-case breakdown](docs/BENCHMARK.md)

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Compile** | Agent reads sources, decides source type, writes schema-compliant wiki pages and graph |
| **Query** | Wiki-native search (metadata + BM25 + graph + ledger) + entity linking + 3-signal ranking → Agent synthesis |
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
| [Installation & Offline Deploy](docs/INSTALL.md) | pip install, Windows notes, offline wheel packaging |
| [Configuration](docs/CONFIGURATION.md) | LLM, embedding, OCR, query settings |
| [Architecture & Lifecycle](docs/ARCHITECTURE.md) | 3-layer design, 10-stage knowledge lifecycle |
| [Benchmark Details](docs/BENCHMARK.md) | RAGAS evaluation, industry comparison, per-case results |
| [Ledger Management](docs/LEDGER.md) | Structured tables, CSV import, NL→SQL query |
| [OCR Backends](docs/OCR.md) | MinerU, DeepSeek-OCR, Logics, PaddleOCR comparison |
| [CLI Reference](docs/CLI.md) | Complete command reference |

## Project Structure

```
llm-wiki-skill/
├── scripts/           # Python automation (~30 scripts)
│   ├── wiki.py        # Unified CLI
│   ├── compile_v2.py  # LLM source → wiki compiler
│   ├── query.py       # Wiki-native search + answer synthesis
│   ├── search.py      # Metadata/BM25/graph search; vector paths are opt-in
│   ├── lint.py        # Health scan + auto-heal
│   ├── dream.py       # Self-looping maintenance (4-phase, auto mode)
│   ├── doctor.py       # User feedback diagnosis + auto-repair
│   ├── ledger.py      # Structured table management (DuckDB)
│   └── ...
├── .wiki/             # Wiki data (LLM-generated)
│   ├── pages/         # Structured markdown pages
│   ├── graph/         # entities.json, edges.json, optional embeddings
│   ├── ledger/        # ledger.duckdb database
│   └── source/        # Original source files (immutable)
├── .claude/hooks/     # Automation hooks (optional)
├── tests/             # Test suite (180 tests)
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
