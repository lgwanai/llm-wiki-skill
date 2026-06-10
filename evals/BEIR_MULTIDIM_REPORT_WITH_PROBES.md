# Multi-Dimensional Retrieval Evaluation

Generated: 2026-06-09 17:45:24 UTC

## Verdict

Qwen 8B page-vector retrieval is currently the strongest tested path. Hybrid bm25,vector underperforms pure vector on the compiled subset, so fusion weighting should be treated as an optimization target. Coverage is materially better than the earlier 4-query run but remains a subset evaluation.

## Retrieval

| Method | Queries | NDCG@10 | Recall@10 | MRR@10 | Eval time |
|---|---:|---:|---:|---:|---:|
| llm_wiki_vector | 61 | 0.9550 | 1.0000 | 0.9399 | 196.2 |
| llm_wiki_bm25 | 61 | 0.8866 | 0.9320 | 0.8844 | 2.3 |
| llm_wiki_bm25_vector | 61 | 0.8834 | 0.9279 | 0.8844 | 199.0 |
| original_bm25_subset | 61 | 0.9139 | 0.9672 | 0.8972 | 0.0 |
| original_bm25_compiled_subset_recomputed | 61 | 0.9139 | 0.9672 | 0.8972 | 0.0098 |

## Coverage

- Corpus docs: 5183
- Compiled mapped docs: 146 (2.82%)
- Covered qrels queries: 61/300 (20.33%)
- Covered relevance labels: 74/339

## Index Health

- Page embeddings: 1797 items, 98.25% coverage
- Embedding model: Qwen/Qwen3-Embedding-8B
- Chunk embeddings: 0 items

## Compile Quality

- Page files: 1830
- Frontmatter parse failures: 0
- Audit contradictions: 20
- Pages per mapped doc mean/p95: 12.18 / 16

## Probes

- vector: sample=20, NDCG@10=0.9281, Recall@10=1.0, p50=3.1448s, p95=3.2646s
  - original: Recall@10=1.0, MRR@10=0.9042, top1_stability=1.0
  - lowercase: Recall@10=1.0, MRR@10=0.9042, top1_stability=1.0
  - no_punctuation: Recall@10=1.0, MRR@10=0.9042, top1_stability=0.95
  - truncated_65pct: Recall@10=0.9, MRR@10=0.6392, top1_stability=0.65
- bm25: sample=20, NDCG@10=0.8775, Recall@10=0.9, p50=0.0254s, p95=0.0398s
  - original: Recall@10=0.9, MRR@10=0.875, top1_stability=1.0
  - lowercase: Recall@10=0.9, MRR@10=0.875, top1_stability=1.0
  - no_punctuation: Recall@10=0.9, MRR@10=0.875, top1_stability=1.0
  - truncated_65pct: Recall@10=0.7, MRR@10=0.5392, top1_stability=0.55

## Limits

- This is still a compiled subset evaluation, not a full SciFact/BEIR leaderboard run.
- Vector latency reflects local Qwen/Qwen3-Embedding-8B on the current CPU environment.
- Chunk-vector evaluation is reported as index health unless chunk embeddings are explicitly generated.
