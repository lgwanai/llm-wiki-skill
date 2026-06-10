# llm-wiki RAGAS Black-Box Evaluation Report

**Generated**: 2026-06-10T17:44:29.930256+00:00
**Pipeline**: compile_v2 → embed → search → synthesize
**Test Cases**: 19
**Domains**: tech, business, chinese

---

## Overall Scores vs Industry Baselines

| System | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------------|-----------------|-------------------|---------------|-------------------|
| **llm-wiki (this eval)** | 0.870 | 0.579 | 0.368 | 0.553 | 0.329 |
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
| tech | 7 | 0.943 | 0.643 | 0.571 | 0.457 | 0.429 |
| business | 6 | 0.816 | 0.667 | 0.333 | 0.633 | 0.250 |
| chinese | 5 | 0.821 | 0.400 | 0.160 | 0.600 | 0.250 |
| cross | 1 | 0.923 | 0.500 | 0.200 | 0.500 | 0.500 |

## Difficulty Breakdown

| Difficulty | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| easy | 7 | 0.821 | 0.643 | 0.314 | 0.729 | 0.464 |
| medium | 8 | 0.898 | 0.594 | 0.425 | 0.581 | 0.219 |
| hard | 4 | 0.897 | 0.438 | 0.350 | 0.188 | 0.312 |

## Query Type Breakdown

| Type | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| factual | 11 | 0.873 | 0.636 | 0.327 | 0.650 | 0.364 |
| synthesis | 5 | 0.838 | 0.500 | 0.400 | 0.420 | 0.250 |
| comparison | 2 | 1.000 | 0.500 | 0.500 | 0.125 | 0.375 |
| temporal | 1 | 0.727 | 0.500 | 0.400 | 1.000 | 0.250 |

## Latency

| Metric | Value |
|--------|-------|
| Mean search latency | 5.433s |
| P50 search latency | 5.953s |
| P95 search latency | 6.673s |
| Min search latency | 2.762s |
| Max search latency | 6.673s |

## Per-Case Results

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness | Pages | Search Latency |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|-------|---------------|
| tech-01 | tech | factual | easy | 1.00 | 0.50 | 0.60 | 0.50 | 0.75 | 5 | 5.51s |
| tech-02 | tech | factual | easy | 1.00 | 0.50 | 0.00 | 0.00 | 0.00 | 5 | 6.09s |
| tech-03 | tech | factual | easy | 1.00 | 0.75 | 0.60 | 0.60 | 0.50 | 5 | 6.14s |
| tech-04 | tech | synthesis | medium | 0.80 | 1.00 | 0.80 | 0.60 | 0.75 | 5 | 6.04s |
| tech-05 | tech | factual | medium | 1.00 | 0.50 | 0.20 | 0.25 | 0.25 | 5 | 4.47s |
| tech-06 | tech | synthesis | medium | 0.80 | 0.25 | 0.80 | 1.00 | 0.00 | 5 | 5.95s |
| tech-07 | tech | comparison | hard | 1.00 | 1.00 | 1.00 | 0.25 | 0.75 | 5 | 3.20s |
| business-01 | business | factual | easy | 1.00 | 1.00 | 0.20 | 1.00 | 1.00 | 5 | 4.53s |
| business-02 | business | factual | medium | 1.00 | 1.00 | 0.80 | 0.60 | 0.25 | 5 | 5.45s |
| business-03 | business | factual | medium | 1.00 | 0.75 | 0.20 | 0.20 | 0.00 | 5 | 6.43s |
| business-04 | business | temporal | medium | 0.73 | 0.50 | 0.40 | 1.00 | 0.25 | 5 | 2.76s |
| business-05 | business | factual | easy | 0.50 | 0.50 | 0.20 | 1.00 | 0.00 | 5 | 4.44s |
| business-06 | business | synthesis | hard | 0.67 | 0.25 | 0.20 | 0.00 | 0.00 | 5 | 6.27s |
| chinese-01 | chinese | factual | easy | 1.00 | 1.00 | 0.40 | 1.00 | 1.00 | 5 | 6.22s |
| chinese-02 | chinese | factual | easy | 0.25 | 0.25 | 0.20 | 1.00 | 0.00 | 5 | 6.44s |
| chinese-03 | chinese | factual | medium | 0.86 | 0.25 | 0.20 | 1.00 | 0.25 | 5 | 6.36s |
| chinese-04 | chinese | synthesis | medium | 1.00 | 0.50 | 0.00 | 0.00 | 0.00 | 5 | 5.34s |
| chinese-05 | chinese | comparison | hard | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 5 | 4.92s |
| cross-01 | cross | synthesis | hard | 0.92 | 0.50 | 0.20 | 0.50 | 0.50 | 5 | 6.67s |

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
*Report generated by benchmark_ragas.py — 2026-06-10T17:44:29.930256+00:00*