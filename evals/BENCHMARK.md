# BEIR Retrieval Benchmark Report

Generated: 2026-06-09 15:08:39 UTC

## Summary

The table below compares this system's retrieval performance against
published baselines on standard BEIR datasets.

| Dataset | Method | NDCG@10 | Recall@10 | MRR@10 | vs BM25 Baseline | vs SOTA |
|---------|--------|---------|-----------|--------|-----------------|---------|
| SciFact | **llm-wiki** | 0.9077 | 1.0000 | 0.8750 | +36.5% | +17.9% |
| SciFact | _BM25 (BEIR)_ | 0.6650 | 0.9070 | 0.5870 | — | — |
| SciFact | _Dense-BGE-base_ | 0.7250 | 0.9400 | 0.6450 | — | — |
| SciFact | _Dense-BGE-large_ | 0.7400 | 0.9480 | 0.6600 | — | — |
| SciFact | _Hybrid (BM25+BGE)_ | 0.7400 | 0.9500 | 0.6650 | — | — |
| SciFact | _SOTA (MTEB best)_ | 0.7700 | 0.9580 | 0.6980 | — | — |


## Interpretation

- **NDCG@10**: Normalized Discounted Cumulative Gain — measures ranking quality (higher = better ranking).
- **Recall@10**: Fraction of relevant documents found in top 10 results.
- **MRR@10**: Mean Reciprocal Rank — average position of the first relevant document.
- **llm-wiki**: The project's real `query.search_wiki` pipeline over BEIR corpus converted to wiki pages.
- **BM25 baseline**: Independent pure keyword search (sparse retrieval).
- **Dense-BGE**: Semantic search using BGE embedding models.
- **Hybrid**: BM25 + Dense fused via Reciprocal Rank Fusion.
- **SOTA**: Best published result on MTEB leaderboard for this dataset.

## Data Sources

- BEIR paper: Thakur et al., 2021 ([arxiv.org/abs/2104.08663](https://arxiv.org/abs/2104.08663))
- BGE paper: Xiao et al., 2023 ([arxiv.org/abs/2309.07597](https://arxiv.org/abs/2309.07597))
- MTEB Leaderboard: [huggingface.co/spaces/mteb/leaderboard](https://huggingface.co/spaces/mteb/leaderboard)

## System Configuration

- Embedding model: Qwen/Qwen3-Embedding-8B
- Embedding mode: local
- llm-wiki streams: metadata,chunk,bm25,vector,graph
- BM25: k1=1.5, b=0.75, Porter stemming + jieba for CJK
- Hybrid: RRF fusion (k=60)