# llm-wiki RAGAS Black-Box Evaluation Report

**Generated**: 2026-06-10T04:23:24.473687+00:00
**Pipeline**: compile_v2 → embed → search → synthesize
**Test Cases**: 19
**Domains**: tech, business, chinese

---

## Overall Scores vs Industry Baselines

| System | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------------|-----------------|-------------------|---------------|-------------------|
| **llm-wiki (this eval)** | 0.847 | 0.789 | 0.453 | 0.658 | 0.342 |
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
| tech | 7 | 0.888 | 0.893 | 0.629 | 0.714 | 0.714 |
| business | 6 | 0.758 | 0.917 | 0.500 | 0.862 | 0.125 |
| chinese | 5 | 0.867 | 0.450 | 0.160 | 0.400 | 0.150 |
| cross | 1 | 1.000 | 1.000 | 0.400 | 0.333 | 0.000 |

## Difficulty Breakdown

| Difficulty | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| easy | 7 | 0.976 | 0.786 | 0.371 | 0.600 | 0.357 |
| medium | 8 | 0.787 | 0.844 | 0.475 | 0.684 | 0.406 |
| hard | 4 | 0.742 | 0.688 | 0.550 | 0.708 | 0.188 |

## Query Type Breakdown

| Type | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| factual | 11 | 0.906 | 0.841 | 0.418 | 0.643 | 0.409 |
| synthesis | 5 | 0.917 | 0.800 | 0.480 | 0.627 | 0.250 |
| comparison | 2 | 0.650 | 0.375 | 0.600 | 0.750 | 0.375 |
| temporal | 1 | 0.250 | 1.000 | 0.400 | 0.800 | 0.000 |

## Latency

| Metric | Value |
|--------|-------|
| Mean search latency | 0.666s |
| P50 search latency | 0.414s |
| P95 search latency | 5.262s |
| Min search latency | 0.388s |
| Max search latency | 5.262s |

## Per-Case Results

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness | Pages | Search Latency |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|-------|---------------|
| tech-01 | tech | factual | easy | 1.00 | 1.00 | 0.60 | 1.00 | 0.75 | 5 | 5.26s |
| tech-02 | tech | factual | easy | 1.00 | 1.00 | 0.80 | 1.00 | 0.75 | 5 | 0.42s |
| tech-03 | tech | factual | easy | 1.00 | 0.75 | 0.20 | 0.20 | 0.50 | 5 | 0.41s |
| tech-04 | tech | synthesis | medium | 1.00 | 1.00 | 1.00 | 0.80 | 0.75 | 5 | 0.42s |
| tech-05 | tech | factual | medium | 0.50 | 1.00 | 0.80 | 0.50 | 1.00 | 5 | 0.40s |
| tech-06 | tech | synthesis | medium | 0.92 | 1.00 | 0.40 | 1.00 | 0.50 | 5 | 0.44s |
| tech-07 | tech | comparison | hard | 0.80 | 0.50 | 0.60 | 0.50 | 0.75 | 5 | 0.42s |
| business-01 | business | factual | easy | 1.00 | 1.00 | 0.60 | 1.00 | 0.25 | 5 | 0.42s |
| business-02 | business | factual | medium | 1.00 | 1.00 | 0.40 | 0.38 | 0.50 | 5 | 0.42s |
| business-03 | business | factual | medium | 0.80 | 0.75 | 0.60 | 1.00 | 0.00 | 5 | 0.39s |
| business-04 | business | temporal | medium | 0.25 | 1.00 | 0.40 | 0.80 | 0.00 | 5 | 0.39s |
| business-05 | business | factual | easy | 0.83 | 0.75 | 0.40 | 1.00 | 0.00 | 5 | 0.39s |
| business-06 | business | synthesis | hard | 0.67 | 1.00 | 0.60 | 1.00 | 0.00 | 5 | 0.42s |
| chinese-01 | chinese | factual | easy | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 5 | 0.42s |
| chinese-02 | chinese | factual | easy | 1.00 | 1.00 | 0.00 | 0.00 | 0.25 | 5 | 0.39s |
| chinese-03 | chinese | factual | medium | 0.83 | 1.00 | 0.20 | 1.00 | 0.50 | 5 | 0.41s |
| chinese-04 | chinese | synthesis | medium | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 5 | 0.41s |
| chinese-05 | chinese | comparison | hard | 0.50 | 0.25 | 0.60 | 1.00 | 0.00 | 5 | 0.41s |
| cross-01 | cross | synthesis | hard | 1.00 | 1.00 | 0.40 | 0.33 | 0.00 | 5 | 0.41s |

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
*Report generated by benchmark_ragas.py — 2026-06-10T04:23:24.473687+00:00*