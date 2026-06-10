# Private Knowledge-Base Benchmark

Generated: 2026-06-10 02:19:50 UTC

Scope: retrieval-only benchmark over deterministic materialized wiki pages. Compile and LLM answer synthesis are skipped.

## Summary

| Cases | Streams | Hit@K | Recall@K | MRR@K | Required term coverage | Permission leak rate | Forbidden hit rate |
|---:|---|---:|---:|---:|---:|---:|---:|
| 6 | metadata,chunk,bm25 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |

## Scenario Breakdown

| Scenario | Cases | Hit@K | Recall@K | MRR@K | Required term coverage | Permission leak rate | Forbidden hit rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| long_document | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| table | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| chinese | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| permission_filter | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| temporal | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| qa_citation | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |

## Findings

- Permission filtering did not leak in this fixture, but the search API still lacks an explicit user/ACL parameter.
- Temporal filtering excludes superseded pages in this fixture when `exclude_statuses` is supplied.

## Details

| Case | Scenario | Retrieved | Forbidden hits | Unauthorized hits | MRR@K | Required terms | Latency |
|---|---|---|---|---|---:|---:|---:|
| long-document-section | long_document | q4-incident-runbook, mercury-public-status, mercury-confidential-budget, soc2-evidence-retention, partner-api-rate-limit-2024 |  |  | 1.0000 | 1.0000 | 0.2667s |
| table-plan-retention | table | enterprise-pricing-2026, soc2-evidence-retention |  |  | 1.0000 | 1.0000 | 0.0013s |
| chinese-release-owner | chinese | zh-release-policy |  |  | 1.0000 | 1.0000 | 0.0007s |
| permission-public-user | permission_filter | mercury-public-status |  |  | 1.0000 | 1.0000 | 0.0013s |
| temporal-current-limit | temporal | partner-api-rate-limit-2026, enterprise-pricing-2026, mercury-public-status |  |  | 1.0000 | 1.0000 | 0.0014s |
| qa-citation-source | qa_citation | soc2-evidence-retention, enterprise-pricing-2026, mercury-public-status, mercury-confidential-budget, partner-api-rate-limit-2026 |  |  | 1.0000 | 1.0000 | 0.0013s |

## Limits

- This fixture is synthetic and intentionally small; it is for regression and product-gap detection, not public leaderboard comparison.
- The permission scenario verifies scope filtering through the `allowed_scopes` search parameter, not a full user/role policy engine.
