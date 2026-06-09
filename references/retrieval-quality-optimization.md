# Retrieval Quality Optimization Plan

This document summarizes concrete ways to improve LLM Wiki retrieval quality and answer accuracy across three layers:

1. Cleaner data at ingest time
2. Smarter index structures
3. Better query-time reasoning and verification

The goal is not just to retrieve more results, but to make retrieval measurable, explainable, and reliably grounded in wiki pages, images, graph entities, and DuckDB ledger rows.

---

## 1. Cleaner Data At Ingest Time

Retrieval quality starts before indexing. If compile output is noisy, inconsistent, or missing source anchors, no search algorithm can fully recover.

### 1.1 Stronger Source Normalization

During `wiki compile`, every source should be normalized into a clean markdown-like intermediate document before entity extraction.

Recommended fields:

```yaml
source:
  original_path: /absolute/path/to/source
  source_type: doc | article | code | conversation | image | ledger
  extracted_at: 2026-06-09T00:00:00Z
  extractor: text | ocr | image_analysis | url2markdown
```

For images, the normalized content should always retain:

- Original image path
- Visual analysis
- OCR text when available
- Detected structure: mind map hierarchy, flowchart steps, table cells, chart axes, numbers, legends

### 1.2 Compile Metadata For Search

Human-readable page content is not always optimal for retrieval. Compile should generate search-focused metadata in YAML frontmatter:

```yaml
summary: One-sentence factual summary.
keywords:
  - approval workflow
  - budget threshold
aliases:
  - Order Approval
  - 订单审批
questions:
  - What threshold requires director approval?
  - When can director approval be skipped?
source_refs:
  - path: /absolute/path/to/source.png
    kind: image
```

High-value fields:

- `summary`: improves snippets and reranking.
- `keywords`: improves sparse retrieval.
- `aliases`: handles abbreviation, Chinese/English variants, and model-name variants.
- `questions`: supports hypothetical question embeddings.
- `source_refs`: improves citation accuracy.

### 1.3 Entity Alias And Canonicalization

Compile should normalize entity IDs while preserving aliases:

```yaml
id: deepseek-v4
name: DeepSeek-V4
aliases:
  - DeepSeek V4
  - DeepSeek-V4-Pro
  - 深度求索 V4
```

Query-time retrieval should expand aliases before BM25, vector search, graph search, and ledger search.

### 1.4 Cleaner Entity Type Routing

Entity/concept routing affects graph quality and search precision.

Recommended behavior:

- Concept-like types go to `pages/concepts`: `concept`, `technique`, `model`, `framework`, `benchmark`, `paper`, `pattern`.
- Concrete or operational types go to `pages/entities`: `entity`, `process`, `rule`, `role`, `event`, `file`, `tool`, `library`, `project`, `person`.

Incorrect routing creates noisy indexes and makes graph traversal less meaningful.

### 1.5 Source-Aware Deduplication

Compile should detect repeated or near-duplicate content before writing pages.

Recommended checks:

- Exact source hash
- Normalized content hash
- Near-duplicate summary similarity
- Same entity from different sources should reinforce the page, not blindly duplicate it

Page metadata should track reinforcement:

```yaml
sources:
  - source-a.md
  - source-b.md
reinforcement_count: 2
last_confirmed: 2026-06-09
```

### 1.6 Ingest-Time Quality Gates

Before writing pages, compile should reject or flag:

- Pages without source context
- Pages with no meaningful summary
- Pages with malformed YAML
- Unsupported entity types
- Relationships without wikilinks
- Image-derived pages without original image path
- Ledger-derived answers without table and row references

---

## 2. Smarter Index Structures

The current hybrid search shape is useful, but stronger indexing will make retrieval more precise and easier to debug.

### 2.1 Unify Embedding Generation For Pages And Queries

Page embeddings and query embeddings must use the same model and provider.

Current risk:

- `generate_embeddings.py` can generate embeddings from configured API models.
- Query-time vector search may use another embedding source.
- If page and query vectors come from different models, semantic search becomes unreliable.

Required fix:

- Use one shared `get_embedding()` path for both indexing and query-time embedding.
- Store index metadata:

```json
{
  "_meta": {
    "embedding_model": "Qwen3-Embedding-4B-4bit-DWQ",
    "provider": "api",
    "dimension": 384,
    "created_at": "2026-06-09T00:00:00Z",
    "schema_version": 2
  },
  "items": {}
}
```

