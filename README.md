# llm-wiki-skill

A Claude Code skill implementing **LLM Wiki v2** — a production-hardened pattern for building personal knowledge bases that compound over time with LLM-powered automation.

> This builds on [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and extends it with patterns proven in [agentmemory](https://github.com/rohitg00/agentmemory).

## Quick Start

### Installation

Copy this directory to your Claude Code skills directory:

```bash
cp -r llm-wiki-skill ~/.claude/skills/llm-wiki/
```

Or register in `.claude/settings.json`:

```json
{
  "skills": {
    "paths": ["~/workspace/llm-wiki-skill"]
  }
}
```

### First Use

In any Claude Code session, say:
- "Set up a wiki for this project"
- "Build a knowledge base"
- "Start tracking what we learn"

The skill triggers and guides you through Level 1 setup — creating `.wiki/` directory
structure, schema, and index.

## What This Skill Does

When triggered, Claude becomes a disciplined knowledge librarian that:

1. **Ingests sources** — extracts entities, builds knowledge graph, creates structured pages
2. **Answers questions** — searches across wiki pages, graph, and embeddings with confidence scores
3. **Maintains quality** — auto-lints, detects contradictions, heals broken links
4. **Consolidates knowledge** — promotes observations through memory tiers, applies retention decay
5. **Crystallizes sessions** — distills working sessions into digestible summaries that compound over time

## Capability Levels

Choose your starting point based on needs:

| Level | Capabilities | When to use |
|-------|-------------|-------------|
| **1 — Minimal Wiki** | Manual ingest, query, lint. Flat pages + index. | Getting started. Runs in minutes. |
| **2 — Lifecycle** | Confidence scoring, supersession, decay, memory tiers. | When wiki accumulates noise. |
| **3 — Structure** | Entity extraction, typed relationships, graph traversal. | When flat pages aren't enough. |
| **4 — Automation** | Auto-ingest, auto-lint, context injection, crystallization. | When maintenance becomes burden. |
| **5 — Scale + Collab** | Hybrid search, mesh sync, shared/private scoping. | Teams, 500+ pages, multi-agent. |

See `references/implementation-spectrum.md` for detailed setup guides at each level.

## Project Structure

```
llm-wiki-skill/
├── SKILL.md                         # Main skill — triggers, workflows, reference pointers
├── README.md                        # This file
├── LICENSE                          # MIT
├── pyproject.toml                   # Python project configuration
├── requirements.txt                 # Python dependencies
│
├── references/                      # Deep-dive pattern docs (loaded on demand)
│   ├── lifecycle.md                 # Confidence scoring, supersession, forgetting
│   ├── knowledge-graph.md           # Entity extraction, typed relationships
│   ├── hybrid-search.md             # BM25 + vector + graph fusion
│   ├── automation.md                # Event hooks, schedules
│   ├── quality.md                   # Scoring, self-healing, contradiction resolution
│   ├── collaboration.md             # Mesh sync, shared/private scoping
│   ├── privacy-governance.md        # Filtering, audit trails
│   ├── crystallization.md           # Session → digest pipeline
│   ├── output-formats.md            # Tables, timelines, graphs, slides
│   └── implementation-spectrum.md   # Level-by-level upgrade guide
│
├── templates/                       # Reusable page templates
│   ├── schema.md                    # Wiki schema — the most important file
│   ├── entity-page.md               # Entity page with typed YAML frontmatter
│   ├── session-digest.md            # Crystallized session summary
│   └── index.md                     # Human-readable catalog
│
├── scripts/                         # Automation scripts (Python)
│   ├── ingest.py                    # Source ingestion + entity extraction
│   ├── search.py                    # Hybrid search engine
│   ├── lint.py                      # Quality linter with auto-healing
│   ├── consolidate.py               # Memory tier promotion + decay
│   ├── graph.py                     # Knowledge graph builder & querier
│   └── crystallize.py               # Session → digest pipeline
│
└── evals/                           # Test cases for skill evaluation
    └── evals.json
```

## Configuration

### Wiki Configuration

After setup, `.wiki/config.json` controls wiki behavior:

```json
{
  "hooks": {
    "on_new_source": { "enabled": true, "auto_ingest": true },
    "on_session_start": { "enabled": true, "context_injection": true },
    "on_session_end": { "enabled": true, "auto_crystallize": true }
  },
  "retention": {
    "architecture_decisions": { "half_life_days": 180 },
    "project_facts": { "half_life_days": 90 },
    "bug_reports": { "half_life_days": 14 }
  },
  "quality": {
    "auto_heal": true,
    "min_score": 0.4
  }
}
```

### Schema Co-Evolution

The wiki schema (`.wiki/schema.md`) is the most critical file. It encodes entity types,
relationship types, ingest rules, quality standards, and consolidation schedules. You
and Claude co-evolve it over time. Share it with someone in a similar domain and they
get a running start.

## Python Setup (for scripts)

If you plan to use the automation scripts:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For Level 5 search features:
```bash
pip install -r requirements.txt  # includes sentence-transformers, faiss-cpu
```

## License

MIT — see LICENSE file.

## References

- [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — original concept
- [agentmemory](https://github.com/rohitg00/agentmemory) — persistent memory engine for AI agents
- [Design blueprint](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2) — full v2 specification
