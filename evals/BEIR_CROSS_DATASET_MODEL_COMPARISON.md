# BEIR Cross-Dataset Model Comparison

Generated: 2026-06-10

Scope: retrieval-only benchmark over already prepared `.wiki` content. Compile is skipped in all runs (`compiled-cache -> search`).

Important caveat: SciFact uses the existing compiled cache subset. NFCorpus and FiQA use qrels-centered direct-wiki subsets produced from BEIR documents, not LLM semantic compile. These results are suitable for local model/pipeline comparison, but they are not full BEIR leaderboard scores.

| Dataset | Model | Qrels coverage | Wiki pages | NDCG@10 | Recall@10 | MRR@10 | Eval time | Result file |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| SciFact qrels50 compiled | Qwen3-Embedding-8B | 61/300 (20.3%) | 1779 | 0.9550 | 1.0000 | 0.9399 | 196.2s | `evals/beir_results_compiled_cache_scifact_qwen8b_qrels50_vectorstream.json` |
| SciFact qrels50 compiled | Qwen3-Embedding-0.6B | 61/300 (20.3%) | 1779 | 0.9243 | 0.9803 | 0.9071 | 43.1s | `evals/beir_results_scifact_qrels50_qwen3_0.6b_vector.json` |
| SciFact qrels50 compiled | Jina v5 small MLX | 61/300 (20.3%) | 1779 | 0.9420 | 0.9934 | 0.9290 | 27.6s | `evals/beir_results_scifact_qrels50_jina_v5_small_mlx_vector.json` |
| NFCorpus qrels25 direct-wiki | Qwen3-Embedding-8B | 205/323 (63.5%) | 592 | 0.3755 | 0.2119 | 0.5408 | 190.3s | `evals/beir_results_nfcorpus_qrels25_qwen3_8b_vector.json` |
| NFCorpus qrels25 direct-wiki | Qwen3-Embedding-0.6B | 205/323 (63.5%) | 592 | 0.3424 | 0.1931 | 0.5178 | 54.0s | `evals/beir_results_nfcorpus_qrels25_qwen3_0.6b_vector.json` |
| NFCorpus qrels25 direct-wiki | Jina v5 small MLX | 205/323 (63.5%) | 592 | 0.3912 | 0.2387 | 0.5604 | 35.2s | `evals/beir_results_nfcorpus_qrels25_jina_v5_small_mlx_vector.json` |
| FiQA qrels100 direct-wiki | Qwen3-Embedding-8B | 100/648 (15.4%) | 226 | 0.9216 | 0.9708 | 0.9273 | 45.5s | `evals/beir_results_fiqa_qrels100_qwen3_8b_vector.json` |
| FiQA qrels100 direct-wiki | Qwen3-Embedding-0.6B | 100/648 (15.4%) | 226 | 0.8473 | 0.9040 | 0.8926 | 13.6s | `evals/beir_results_fiqa_qrels100_qwen3_0.6b_vector.json` |
| FiQA qrels100 direct-wiki | Jina v5 small MLX | 100/648 (15.4%) | 226 | 0.8990 | 0.9448 | 0.9231 | 7.5s | `evals/beir_results_fiqa_qrels100_jina_v5_small_mlx_vector.json` |

## Best Model By Dataset

- SciFact qrels50 compiled: Qwen3-Embedding-8B (NDCG@10=0.9550, Recall@10=1.0000, MRR@10=0.9399)
- NFCorpus qrels25 direct-wiki: Jina v5 small MLX (NDCG@10=0.3912, Recall@10=0.2387, MRR@10=0.5604)
- FiQA qrels100 direct-wiki: Qwen3-Embedding-8B (NDCG@10=0.9216, Recall@10=0.9708, MRR@10=0.9273)

## Interpretation

- Qwen3-Embedding-8B remains the strongest model on SciFact and FiQA quality metrics, but it is substantially slower per query on MPS.
- Jina v5 small MLX is the best NFCorpus run and is much faster than 8B, making it the best latency/quality tradeoff in these local tests.
- Qwen3-Embedding-0.6B is consistently behind the other two models, but provides a low-cost baseline that still keeps reasonable recall on simpler subsets.
- NFCorpus exposes the main remaining retrieval gap: biomedical queries have many relevant documents per query, so page-level dense retrieval needs chunk-level indexing, query expansion, or hybrid reranking to close Recall@10.

## Product Comparison Note

The included public baseline fields in each JSON are reference values for full BEIR-style tasks. Because these runs evaluate subset caches with filtered qrels, especially qrels-centered FiQA, they must not be reported as beating public SOTA. The fair claim is: within the same compiled-cache/direct-wiki subset, the fixed retrieval pipeline now supports repeatable model-to-model comparison across SciFact, NFCorpus, and FiQA.
