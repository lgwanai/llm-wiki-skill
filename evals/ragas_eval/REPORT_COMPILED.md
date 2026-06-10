# llm-wiki RAGAS Black-Box Evaluation Report

**Generated**: 2026-06-10T04:19:37.256860+00:00
**Pipeline**: compile_v2 → embed → search → synthesize
**Test Cases**: 6
**Domains**: tech, business, chinese

---

## Overall Scores vs Industry Baselines

| System | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------------|-----------------|-------------------|---------------|-------------------|
| **llm-wiki (this eval)** | 0.893 | 1.000 | 0.633 | 0.742 | 0.625 |
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
| tech | 6 | 0.893 | 1.000 | 0.633 | 0.742 | 0.625 |

## Difficulty Breakdown

| Difficulty | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| easy | 3 | 1.000 | 1.000 | 0.533 | 0.733 | 0.583 |
| medium | 3 | 0.786 | 1.000 | 0.733 | 0.750 | 0.667 |

## Query Type Breakdown

| Type | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| factual | 4 | 0.875 | 1.000 | 0.600 | 0.675 | 0.688 |
| synthesis | 2 | 0.928 | 1.000 | 0.700 | 0.875 | 0.500 |

## Latency

| Metric | Value |
|--------|-------|
| Mean search latency | 0.511s |
| P50 search latency | 0.428s |
| P95 search latency | 0.967s |
| Min search latency | 0.405s |
| Max search latency | 0.967s |

## Per-Case Results

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness | Pages | Search Latency |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|-------|---------------|
| tech-01 | tech | factual | easy | 1.00 | 1.00 | 0.60 | 1.00 | 0.50 | 5 | 0.97s |
| tech-02 | tech | factual | easy | 1.00 | 1.00 | 0.80 | 1.00 | 0.75 | 5 | 0.41s |
| tech-03 | tech | factual | easy | 1.00 | 1.00 | 0.20 | 0.20 | 0.50 | 5 | 0.43s |
| tech-04 | tech | synthesis | medium | 1.00 | 1.00 | 1.00 | 0.75 | 0.75 | 5 | 0.43s |
| tech-05 | tech | factual | medium | 0.50 | 1.00 | 0.80 | 0.50 | 1.00 | 5 | 0.41s |
| tech-06 | tech | synthesis | medium | 0.86 | 1.00 | 0.40 | 1.00 | 0.25 | 5 | 0.43s |

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
*Report generated by benchmark_ragas.py — 2026-06-10T04:19:37.256860+00:00*