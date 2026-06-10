# Optimization Roadmap — Closing the Gap with Industry Leaders

Based on RAGAS black-box evaluation (19 test cases, 3 domains). Current scores vs targets:

| Metric | llm-wiki | RAGFlow (est.) | GraphRAG | **Gap** | **Target** |
|--------|----------|---------------|----------|---------|------------|
| Faithfulness | 0.85 | 0.86 | 0.88 | -0.01~0.03 | 0.88 |
| Answer Relevance | 0.79 | 0.84 | 0.87 | -0.05~0.08 | 0.85 |
| **Context Precision** | **0.45** | 0.80 | 0.82 | **-0.35** | 0.75 |
| **Context Recall** | **0.66** | 0.79 | 0.84 | **-0.13** | 0.80 |
| Answer Correctness | 0.34 | 0.80 | 0.83 | -0.46 | 0.70 |

Two critical gaps: **Context Precision** and **Context Recall**. Faithfulness is already competitive.

---

## Priority 1: Context Precision (0.45 → 0.75)

**Root Cause**: 142 wiki pages from 12 source docs. RRF fusion returns many tangentially-related pages. No intelligent re-ranking after fusion.

### 1.1 Entity-Type-Weighted Reranking (Quick Win, ~2h)

Current reranker (`rerank_results` in `query.py`) only considers stream source and lexical overlap. It should also weight by entity type relevance:

```python
# Entity type weights — prioritize content-carrying types
TYPE_WEIGHTS = {
    "concept": 1.2, "technique": 1.2, "model": 1.1,
    "framework": 1.0, "benchmark": 0.9, "paper": 0.8,
    "entity": 0.9, "event": 0.8, "process": 0.9,
}
# Match query intent → entity type preference
INTENT_TYPE_PREFERENCE = {
    "fact": ["concept", "technique", "model"],
    "relationship": ["technique", "concept", "model"],
    "comparison": ["model", "framework", "benchmark"],
    "ledger_filter": ["entity", "event"],
}
```

**Expected impact**: Precision +0.10~0.15

### 1.2 Graph-Enhanced Reranking (Medium, ~4h)

Use the knowledge graph to boost pages that are connected to already-high-ranked pages:

```python
def graph_boost(results, graph, top_n=3):
    """Boost pages connected to top-ranked pages via graph edges."""
    top_ids = {r["id"] for r in results[:top_n]}
    for r in results[top_n:]:
        # Check graph edges connecting to top results
        connections = graph.count_connections(r["id"], top_ids)
        r["score"] *= (1 + 0.1 * connections)  # +10% per connection
```

**Expected impact**: Precision +0.05~0.10

### 1.3 Cross-Encoder Reranker (High Impact, ~8h)

After RRF fusion returns top-20 candidates, use a cross-encoder to re-rank. This is the key technique that takes "RAG + Reranker" from 0.65 to 0.78 precision:

```
RRF Top-20 → Cross-Encoder (BGE-Reranker-v2 or MiniLM) → Top-5
```

Options:
- **Lightweight**: `BAAI/bge-reranker-base` (278M params, ~50ms per pair)
- **High quality**: `BAAI/bge-reranker-v2-m3` (568M params, multilingual)

```bash
pip install FlagEmbedding
```

```python
from FlagEmbedding import FlagReranker
reranker = FlagReranker('BAAI/bge-reranker-base', use_fp16=True)

def cross_encode_rerank(query, candidates):
    pairs = [[query, ctx["text"][:2000]] for ctx in candidates]
    scores = reranker.compute_score(pairs)
    for c, s in zip(candidates, scores):
        c["cross_score"] = float(s)
    candidates.sort(key=lambda x: -x.get("cross_score", 0))
    return candidates[:5]
```

**Expected impact**: Precision +0.15~0.25, reaching 0.70~0.75

---

## Priority 2: Context Recall (0.66 → 0.80)

**Root Cause**: Missing relevant documents. Lexical query variants are insufficient for semantic recall.

### 2.1 LLM Query Expansion (High Impact, ~6h)

Replace the current lexical-only `rewrite_query` with LLM-based expansion:

```python
def llm_expand_query(query, plan):
    """Use LLM to generate semantic query variants."""
    prompt = f"""Generate 3 search queries to find information about:
"{query}"
Intent: {plan["intent"]}
Output one query per line. Include synonyms, related terms, and decompositions."""
    
    variants = call_llm(prompt).strip().split("\n")
    return [v.strip() for v in variants if v.strip()][:5]
```

Example:
```
Input: "How does DeepSeek-V4 reduce inference memory?"
Output:
  "DeepSeek-V4 MLA KV-cache compression mechanism"
  "DeepSeekMoE expert routing active parameters per token"
  "multi-head latent attention memory reduction inference"
```

**Expected impact**: Recall +0.08~0.12

### 2.2 Increase Retrieval Depth (Quick Win, ~1h)

Current RRF merges top-K from each stream (limit * 2). Increase to limit * 4 before fusion, then rerank to final top-K:

```python
# search_wiki optimization
for stream in streams:
    results = stream_search(query, limit=limit * 4)  # was limit * 2
```

**Expected impact**: Recall +0.03~0.05

### 2.3 Graph Traversal Recall (Medium, ~4h)

