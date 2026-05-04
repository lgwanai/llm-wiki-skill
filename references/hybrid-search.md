# Hybrid Search

A single `index.md` file works up to ~100-200 pages. Beyond that, the index becomes
too long for the LLM to read in one pass, and you need real search. The best approach
combines three search streams with reciprocal rank fusion.

## When to Implement

- **Level 1-2**: `index.md` is sufficient. Keep it updated manually or via hooks.
- **Level 3+**: Add keyword search (grep over wiki pages) as a bridge
- **Level 5**: Full hybrid search with embeddings and graph traversal

## Three Search Streams

### 1. BM25 / Keyword Search

Classic term-matching with enhancements:

- **Stemming**: "deploying" matches "deploy", "deployment"
- **Synonym expansion**: "cache" also matches "caching", "cached"
- **Field weighting**: Title matches count 3x body text matches. Entity attributes
  (tags, type) count 2x.
- **Phrase matching**: Exact phrase matches ranked higher than scattered term matches

**Strengths**: Fast, finds exact terms, works without embeddings
**Weaknesses**: Misses semantic connections ("database" won't find "Postgres" without
synonym mapping)

### 2. Vector / Semantic Search

Embedding-based similarity search:

- **Generate embeddings** for each wiki page (title + content)
- **Store** in a local vector index (SQLite with sqlite-vss, or a simple file-based
  index using FAISS)
- **Query**: Embed the search query, find nearest neighbors by cosine similarity

**Strengths**: Finds semantically related content even with different wording
**Weaknesses**: Computationally more expensive, requires embeddings model, can return
tangentially related results

### 3. Graph Traversal Search

Entity-aware structural search:

- **Start at entity nodes** matching query terms
- **Walk typed edges** (`uses`, `depends_on`, `contains`, etc.)
- **Filter by relationship type** relevant to the query
- **Rank by path confidence** (product of edge confidences)

**Strengths**: Discovers non-obvious connections, great for impact analysis and
relationship queries
**Weaknesses**: Only finds content connected via the graph, requires populated graph

## Reciprocal Rank Fusion (RRF)

Combine results from all three streams using RRF:

```
RRF_score(d) = Σ (1 / (k + rank_i(d)))

Where:
- d is a document
- i iterates over search streams (BM25, vector, graph)
- rank_i(d) is the rank of d in stream i (1-indexed)
- k is a constant (default: 60, higher = less penalty for low ranks)
```

### Fusion Algorithm

1. Run all three searches independently
2. For each document, compute RRF score
3. Sort by descending RRF score
4. Deduplicate (same page found by multiple streams)
5. Return top N results

### Weighting Streams by Query Type

Adjust stream weights based on query intent:

| Query Type | BM25 Weight | Vector Weight | Graph Weight |
|-----------|-------------|---------------|--------------|
| "Find the page about X" | 1.0 | 0.5 | 0.3 |
| "What's related to X?" | 0.5 | 0.8 | 1.0 |
| "What uses X?" | 0.2 | 0.3 | 1.5 |
| "Explain concept X" | 0.5 | 1.2 | 0.3 |
| "Impact of changing X" | 0.3 | 0.5 | 2.0 |

Detect query intent by looking for keywords:
- Impact analysis: "impact", "affect", "break", "depends on", "what would happen if"
- Relationship/connection: "related to", "connected", "what else", "similar to"
- Definition/explanation: "what is", "explain", "how does", "tell me about"
- Finding specific: "find", "where is", "show me the", "look up"

## Implementation Approaches

### Lightweight (Level 3)

No embeddings, just keyword + graph:

1. **Keyword search**: `grep -rl "query" .wiki/pages/` with basic preprocessing
2. **Graph search**: Read `graph/edges.json`, traverse from matching entities
3. **Fusion**: Simple intersection + append

### Full (Level 5)

All three streams with proper infrastructure:

1. **Embedding generation**: Use a local embedding model (all-MiniLM-L6-v2 via
   sentence-transformers) or an API (OpenAI embeddings). Generate on ingest, store
   in the entity page's YAML frontmatter or a separate index file.
2. **Vector index**: FAISS for small wikis (<1000 pages), Qdrant or Weaviate for larger.
   Rebuild index after consolidation.
3. **Hybrid retrieval**: Implement RRF fusion in `scripts/search.py`
4. **Caching**: Cache frequent query results

### File-Based Embedding Index

For wikis where running a vector database is overhead, store embeddings inline:

```yaml
---
id: redis-caching
title: Redis
embedding: [0.023, -0.145, 0.891, ...]  # 384-dimensional vector
---
```

During search, load all embeddings into memory (works for <10,000 pages), compute cosine
similarity, and sort. For larger wikis, use FAISS with periodic index rebuilds.

## Search Quality Tuning

### Precision vs. Recall

- **Precision**: How many returned results are actually relevant?
- **Recall**: How many relevant results were found?

Tune by adjusting the RRF constant `k`:
- Higher k (e.g., 100) → more weight to lower-ranked results → higher recall, lower precision
- Lower k (e.g., 30) → only top-ranked results matter → higher precision, lower recall

Default k=60 is a good balance for most wikis.

### Relevance Feedback

After each search, optionally ask the user (or auto-detect from click-through):
- Which results were useful?
- Which were irrelevant?

Use this feedback to:
- Boost terms/pages that were useful
- Penalize pages that were irrelevant
- Tune stream weights

### Index Maintenance

- **On ingest**: Add new pages to all three indices
- **On lint**: Re-index pages that were modified
- **On consolidate**: Rebuild vector index if significant changes
- **Scheduled**: Full re-index weekly for active wikis

## Search UX Patterns

When presenting search results to the user:

### Result Format

```markdown
## Search: "redis caching configuration"

### Top Results

1. **[[Redis]]** (confidence: 0.9)
   Entity: library | Type: infrastructure
   Redis is used for session caching across auth-service and rate-limiter.
   Matched by: keyword, graph

2. **[[auth-service]]** (confidence: 0.85)
   Entity: project | Owner: Sarah Chen
   Uses Redis for session token storage. Configuration at docker-compose.yml:45.
   Matched by: graph (depends_on Redis)

3. **[[Session 2024-03-15 - Config Review]]** (confidence: 0.7)
   Session digest
   Reviewed Redis configuration, found hardcoded password in docker-compose.yml.
   Matched by: vector

### Did you mean?
- [[Redis Migration Notes]]
- [[rate-limiter]]
```

### Progressive Disclosure

1. Show top 3-5 results with snippets
2. Offer "show more" for additional results
3. Show "related entities" from graph traversal
4. Offer "did you mean?" for ambiguous queries
