# API Rate Limiting Policy

## Current Limits (2026)

### Partner API
| Tier | Rate Limit | Burst Allowance | Window |
|------|-----------|----------------|--------|
| Standard Partner | 600 req/min | 100 burst | 1 minute sliding |
| Premium Partner | 1200 req/min | 200 burst | 1 minute sliding |
| Enterprise Partner | 3000 req/min | 500 burst | 1 minute sliding |

Rate limits are enforced per API key with a sliding window algorithm. When a limit is exceeded, the API returns HTTP 429 with `Retry-After` header indicating the wait time in seconds.

### Internal Services
| Service | Rate Limit | Rationale |
|---------|-----------|-----------|
| auth-service | 5000 req/s | Stateless, horizontally scalable |
| payment-service | 1000 req/s | Database-bound, connection pool limited |
| notification-service | 2000 req/s | Async with queue buffering |
| search-service | 3000 req/s | Read-only, cached |

## Historical Changes

### 2024 Limits (Deprecated)
- Standard Partner: 300 req/min
- Premium Partner: 600 req/min
- Enterprise Partner: 1500 req/min

The 2024 limits were doubled in 2025 after infrastructure upgrades (migration from monolith to microservices with Kubernetes autoscaling). The 2024 policy document (`partner-api-rate-limit-2024.md`) is marked as superseded and should not be used for current decisions.

### 2025 Upgrades
Key infrastructure changes that enabled the limit increases:
1. Kubernetes HPA (Horizontal Pod Autoscaler) with custom metrics
2. Redis-based distributed rate limiter replacing in-memory counters
3. Multi-region API gateway deployment reducing cross-region latency

## Enforcement Architecture

```
API Gateway (Kong) → Rate Limiter (Redis) → Backend Service
                          ↓
                   Redis Cluster (3 nodes)
                   - Key: ratelimit:{api_key}:{window}
                   - TTL: window duration
                   - Algorithm: Sliding window counter
```

## Rate Limit Headers

All API responses include:
```
X-RateLimit-Limit: 1200
X-RateLimit-Remaining: 847
X-RateLimit-Reset: 2026-01-15T10:30:00Z
```

## Handling Rate Limits

Clients must implement exponential backoff with jitter:
- Initial retry: `Retry-After` + random(0, 2s)
- Second retry: `Retry-After * 2` + random(0, 4s)
- Third retry: `Retry-After * 4` + random(0, 8s)
- Max retries: 3

Consecutive rate limit violations (> 10/minute) trigger temporary API key suspension for 5 minutes.