For relationship queries, traverse entity graph 2-hop to add connected pages:

```python
def graph_aware_recall(query, graph, top_pages):
    """Add pages connected to top results via graph edges."""
    expanded = set()
    for page in top_pages[:3]:
        neighbors = graph.get_neighbors(page["id"], depth=2)
        expanded.update(neighbors)
    return list(expanded)
```

**Expected impact**: Recall +0.03~0.05 (especially for synthesis/cross-domain queries)

---

## Priority 3: Chinese Search (Precision 0.16 → 0.50)

**Root Cause**: Chinese entity naming mismatch. Entities have mixed pinyin-chinese IDs like `damoxing-大模型部署方案`, but search queries use pure Chinese. Jieba tokenization doesn't match these IDs.

### 3.1 Chinese Entity Alias Index (Quick Win, ~2h)

Add Chinese entity names to the metadata index as search aliases:

```python
# In compile_v2: when creating Chinese entity, add name as alias
entity_aliases = [entity["name"]]  # "大模型部署方案"
entity_aliases.append(entity["name"].replace(" ", ""))  # normalize
# Store in metadata index for metadata_search to find
```

### 3.2 Jieba Custom Dictionary (Quick Win, ~1h)

Add all entity names to jieba's dictionary:

```python
import jieba
for entity_name in chinese_entities:
    jieba.add_word(entity_name)
```

### 3.3 Chinese Query LLM Expansion (Medium, ~3h)

```python
def expand_chinese_query(query):
    prompt = f"""将以下搜索查询扩展为3个不同的搜索词，包含同义词和相关术语：
"{query}"
每行输出一个查询："""
    variants = call_llm(prompt).strip().split("\n")
    return [v for v in variants if v.strip()][:3]
```

**Expected combined impact**: Chinese Precision 0.16 → 0.45~0.55

---

## Priority 4: Answer Correctness (0.34 → 0.70)

**Root Cause**: Two factors — (a) judge LLM strictness causing false zeros, (b) synthesis LLM sometimes produces incomplete answers.

### 4.1 Improved Context Presentation (Quick Win, ~2h)

Format retrieved pages for the LLM with clear structure:

```python
def format_context_for_synthesis(page):
    return f"""## {page['name']} ({page['type']})
**Key Details**: {page.get('summary', '')}
**Relationships**: {', '.join(page.get('relationships', []))}
{page['content'][:1500]}
---
"""
```

### 4.2 Structured Answer Template (Quick Win, ~1h)

Guide the LLM to produce more complete answers:

```python
SYNTHESIS_PROMPT = """Answer the question using the provided wiki pages.
Structure your answer as:
1. **Direct Answer**: 2-3 sentence summary
2. **Key Details**: Bullet points with specific facts
3. **Sources**: [[page-id]] for each claim
If a claim cannot be verified from the provided pages, mark it as [uncertain]."""
```

### 4.3 Chain-of-Thought Synthesis (Medium, ~4h)

For complex queries, do two-pass synthesis:

```
Pass 1: Extract relevant facts from each context
Pass 2: Synthesize answer from extracted facts
```

**Expected impact**: Correctness +0.15~0.25 (partly by reducing judge false-zeros)

---

## Implementation Sequence

| Phase | Tasks | Effort | Expected Precision | Expected Recall |
|-------|-------|--------|-------------------|----------------|
| **Phase 1** (this week) | 1.1 Type-weighted rerank + 2.2 Depth increase + 3.1 Chinese alias | ~5h | 0.55 | 0.72 |
| **Phase 2** (next week) | 1.3 Cross-encoder + 2.1 LLM query expansion | ~14h | 0.70 | 0.78 |
| **Phase 3** (week 3) | 1.2 Graph rerank + 2.3 Graph recall + 3.3 Chinese LLM expansion | ~11h | 0.73 | 0.82 |
| **Phase 4** (week 4) | 4.1-4.3 Answer synthesis improvements | ~7h | — | — |

**Total**: ~37h to close the gap from 0.45/0.66 to 0.73/0.82.

---

## What NOT to Optimize

Based on the evaluation data, these are NOT worth optimizing:

- ❌ **Embedding model swapping** (Qwen→BGE→Jina): Faithfulness is already 0.85. Embedding changes affect retrieval recall marginally but won't fix the precision/recall gap.
- ❌ **BEIR benchmarks**: Already proven that component-level testing doesn't reflect product quality.
- ❌ **More test documents**: 12 docs already produce 142 wiki pages — the precision issue is ranking, not coverage.
- ❌ **Chunking strategy tweaks**: Current heading-aware chunking works well (tech domain precision 0.63). The problem is post-retrieval ranking.

## Success Metrics

Re-run `python scripts/benchmark_ragas.py` after each phase. Target:

| Metric | Current | Phase 1 | Phase 2 | Phase 3 |
|--------|---------|---------|---------|---------|
| Context Precision | 0.45 | 0.55 | 0.70 | 0.73+ |
| Context Recall | 0.66 | 0.72 | 0.78 | 0.82+ |
| Chinese Precision | 0.16 | 0.35 | 0.45 | 0.50+ |
| Answer Correctness | 0.34 | 0.45 | 0.55 | 0.65+ |
