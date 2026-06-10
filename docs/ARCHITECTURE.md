# Architecture & Knowledge Lifecycle

## 3-Layer Design

```
┌──────────────────────────────────────────────┐
│  Raw Sources (.wiki/source/)                  │
│  Immutable. LLM reads, never modifies.        │
│  Papers, articles, PDFs, images.              │
├──────────────────────────────────────────────┤
│  Wiki (.wiki/pages/)                          │
│  LLM-owned. Summaries, entities, concepts,    │
│  comparisons, syntheses.                      │
│  Humans read-only.                            │
├──────────────────────────────────────────────┤
│  Schema (.wiki/schema.md + wiki_config.yaml)  │
│  Conventions, ingestion rules, quality bars.  │
│  You + LLM evolve together.                   │
└──────────────────────────────────────────────┘
```

## 7-Stream Hybrid Search

```
User Query
  ↓
Query Planner → intent classification (fact/ledger/relationship/comparison)
  ↓
Query Rewriter → lexical variants (space/hyphen/domain terms)
  ↓
┌─────────────── Parallel Retrieval ───────────────┐
│ Metadata (aliases/keywords/questions)             │
│ Chunk BM25 (heading-aware chunks)                 │
│ Chunk Vector (semantic chunk vectors)             │
│ Page BM25 (full-text keyword)                     │
│ Page Vector (page semantic vectors)               │
│ Graph (entity relationship traversal)             │
│ Ledger (structured table matching)                │
└──────────────────────────────────────────────────┘
  ↓
Reciprocal Rank Fusion (RRF) → multi-stream fusion
  ↓
Light Reranker → stream preference + lexical overlap
  ↓
LLM Synthesis → structured answer + citations
```

## Knowledge Lifecycle (10 Stages)

```
Source → Compile → Pages + Graph → Query → File-back
              │         │            │
              ▼         ▼            ▼
           Log.md   entities.json   Answers → new pages
           Audit    edges.json
              │         │
              ▼         ▼
           Lint → Stale → Decay → Archive
           Auto-heal   Contradictions   Forgotten
              │
              ▼
       Consolidate → Working → Episodic → Semantic → Procedural
              │
              ▼
       Crystallize → Session → Digest → Facts → Working Memory
```

### Stage 1: Ingest (Compile)
LLM reads source → extracts entities → builds typed pages with YAML frontmatter.

### Stage 2: Graph Building
12 relationship types extracted from wikilinks: `uses`, `depends_on`, `extends`, `improves_upon`, `contradicts`, `supersedes`, `caused_by`, `fixed_by`, `replaces`, `relates_to`, `part_of`, `implemented_by`.

### Stage 3: Query & File-back
7-stream hybrid search → RRF fusion → LLM synthesis → optional file-back as new wiki page.

### Stage 4: Lint & Auto-heal
Detects: contradictions, stale claims, orphan pages, broken links. Auto-heals what it can.

### Stage 5: Contradiction & Supersession
Re-compiling the same source auto-detects contradictions (factual/temporal/numerical/opinion) with severity scoring.

### Stage 6: Confidence Decay
Ebbinghaus forgetting curve per entity type:

| Entity Type | Half-life |
|-------------|----------|
| architecture | 260 days |
| project | 130 days |
| pattern | 87 days |
| bug | 20 days |
| meeting | 10 days |
| preference | 527 days |

### Stage 7-8: Memory Consolidation & Crystallization
Working → Episodic → Semantic → Procedural pipeline with automatic promotion. Sessions crystallized into structured digests.

## Entity Name Collision Protection

Same name from different sources? Auto-prefix prevents overwrites:

```
Source A (competition plan) → expert-review-committee.md
Source B (course plan)      → coursepl-expert-review-committee.md
                            → concepts/expert-review-committee.md (aggregation)
```

## Embedding Architecture

- **Page embeddings**: Full-page semantic vectors (Qwen3-Embedding-8B, 4096-dim)
- **Chunk embeddings**: Heading-aware chunk vectors for precise retrieval
- **Metadata index**: Aliases, keywords, questions for recall
- **BM25 index**: Cached to disk, auto-rebuilds on page changes
