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

## Directory Structure

All wiki files live under `.wiki/` in the project root:

```
.wiki/
├── schema.md              # The most important file. Defines entities, relationships,
│                          # ingest rules, quality standards, and consolidation schedule.
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

### Initializing a New Wiki

1. **Create the directory structure**:
   ```bash
   mkdir -p .wiki/{pages/{entities,decisions,sessions,patterns},graph,memory,audit}
   ```

2. **Create `schema.md`** using the template from `templates/schema.md`. Customize it
   for the user's domain. The schema is co-evolved over time.

3. **Create `config.json`** with sensible defaults (retention curves, quality thresholds,
   consolidation schedule).

4. **Create `pages/index.md`** as the human-readable entry point.

### Seeding from Existing Knowledge

If the user already has notes, documents, or a codebase:
1. Ingest each source (document, README, discussion) following the Ingest workflow
2. Let the LLM extract entities, build the graph, and create pages
3. Run a lint pass to check consistency

## Core Workflows

### 1. Ingest — From Source to Structure

When the user provides a source (article, document, conversation, code, URL), or
when a session produces insights worth preserving:

1. **Parse the source**: Extract key claims, facts, decisions, and entities
2. **Filter sensitive data**: Strip API keys, tokens, passwords, PII before anything
   hits the wiki. See `references/privacy-governance.md`
3. **Extract entities**: Identify people, projects, libraries, concepts, files, decisions.
   Each gets a type, attributes, and relationships. See `references/knowledge-graph.md`
4. **Score confidence**: How many sources support each claim? How recently confirmed?
   Any contradictions? See `references/lifecycle.md`
5. **Check for existing knowledge**: Does this contradict, confirm, or supersede
   existing claims? Resolve before writing.
6. **Write to wiki**:
   - Entity pages in `pages/entities/` using `templates/entity-page.md`
   - Decision records in `pages/decisions/` (ADR format if applicable)
   - Update `graph/entities.json` and `graph/edges.json`
   - Add to `memory/working.json` as a new observation
7. **Log operation** to `audit/trail.jsonl`

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
| `scripts/ingest.py` | Process a source file/URL, extract entities, write to wiki |
| `scripts/search.py` | Hybrid search over wiki pages, graph, and embeddings |
| `scripts/lint.py` | Quality checks: orphans, staleness, contradictions, broken links |
| `scripts/consolidate.py` | Promote observations through memory tiers, apply decay |
| `scripts/graph.py` | Build and query the knowledge graph |

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
