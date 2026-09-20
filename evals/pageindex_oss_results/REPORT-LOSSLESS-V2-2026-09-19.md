# llm-wiki — PageIndex OSS Benchmark

- Predictions: `predictions-lossless-v2-2026-09-19.configured-official-prompt-judged.json`
- Questions: 62
- Judged: 62
- Correct: 55
- Accuracy: **88.7%**
- Runtime errors: 0
- Query latency mean / p50 / p95: 2.88s / 2.22s / 4.62s

## By document type

| Type | Questions | Correct | Accuracy |
|---|---:|---:|---:|
| Academic paper | 7 | 4 | 57.1% |
| Administration/Industry file | 20 | 17 | 85.0% |
| Brochure | 5 | 5 | 100.0% |
| Financial report | 14 | 13 | 92.9% |
| Guidebook | 10 | 10 | 100.0% |
| Research report / Introduction | 6 | 6 | 100.0% |

## Comparability

The PDFs, questions, reference answers, prediction schema, and semantic-equivalence rubric follow PageIndex-OSS-Benchmark. A score produced by `judge-configured` is directional because it uses llm-wiki's configured model, not PageIndex's pinned gpt-5.6-luna/high judge. Run the official MMLongBench-Doc-V2 `eval.judge` command for a directly comparable score.
