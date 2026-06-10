# Benchmark Coverage Matrix

## BEIR

| Dataset | Corpus | Qrels queries | Compiled docs | Covered qrels | Ready |
|---|---:|---:|---:|---:|---|
| SciFact | 5183 | 300 | 146 | 61 (20.33%) | True |
| NFCorpus | 3633 | 323 | 0 | 0 (0.0%) | False |
| FiQA-2018 | 57638 | 648 | 0 | 0 (0.0%) | False |

## BEIR Qrels-Centered Subset Caches

| Dataset | Subset | Format | Compiled docs | Covered qrels | Ready | Path |
|---|---|---|---:|---:|---|---|
| nfcorpus | nfcorpus_qrels25 | beir-qrels-centered-direct-wiki | 592 | 205/323 (63.47%) | True | /Users/wuliang/workspace/llm-wiki-skill/evals/beir_wiki/nfcorpus_qrels25/.wiki |
| fiqa | fiqa_qrels100 | beir-qrels-centered-direct-wiki | 226 | 100/648 (15.43%) | True | /Users/wuliang/workspace/llm-wiki-skill/evals/beir_wiki/fiqa_qrels100/.wiki |

## Private Knowledge-Base Scenarios

| Scenario | Ready | Hit@K | MRR@K | Permission leak | Forbidden hit | Files |
|---|---|---:|---:|---:|---:|---|
| long_document | True | 1.0 | 1.0 | 0.0 | 0.0 | /Users/wuliang/workspace/llm-wiki-skill/evals/private_kb_benchmark.json |
| table | True | 1.0 | 1.0 | 0.0 | 0.0 | /Users/wuliang/workspace/llm-wiki-skill/evals/private_kb_benchmark.json |
| chinese | True | 1.0 | 1.0 | 0.0 | 0.0 | /Users/wuliang/workspace/llm-wiki-skill/evals/private_kb_benchmark.json |
| permission_filter | True | 1.0 | 1.0 | 0.0 | 0.0 | /Users/wuliang/workspace/llm-wiki-skill/evals/private_kb_benchmark.json |
| temporal | True | 1.0 | 1.0 | 0.0 | 0.0 | /Users/wuliang/workspace/llm-wiki-skill/evals/private_kb_benchmark.json |
| qa_citation | True | 1.0 | 1.0 | 0.0 | 0.0 | /Users/wuliang/workspace/llm-wiki-skill/evals/private_kb_benchmark.json |

## Required Next Work

- Promote NFCorpus and FiQA from qrels-centered direct-wiki subsets to product-grade compiled caches.
- Run `python scripts/benchmark_private_kb.py --rebuild` after retrieval changes to refresh private scenario metrics.
- Add LLM compile fidelity evals: source claim preservation, entity split quality, relation graph correctness, contradiction handling.
