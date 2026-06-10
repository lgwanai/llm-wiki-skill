# SciFact qrels50 Model Comparison

Coverage: 61/300 qrels queries, 146 mapped BEIR docs. This is a compiled subset, not full BEIR leaderboard.

| Model | Streams | NDCG@10 | Recall@10 | MRR@10 | Eval sec | Result |
|---|---|---:|---:|---:|---:|---|
| Qwen3-8B | vector | 0.9550 | 1.0000 | 0.9399 | 196.2 | `evals/beir_results_compiled_cache_scifact_qwen8b_qrels50_vectorstream.json` |
| Qwen3-8B | bm25,vector fixed | 0.9543 | 1.0000 | 0.9391 | 176.2 | `evals/beir_results_scifact_qrels50_qwen3_8b_bm25_vector_hybrid_fixed.json` |
| Qwen3-0.6B | vector | 0.9243 | 0.9803 | 0.9071 | 43.1 | `evals/beir_results_scifact_qrels50_qwen3_0.6b_vector.json` |
| Qwen3-0.6B | bm25,vector fixed | 0.9330 | 0.9803 | 0.9186 | 51.4 | `evals/beir_results_scifact_qrels50_qwen3_0.6b_bm25_vector_hybrid_fixed.json` |
| Jina-v5-small-MLX | vector | 0.9420 | 0.9934 | 0.9290 | 27.6 | `evals/beir_results_scifact_qrels50_jina_v5_small_mlx_vector.json` |
| Jina-v5-small-MLX | bm25,vector fixed | 0.9504 | 0.9934 | 0.9399 | 31.4 | `evals/beir_results_scifact_qrels50_jina_v5_small_mlx_bm25_vector_hybrid_fixed.json` |
| llm-wiki BM25 | bm25 | 0.8866 | 0.9320 | 0.8844 | 2.3 | `evals/beir_results_compiled_cache_scifact_qwen8b_qrels50_bm25stream.json` |
| Original docs BM25 | bm25 | 0.9139 | 0.9672 | 0.8972 | 0.0 | `evals/beir_results_scifact_qrels50_bm25_subset.json` |

## Findings

- Best effectiveness remains Qwen3-8B vector/hybrid fixed; Jina MLX is very close with much lower wall time on MPS.
- Qwen3-0.6B is materially faster than 8B and remains above original-doc BM25 on NDCG@10 in vector mode.
- The previous bm25,vector path was defective: BM25 dominated rerank, causing all embedding models to produce identical hybrid scores. Fixed weighted RRF restores model sensitivity.
- Full BEIR comparison still requires compiling/evaluating NFCorpus and FiQA, not just SciFact subset.
