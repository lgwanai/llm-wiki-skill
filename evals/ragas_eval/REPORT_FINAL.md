# llm-wiki RAGAS Black-Box Evaluation Report

**Generated**: 2026-06-10T09:01:53.064534+00:00
**Pipeline**: compile_v2 → embed → search → synthesize
**Test Cases**: 19
**Domains**: tech, business, chinese

---

## Overall Scores vs Industry Baselines

| System | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------------|-----------------|-------------------|---------------|-------------------|
| **llm-wiki (this eval)** | 0.332 | 0.434 | 0.442 | 0.772 | 0.132 |
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
| tech | 7 | 0.349 | 0.357 | 0.343 | 0.571 | 0.179 |
| business | 6 | 0.323 | 0.542 | 0.567 | 0.889 | 0.208 |
| chinese | 5 | 0.224 | 0.300 | 0.480 | 1.000 | 0.000 |
| cross | 1 | 0.800 | 1.000 | 0.200 | 0.333 | 0.000 |

## Difficulty Breakdown

| Difficulty | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| easy | 7 | 0.261 | 0.429 | 0.343 | 0.779 | 0.143 |
| medium | 8 | 0.298 | 0.438 | 0.525 | 0.798 | 0.125 |
| hard | 4 | 0.525 | 0.438 | 0.450 | 0.708 | 0.125 |

## Query Type Breakdown

| Type | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| factual | 11 | 0.254 | 0.341 | 0.382 | 0.730 | 0.091 |
| synthesis | 5 | 0.437 | 0.600 | 0.480 | 0.827 | 0.250 |
| comparison | 2 | 0.539 | 0.250 | 0.600 | 0.750 | 0.125 |
| temporal | 1 | 0.250 | 1.000 | 0.600 | 1.000 | 0.000 |

## Latency

| Metric | Value |
|--------|-------|
| Mean search latency | 2.627s |
| P50 search latency | 2.316s |
| P95 search latency | 5.962s |
| Min search latency | 1.149s |
| Max search latency | 5.962s |

## Per-Case Results

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness | Pages | Search Latency |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|-------|---------------|
| tech-01 | tech | factual | easy | 0.00 | 0.00 | 0.20 | 0.25 | 0.00 | 5 | 3.33s |
| tech-02 | tech | factual | easy | 0.33 | 0.50 | 0.40 | 1.00 | 0.00 | 5 | 2.02s |
| tech-03 | tech | factual | easy | 0.09 | 0.00 | 0.00 | 0.20 | 0.00 | 5 | 2.23s |
| tech-04 | tech | synthesis | medium | 0.31 | 0.75 | 0.80 | 0.80 | 0.25 | 5 | 2.10s |
| tech-05 | tech | factual | medium | 0.00 | 0.00 | 0.20 | 0.25 | 0.00 | 5 | 2.69s |
| tech-06 | tech | synthesis | medium | 0.86 | 1.00 | 0.40 | 1.00 | 0.75 | 5 | 2.29s |
| tech-07 | tech | comparison | hard | 0.86 | 0.25 | 0.40 | 0.50 | 0.25 | 5 | 2.08s |
| business-01 | business | factual | easy | 1.00 | 1.00 | 0.60 | 1.00 | 1.00 | 5 | 2.12s |
| business-02 | business | factual | medium | 0.29 | 0.25 | 0.40 | 0.33 | 0.00 | 5 | 2.20s |
| business-03 | business | factual | medium | 0.18 | 0.25 | 0.80 | 1.00 | 0.00 | 5 | 2.82s |
| business-04 | business | temporal | medium | 0.25 | 1.00 | 0.60 | 1.00 | 0.00 | 5 | 2.84s |
| business-05 | business | factual | easy | 0.00 | 0.50 | 0.60 | 1.00 | 0.00 | 5 | 2.24s |
| business-06 | business | synthesis | hard | 0.22 | 0.25 | 0.40 | 1.00 | 0.25 | 5 | 2.32s |
| chinese-01 | chinese | factual | easy | 0.00 | 0.00 | 0.40 | 1.00 | 0.00 | 5 | 2.80s |
| chinese-02 | chinese | factual | easy | 0.40 | 1.00 | 0.20 | 1.00 | 0.00 | 5 | 2.78s |
| chinese-03 | chinese | factual | medium | 0.50 | 0.25 | 0.40 | 1.00 | 0.00 | 5 | 2.86s |
| chinese-04 | chinese | synthesis | medium | 0.00 | 0.00 | 0.60 | 1.00 | 0.00 | 5 | 3.09s |
| chinese-05 | chinese | comparison | hard | 0.22 | 0.25 | 0.80 | 1.00 | 0.00 | 5 | 1.15s |
| cross-01 | cross | synthesis | hard | 0.80 | 1.00 | 0.20 | 0.33 | 0.00 | 5 | 5.96s |

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
*Report generated by benchmark_ragas.py — 2026-06-10T09:01:53.064534+00:00*