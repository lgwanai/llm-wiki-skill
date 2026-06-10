# Q4 2025 Incident Postmortem: Payment Service Outage

## Incident Summary
- **Date**: 2025-11-15
- **Duration**: 4 hours 23 minutes (14:00 - 18:23 UTC)
- **Severity**: SEV-1 (Critical)
- **Impact**: Payment processing unavailable for 47% of users
- **Root Cause**: Database connection pool exhaustion in the payment-service

## Timeline

| Time (UTC) | Event |
|-------------|-------|
| 14:00 | Monitoring alerts triggered: p99 latency spike from 200ms to 8s |
| 14:07 | On-call engineer begins investigation |
| 14:15 | Identified elevated database errors in payment-service logs |
| 14:30 | Decision to restart payment-service instances |
| 14:45 | Rolling restart completed; no improvement observed |
| 15:00 | Escalated to database team |
| 15:30 | Database team identified connection pool saturation (800/800 connections) |
| 16:00 | Increased max connections from 800 to 1200 — temporary relief |
| 16:30 | Connection pool saturated again at 1200/1200 |
| 17:00 | Root cause found: new bulk-payment feature introduced connection leaks |
| 17:30 | Hotfix deployed: close connections in finally block, add connection timeout |
| 18:00 | Connection pool stabilized at 400/800 |
| 18:23 | All payment processing fully restored |

## Root Cause Analysis

### Direct Cause
The `bulk-payment-processor` service, deployed at 13:30 UTC, opened database connections in a try block but failed to close them in a finally block. Each bulk payment request leaked 1-3 connections. Under peak load (200 req/s), the connection pool exhausted within 30 minutes.

### Contributing Factors
1. **Missing connection timeout**: Default PostgreSQL timeout is infinite; leaked connections never released
2. **Insufficient monitoring**: No per-service connection pool metrics dashboard
3. **Rollout strategy**: Bulk-payment was rolled to 100% of traffic without gradual canary deployment
4. **Alert threshold**: p99 latency alert at 5s was too high; should be 500ms

## Remediation Actions

| Action | Owner | Status |
|--------|-------|--------|
| Add connection leak detection middleware | payment-team | Done |
| Implement circuit breaker for DB connections | infra-team | Done |
| Reduce p99 alert threshold to 500ms | observability-team | Done |
| Mandatory canary deployment for all payment services | devops-team | In Review |
| Weekly connection pool audit dashboard | observability-team | Done |
| Outbox pattern for async payment processing | payment-team | Planned Q1 2026 |

## Lessons Learned

1. All database connections must be managed through connection pools with hard timeouts (30s max connection lifetime)
2. Critical path services require mandatory canary deployments (1% → 10% → 50% → 100%)
3. Each service must expose connection pool saturation as a first-class metric
4. Recovery runbooks should include "check recent deploys" as the second step (after health checks)

## Outbox Pattern Implementation

The planned outbox pattern (`outbox_retry_watermark`) will decouple payment requests from database transactions. Payment events are first written to an outbox table atomically with the business transaction, then processed asynchronously. The retry watermark tracks the last successfully processed event ID, enabling idempotent replay after failures.
