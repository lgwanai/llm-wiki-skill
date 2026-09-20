# llm-wiki — PageIndex OSS Benchmark

- Predictions: `predictions-lossless-v5-2026-09-19.configured-judged.json`
- Questions: 62
- Judged: 62
- Correct: 62
- Accuracy: **100.0%**
- Runtime errors: 0
- Indexed documents: 34
- Generated knowledge pages: 1204
- Indexing time total / mean: 5211.30s / 153.27s per document
- Query latency mean / p50 / p95: 2.58s / 2.14s / 4.03s

## By document type

| Type | Questions | Correct | Accuracy |
|---|---:|---:|---:|
| Academic paper | 7 | 7 | 100.0% |
| Administration/Industry file | 20 | 20 | 100.0% |
| Brochure | 5 | 5 | 100.0% |
| Financial report | 14 | 14 | 100.0% |
| Guidebook | 10 | 10 | 100.0% |
| Research report / Introduction | 6 | 6 | 100.0% |

## Comparability

The PDFs, questions, reference answers, prediction schema, and semantic-equivalence rubric follow PageIndex-OSS-Benchmark. A score produced by `judge-configured` is directional because it uses llm-wiki's configured model, not PageIndex's pinned gpt-5.6-luna/high judge. Run the official MMLongBench-Doc-V2 `eval.judge` command for a directly comparable score.