If config changes, `wiki query` should warn that embeddings are stale and recommend:

```bash
wiki embed --force
```

### 2.2 Chunk-Level Index

Whole-page embeddings are too coarse. Long pages may contain several unrelated facts, and query hits may be buried after the first 2000 characters.

Recommended chunk index:

```json
{
  "chunk_id": "order-approval-flow#key-details:1",
  "page_id": "order-approval-flow",
  "heading_path": ["Order Approval Flow", "Key Details"],
  "text": "Amount 12000 CNY is compared against threshold 10000.",
  "source_refs": ["/private/tmp/test.png"],
  "entity_type": "process",
  "embedding": []
}
```

Chunking rules:

- Split by markdown headings first.
- Preserve lists and tables as atomic chunks when possible.
- Keep chunks around 300-800 tokens.
- Keep heading path and source refs with every chunk.
- Retrieve chunks first, then expand to page context when needed.

### 2.3 Multi-Index Retrieval

Use separate indexes for different retrieval signals:

- BM25 page index
- BM25 chunk index
- Vector chunk index
- Entity alias index
- Graph entity index
- Ledger schema index
- Ledger row/content index

Each stream should return a common result type:

```python
SearchResult(
    id="...",
    source_type="page|chunk|ledger_row|graph_entity",
    title="...",
    text="...",
    path="...",
    score=0.0,
    stream="bm25|vector|graph|ledger|alias",
    metadata={},
    citations=[],
)
```

This makes fusion, reranking, synthesis, and debug tracing much easier.

### 2.4 Reranker Layer

Use two-stage retrieval:

1. Recall broadly from BM25, vector, graph, alias, and ledger.
2. Rerank top candidates with a stronger relevance model.

Recommended pipeline:

```text
query
  -> recall top 20 per stream
  -> deduplicate
  -> rerank top 30
  -> select top 5-8 context items
  -> answer synthesis
```

Reranker options:

- API reranker: bge-reranker, Jina reranker, Qwen reranker
- Local cross-encoder
- LLM listwise reranking for difficult questions

Reranking usually gives the largest visible quality jump after chunk indexing.

### 2.5 Graph Expansion Index

Graph search should not only match entity names. It should use retrieved seed entities and expand by relationship type.

Recommended behavior:

- BM25/vector find seed chunks/pages.
- Map seeds to entity IDs.
- Expand 1-2 hops.
- Weight edges by type and query intent.

Example weights:

```yaml
depends_on: 1.0
part_of: 0.9
implements: 0.9
uses: 0.8
related_to: 0.3
```

Intent-specific graph traversal:

- Impact analysis: `depends_on`, `uses`, `implemented_by`
- Source/provenance: source links and reinforcement
- Architecture: `part_of`, `contains`, `implements`
- Contradiction: `contradicts`, `supersedes`

### 2.6 Ledger-Aware Indexes

Ledger data should not be treated like plain text only.

Recommended ledger indexes:

- Table name and description index
- Field name and field alias index
- Row text BM25 index
- Row embedding index
- Numeric/date field metadata for filtering

For structured questions, query should prefer SQL over unstructured retrieval.

Example:

```text
Query: 预算超过 40 万且状态为进行中的项目
Plan:
  - identify table: 项目台账
  - map fields: 预算, 状态
  - generate SQL filter
  - return rows as grounded context
```

---

## 3. Better Query-Time Reasoning And Verification

Retrieval should be query-aware. Different questions need different tools and context.

### 3.1 Query Planner

Before retrieval, classify the query:

```json
{
  "intent": "fact|comparison|timeline|impact|ledger_filter|relationship|how_to",
  "language": "zh",
  "entities": ["项目台账"],
  "keywords": ["预算", "进行中"],
  "filters": [
    {"field": "预算", "op": ">", "value": 400000},
    {"field": "状态", "op": "=", "value": "进行中"}
  ],
  "preferred_streams": ["ledger", "bm25", "graph"]
}
```

The planner decides:

- Whether to search wiki pages, ledger tables, graph, or all streams.
- Whether to use SQL generation.
- Which edge types matter.
- Whether the answer needs comparison, timeline, table, or graph format.

### 3.2 Query Rewrite And Expansion

Generate retrieval variants:

- Original query
- Keyword query
- Alias-expanded query
- Chinese/English translation or mixed-language equivalent
- Entity-name focused query
- Field-name focused query for ledgers

