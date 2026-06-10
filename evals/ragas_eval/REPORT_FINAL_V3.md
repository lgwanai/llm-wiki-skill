# llm-wiki RAGAS Black-Box Evaluation Report

**Generated**: 2026-06-10T18:27:15.998910+00:00
**Pipeline**: compile_v2 → embed → search → synthesize
**Test Cases**: 19
**Domains**: tech, business, chinese

---

## Overall Scores vs Industry Baselines

| System | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------------|-----------------|-------------------|---------------|-------------------|
| **llm-wiki (this eval)** | 0.782 | 0.671 | 0.442 | 0.662 | 0.329 |
| Naive RAG (chunk + embed + LLM) | 0.720 | 0.780 | 0.650 | 0.680 | 0.650 |
| RAG + Reranker | 0.830 | 0.850 | 0.780 | 0.760 | 0.780 |
| GraphRAG (Microsoft) | 0.880 | 0.870 | 0.820 | 0.840 | 0.830 |
| RAGFlow (estimated) | 0.860 | 0.840 | 0.800 | 0.790 | 0.800 |

> Baseline scores are from published literature (RAGAS paper, RGB benchmark, Microsoft GraphRAG paper).
> RAGFlow scores are estimated from their public benchmark reports.
> All scores use LLM-as-judge methodology aligned with the RAGAS framework.

---

## llm-wiki vs Industry Baseline — Radar View

## Domain Breakdown

| Domain | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| tech | 7 | 0.904 | 0.821 | 0.514 | 0.693 | 0.536 |
| business | 6 | 0.582 | 0.708 | 0.567 | 0.733 | 0.208 |
| chinese | 5 | 0.850 | 0.500 | 0.240 | 0.600 | 0.200 |
| cross | 1 | 0.778 | 0.250 | 0.200 | 0.333 | 0.250 |

## Difficulty Breakdown

| Difficulty | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| easy | 7 | 0.665 | 0.750 | 0.371 | 0.893 | 0.357 |
| medium | 8 | 0.829 | 0.656 | 0.500 | 0.644 | 0.312 |
| hard | 4 | 0.891 | 0.562 | 0.450 | 0.296 | 0.312 |

## Query Type Breakdown

| Type | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| factual | 11 | 0.729 | 0.705 | 0.418 | 0.800 | 0.318 |
| synthesis | 5 | 0.833 | 0.600 | 0.480 | 0.507 | 0.400 |
| comparison | 2 | 1.000 | 0.500 | 0.400 | 0.125 | 0.250 |
| temporal | 1 | 0.667 | 1.000 | 0.600 | 1.000 | 0.250 |

## Latency

| Metric | Value |
|--------|-------|
| Mean search latency | 10.364s |
| P50 search latency | 10.660s |
| P95 search latency | 14.934s |
| Min search latency | 6.538s |
| Max search latency | 14.934s |

