# llm-wiki RAGAS Black-Box Evaluation Report

**Generated**: 2026-06-10T04:04:44.506212+00:00
**Pipeline**: direct wiki → search → synthesize
**Test Cases**: 19
**Domains**: tech, business, chinese

---

## Overall Scores vs Industry Baselines

| System | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|--------|-------------|-----------------|-------------------|---------------|-------------------|
| **llm-wiki (this eval)** | 0.644 | 0.711 | 0.461 | 0.858 | 0.316 |
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
| tech | 7 | 0.589 | 0.643 | 0.532 | 0.900 | 0.429 |
| business | 6 | 0.686 | 0.750 | 0.438 | 0.833 | 0.167 |
| chinese | 5 | 0.647 | 0.700 | 0.438 | 1.000 | 0.350 |
| cross | 1 | 0.750 | 1.000 | 0.219 | 0.000 | 0.250 |

## Difficulty Breakdown

| Difficulty | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| easy | 7 | 0.645 | 0.786 | 0.501 | 0.971 | 0.250 |
| medium | 8 | 0.629 | 0.719 | 0.465 | 0.844 | 0.438 |
| hard | 4 | 0.672 | 0.562 | 0.383 | 0.688 | 0.188 |

## Query Type Breakdown

| Type | Cases | Faithfulness | Answer Relevance | Context Precision | Context Recall | Answer Correctness |
|------|-------|-------------|-----------------|-------------------|---------------|-------------------|
| factual | 11 | 0.599 | 0.727 | 0.478 | 0.891 | 0.318 |
| synthesis | 5 | 0.775 | 0.750 | 0.438 | 0.750 | 0.400 |
| comparison | 2 | 0.635 | 0.375 | 0.438 | 0.875 | 0.250 |
| temporal | 1 | 0.500 | 1.000 | 0.438 | 1.000 | 0.000 |

## Latency

| Metric | Value |
|--------|-------|
| Mean search latency | 0.625s |
| P50 search latency | 0.270s |
| P95 search latency | 6.991s |
| Min search latency | 0.243s |
| Max search latency | 6.991s |

## Per-Case Results

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness | Pages | Search Latency |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|-------|---------------|
| tech-01 | tech | factual | easy | 1.00 | 0.75 | 0.66 | 1.00 | 0.50 | 5 | 6.99s |
| tech-02 | tech | factual | easy | 0.00 | 1.00 | 0.44 | 1.00 | 0.25 | 5 | 0.28s |
| tech-03 | tech | factual | easy | 0.80 | 0.25 | 0.66 | 0.80 | 0.00 | 5 | 0.25s |
| tech-04 | tech | synthesis | medium | 0.62 | 1.00 | 0.66 | 0.75 | 0.75 | 5 | 0.28s |
| tech-05 | tech | factual | medium | 0.00 | 0.00 | 0.44 | 1.00 | 0.25 | 5 | 0.27s |
| tech-06 | tech | synthesis | medium | 1.00 | 1.00 | 0.44 | 1.00 | 1.00 | 5 | 0.26s |
| tech-07 | tech | comparison | hard | 0.70 | 0.50 | 0.44 | 0.75 | 0.25 | 5 | 0.25s |
| business-01 | business | factual | easy | 0.67 | 1.00 | 0.44 | 1.00 | 0.00 | 5 | 0.24s |
| business-02 | business | factual | medium | 1.00 | 0.50 | 0.44 | 0.00 | 0.00 | 5 | 0.26s |
| business-03 | business | factual | medium | 0.57 | 1.00 | 0.44 | 1.00 | 1.00 | 5 | 0.26s |
| business-04 | business | temporal | medium | 0.50 | 1.00 | 0.44 | 1.00 | 0.00 | 5 | 0.26s |
| business-05 | business | factual | easy | 0.71 | 0.50 | 0.44 | 1.00 | 0.00 | 5 | 0.26s |
| business-06 | business | synthesis | hard | 0.67 | 0.50 | 0.44 | 1.00 | 0.00 | 5 | 0.28s |
| chinese-01 | chinese | factual | easy | 1.00 | 1.00 | 0.44 | 1.00 | 1.00 | 5 | 0.27s |
| chinese-02 | chinese | factual | easy | 0.33 | 1.00 | 0.44 | 1.00 | 0.00 | 5 | 0.27s |
| chinese-03 | chinese | factual | medium | 0.50 | 1.00 | 0.44 | 1.00 | 0.50 | 5 | 0.24s |
| chinese-04 | chinese | synthesis | medium | 0.83 | 0.25 | 0.44 | 1.00 | 0.00 | 5 | 0.37s |
| chinese-05 | chinese | comparison | hard | 0.57 | 0.25 | 0.44 | 1.00 | 0.25 | 5 | 0.27s |
| cross-01 | cross | synthesis | hard | 0.75 | 1.00 | 0.22 | 0.00 | 0.25 | 5 | 0.29s |

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
*Report generated by benchmark_ragas.py — 2026-06-10T04:04:44.506212+00:00*