Example:

```text
Original: 哪些项目预算超过40万
Expanded:
  - 项目 预算 超过 40万
  - budget greater than 400000 project
  - 项目台账 预算 状态
```

Use these variants for recall, then rerank using the original query.

### 3.3 Structured Ledger Reasoning

For ledger questions, prefer deterministic SQL:

1. Retrieve candidate tables.
2. Retrieve relevant fields.
3. Generate SQL with schema context.
4. Execute read-only query.
5. Page large results.
6. Cite table name, row IDs, and selected fields.

This avoids hallucinating over structured data.

### 3.4 Context Packing

Answer quality often fails because the right page is retrieved but the wrong part is sent to the LLM.

Context packing should:

- Use hit chunks, not only page starts.
- Include heading path.
- Include source refs.
- Add small neighboring chunks when needed.
- Keep ledger rows compact and field-labeled.
- Deduplicate repeated content.

Recommended context item:

```text
--- CHUNK: order-approval-flow#key-details
Page: [[order-approval-flow]]
Source: /private/tmp/test.png
Heading: Order Approval Flow > Key Details
Text:
Amount 12000 CNY is compared against threshold 10000.
```

### 3.5 Answer Verification

Before final answer, run a lightweight grounding check:

- Does every key claim have a supporting retrieved chunk or ledger row?
- Are numeric values copied exactly?
- Are table filters reflected correctly?
- Did the answer introduce unsupported facts?
- Should the answer say "not found" instead?

For high-stakes or ambiguous answers, use a second LLM pass:

```text
Given the answer and sources, mark each claim as supported, unsupported, or contradicted.
```

### 3.6 Better No-Answer Behavior

The system should explicitly refuse unsupported answers:

```text
I did not find this in the current wiki/ledger. Closest matches are...
```

This is especially important for:

- Missing ledger fields
- Unindexed pages
- Stale embeddings
- Ambiguous entity aliases
- Questions outside the current project wiki

### 3.7 Search Debug Trace

Add:

```bash
wiki query "..." --debug-search
```

Debug output should include:

- Query planner result
- Query rewrites
- BM25 top results
- Vector top results
- Graph top results
- Ledger top results
- RRF score
- Reranker score
- Final context sent to LLM

This turns retrieval tuning from guesswork into engineering.

### 3.8 Retrieval Evaluation

Create `.wiki/evals/retrieval.jsonl`:

```json
{"query":"什么情况下需要总监审批？","expected_pages":["order-approval-flow"],"must_contain":["10000","Director Approval"]}
{"query":"预算超过40万的进行中项目有哪些？","expected_ledgers":["项目台账"],"must_contain":["预算","状态"]}
```

Metrics:

- Recall@5
- Recall@10
- MRR
- NDCG
- Ledger table hit rate
- Expected field hit rate
- Citation correctness
- Unsupported-answer rate

Add:

```bash
wiki search eval
wiki search doctor
```

`doctor` should check:

- Embedding coverage
- Embedding model/config mismatch
- BM25 cache freshness
- Missing chunk index
- Orphan graph nodes
- Alias coverage
- Ledger embedding coverage

---

## Recommended Implementation Order

### Phase 1: Correctness Foundation

1. Unify page and query embedding generation.
2. Store embedding index metadata.
3. Add stale-index detection.
4. Add retrieval eval file and basic metrics.
5. Add debug-search trace.

### Phase 2: Retrieval Quality

1. Add chunk-level index.
2. Search chunks before pages.
3. Add alias/keyword/question metadata at compile time.
4. Add query rewrite and alias expansion.
5. Add reranker.

### Phase 3: Structured Reasoning

1. Add query planner.
2. Route ledger questions to SQL.
3. Add field-level ledger retrieval.
4. Add graph seed expansion.
5. Add answer verification.

### Phase 4: Operations

1. Add `wiki search doctor`.
2. Add index versioning and migration checks.
3. Add CI tests for retrieval evals.
4. Track quality metrics over time.

---

## Highest-Impact Three Changes

If only three changes can be implemented first, choose:

1. **Unify embedding generation for indexing and query-time search.**
2. **Move from page-level embeddings to chunk-level indexes.**
3. **Add a reranker after broad hybrid recall.**

These three changes directly improve recall, ranking precision, and answer grounding while remaining measurable with a small retrieval eval set.
