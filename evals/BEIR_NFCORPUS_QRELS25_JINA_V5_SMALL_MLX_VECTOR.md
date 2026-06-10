# BEIR Retrieval Benchmark Report

Generated: 2026-06-10 01:43:33 UTC

## Summary

The table below compares this system's retrieval performance against
published baselines on standard BEIR datasets.

| Dataset | Method | NDCG@10 | Recall@10 | MRR@10 | vs BM25 Baseline | vs SOTA |
|---------|--------|---------|-----------|--------|-----------------|---------|
| NFCorpus | **llm-wiki (compiled subset 205/323)** | 0.3912 | 0.2387 | 0.5604 | n/a (subset) | n/a (subset) |
| NFCorpus | _BM25 (BEIR)_ | 0.3250 | 0.1930 | 0.3130 | — | — |
| NFCorpus | _Dense-BGE-base_ | 0.3520 | 0.2190 | 0.3540 | — | — |
| NFCorpus | _Dense-BGE-large_ | 0.3650 | 0.2280 | 0.3700 | — | — |
| NFCorpus | _Hybrid (BM25+BGE)_ | 0.3700 | 0.2350 | 0.3780 | — | — |
| NFCorpus | _SOTA (MTEB best)_ | 0.3900 | 0.2500 | 0.4050 | — | — |


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