## Per-Case Results

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness | Pages | Search Latency |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|-------|---------------|
| tech-01 | tech | factual | easy | 1.00 | 0.50 | 0.60 | 0.25 | 0.25 | 10 | 14.93s |
| tech-02 | tech | factual | easy | 1.00 | 1.00 | 0.20 | 1.00 | 0.75 | 10 | 11.12s |
| tech-03 | tech | factual | easy | 0.73 | 0.75 | 0.40 | 1.00 | 0.50 | 10 | 11.35s |
| tech-04 | tech | synthesis | medium | 1.00 | 1.00 | 0.60 | 0.60 | 0.75 | 10 | 10.56s |
| tech-05 | tech | factual | medium | 1.00 | 1.00 | 0.60 | 0.75 | 0.50 | 10 | 10.88s |
| tech-06 | tech | synthesis | medium | 0.60 | 0.50 | 0.40 | 1.00 | 0.50 | 10 | 6.54s |
| tech-07 | tech | comparison | hard | 1.00 | 1.00 | 0.80 | 0.25 | 0.50 | 10 | 10.71s |
| business-01 | business | factual | easy | 0.38 | 0.25 | 0.60 | 1.00 | 0.00 | 10 | 8.85s |
| business-02 | business | factual | medium | 0.59 | 1.00 | 0.80 | 0.40 | 0.50 | 10 | 8.22s |
| business-03 | business | factual | medium | 0.78 | 0.25 | 0.40 | 0.40 | 0.00 | 10 | 10.87s |
| business-04 | business | temporal | medium | 0.67 | 1.00 | 0.60 | 1.00 | 0.25 | 10 | 9.36s |
| business-05 | business | factual | easy | 0.30 | 0.75 | 0.20 | 1.00 | 0.00 | 10 | 11.02s |
| business-06 | business | synthesis | hard | 0.79 | 1.00 | 0.80 | 0.60 | 0.50 | 10 | 10.66s |
| chinese-01 | chinese | factual | easy | 1.00 | 1.00 | 0.40 | 1.00 | 1.00 | 10 | 10.41s |
| chinese-02 | chinese | factual | easy | 0.25 | 1.00 | 0.20 | 1.00 | 0.00 | 10 | 9.21s |
| chinese-03 | chinese | factual | medium | 1.00 | 0.25 | 0.20 | 1.00 | 0.00 | 10 | 11.31s |
| chinese-04 | chinese | synthesis | medium | 1.00 | 0.25 | 0.40 | 0.00 | 0.00 | 10 | 11.34s |
| chinese-05 | chinese | comparison | hard | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 10 | 9.58s |
| cross-01 | cross | synthesis | hard | 0.78 | 0.25 | 0.20 | 0.33 | 0.25 | 10 | 10.01s |

---

## Interpretation Guide

### What These Scores Mean

- **Faithfulness** (0-1): Higher = less hallucination. Measures whether claims in the answer are supported by retrieved contexts. Score of 0.85 means 85% of claims are grounded.
- **Answer Relevance** (0-1): Higher = more on-topic. Measures whether the answer addresses the question. Low scores suggest the system is retrieving wrong contexts or generating off-topic responses.
- **Context Precision** (0-1): Higher = better ranking. Measures whether relevant documents appear at the top. Position-weighted (rank 1 counts more than rank 5).
- **Context Recall** (0-1): Higher = more complete retrieval. Measures whether the retrieved contexts collectively cover the ground truth information.
- **Answer Correctness** (0-1): Higher = more factually accurate. Direct LLM comparison of generated answer against ground truth.

### How This Differs From BEIR Benchmarks

| Aspect | BEIR (benchmark_beir.py) | RAGAS (this benchmark) |
|--------|-------------------------|------------------------|
| What it tests | BM25/Dense retriever in isolation | Complete product pipeline |
| User perspective | Tests a component no user sees | Tests what the user actually experiences |
| Knowledge ingestion | Documents → direct index (no compile) | Documents → compile_v2 → entity extraction → graph → index |
| Answer synthesis | Not tested | Tested: search_wiki → synthesize_answer |
| Comparison target | Embedding models (BGE, Qwen) | RAG products (RAGFlow, GraphRAG) |
| Hallucination check | Not measured | Measured via faithfulness score |

### Limitations

- Test dataset is synthetic and relatively small (12 docs, 19 test cases). Scores will shift with larger-scale testing.
- LLM-as-judge scores have inherent variance (±0.05-0.10). Run multiple times for confidence intervals.
- Industry baseline scores are from published papers, not from running the exact same test set — they indicate approximate capability levels.
- The `--no-compile` fast path skips entity extraction and graph building, which reduces the pipeline's differentiating capabilities vs naive RAG.

### Sources

- RAGAS: Es et al., "RAGAS: Automated Evaluation of Retrieval Augmented Generation" (2024)
- RGB: Chen et al., "Benchmarking Large Language Models in Retrieval-Augmented Generation" (2024)
- GraphRAG: Edge et al., "From Local to Global: A Graph RAG Approach to Query-Focused Summarization" (2024)
- RAGFlow: Public benchmarks from https://github.com/infiniflow/ragflow

---
*Report generated by benchmark_ragas.py — 2026-06-10T18:27:15.998910+00:00*