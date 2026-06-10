# BEIR Retrieval Benchmark Report

Generated: 2026-06-10 01:45:10 UTC

## Summary

The table below compares this system's retrieval performance against
published baselines on standard BEIR datasets.

| Dataset | Method | NDCG@10 | Recall@10 | MRR@10 | vs BM25 Baseline | vs SOTA |
|---------|--------|---------|-----------|--------|-----------------|---------|
| FiQA-2018 | **llm-wiki (compiled subset 100/648)** | 0.8990 | 0.9448 | 0.9231 | n/a (subset) | n/a (subset) |
| FiQA-2018 | _BM25 (BEIR)_ | 0.2360 | 0.5390 | 0.3890 | — | — |
| FiQA-2018 | _Dense-BGE-base_ | 0.3550 | 0.6850 | 0.5200 | — | — |
| FiQA-2018 | _Dense-BGE-large_ | 0.3750 | 0.7080 | 0.5450 | — | — |
| FiQA-2018 | _Hybrid (BM25+BGE)_ | 0.3800 | 0.7150 | 0.5580 | — | — |
| FiQA-2018 | _SOTA (MTEB best)_ | 0.4300 | 0.7600 | 0.6100 | — | — |


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

- Embedding model: jinaai/jina-embeddings-v5-text-small-retrieval-mlx
- Embedding mode: local
- llm-wiki streams: vector
- BM25: k1=1.5, b=0.75, Porter stemming + jieba for CJK
- Hybrid: RRF fusion (k=60)