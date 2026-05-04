# Privacy & Governance

Sources often contain sensitive information. A wiki that leaks credentials or PII is
worse than no wiki at all. Governance ensures the wiki remains trustworthy and auditable.

## Sensitive Data Filtering

### Filter on Ingest — Automatic, Not Optional

Before anything hits the wiki, strip sensitive data. This must be automatic because
humans forget.

### What to Filter

| Category | Patterns | Action |
|----------|----------|--------|
| API keys | `sk-...`, `ghp_...`, `AIza...`, key=value patterns | Redact entirely |
| Tokens | JWT tokens, bearer tokens, session tokens | Redact entirely |
| Passwords | `password=`, `passwd=`, `pwd=`, `secret=` | Redact value, keep key |
| Connection strings | `postgres://user:pass@host/db`, `redis://...` | Redact credentials only |
| Private keys | `-----BEGIN PRIVATE KEY-----` blocks | Redact entirely |
| PII | Email addresses, phone numbers, physical addresses | Redact or hash |
| Internal IPs | 10.x.x.x, 192.168.x.x | Redact (context-dependent) |
| Environment variables | Values of `PRODUCTION_*`, `SECRET_*` | Redact values |
| File paths with usernames | `/home/username/`, `/Users/username/` | Redact username |

### Filter Implementation

```python
# Conceptual pattern — see scripts/ingest.py for full implementation

SENSITIVE_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{32,}', '[REDACTED: API key]'),
    (r'ghp_[a-zA-Z0-9]{36}', '[REDACTED: GitHub token]'),
    (r'password\s*[=:]\s*\S+', 'password=[REDACTED]'),
    (r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END \1?PRIVATE KEY-----',
     '[REDACTED: Private key]', re.DOTALL),
    (r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED: Email]'),
]
```

### Filter Logging

Every filter action is logged:
```json
{"operation": "filter", "pattern": "API key", "source": "session-2024-04-02.txt",
 "line": 45, "timestamp": "2024-04-02T10:30:00Z"}
```

### Filter Bypass

Allow the user to explicitly opt out: "ingest this with sensitive data preserved — I've
already sanitized it." This is a conscious override, not a default.

## Audit Trail

Every operation on the wiki should be logged with a timestamp, what changed, and why.

### Trail Format

Append-only JSONL file at `audit/trail.jsonl`:

```jsonl
{"op": "ingest", "source": "article-url", "entities": ["redis", "auth-service"], "agent": "sisyphus", "ts": "2024-04-02T10:30:00Z"}
{"op": "create_entity", "entity": "redis-caching", "type": "library", "agent": "sisyphus", "ts": "2024-04-02T10:30:05Z"}
{"op": "add_edge", "source": "auth-service", "target": "redis-caching", "type": "uses", "agent": "sisyphus", "ts": "2024-04-02T10:30:05Z"}
{"op": "supersede", "old_claim": "claim-123", "new_claim": "claim-456", "reason": "newer source", "agent": "sisyphus", "ts": "2024-04-02T11:00:00Z"}
{"op": "lint", "issues_found": 12, "auto_healed": 8, "needs_attention": 4, "agent": "sisyphus", "ts": "2024-04-02T12:00:00Z"}
{"op": "filter", "pattern": "API key", "source": "config-review.txt", "line": 45, "agent": "sisyphus", "ts": "2024-04-02T10:29:58Z"}
{"op": "quality_score", "entity": "auth-service", "score": 0.85, "dimensions": {"structure": 0.9, "completeness": 0.8}, "agent": "sisyphus", "ts": "2024-04-02T12:00:10Z"}
```

### What to Log

- **All writes**: creates, updates, deletes, supersessions
- **All reads that modify state**: queries that trigger crystallization
- **All automated operations**: lint, consolidation, decay, filtering
- **All errors and exceptions**
- **All configuration changes**: schema updates, config.json changes

### What NOT to Log

- Query content (privacy — don't log what the user searches for)
- Filtered content (don't log the actual sensitive data)
- Non-state-changing reads (browsing the wiki)

### Audit Trail Usage

- **Debugging**: "Why is this entity marked stale?" → check the trail
- **Compliance**: "Show me all operations on financial data" → filter the trail
- **Security**: "Were any credentials ingested?" → grep for filter operations
- **Analytics**: "How fast is the wiki growing?" → count create operations

### Trail Rotation

For large wikis, the trail can grow unbounded. Rotate:
- Daily active trail: `audit/trail.jsonl`
- Monthly archives: `audit/archive/2024-04.jsonl`
- Retention: Keep 12 months of archives, then suggest deletion

## Bulk Operations

As the wiki grows, bulk operations become necessary:

### Bulk Delete Stale Content

When retention decay has accumulated stale content:
1. Query for all entities/pages below decay threshold
2. Present to user: "42 pages are below retention threshold. Archive?"
3. On approval: move to `.wiki/archive/`, update graph, log operation
4. Reversible: archived content can be restored

### Export Subsets

For sharing or backup:
1. Specify scope: "export all entities tagged 'infrastructure'"
2. Export format: markdown bundle, JSON graph dump, or combined
3. Include metadata: confidence scores, sources, timestamps
4. Log export operation

### Merge Duplicates

When duplicate entities are detected:
1. Present both entities side by side
2. Show attribute differences
3. Propose merge (take newest values, preserve all edges)
4. On approval: merge, update references, log operation

### Bulk Schema Update

When schema changes affect many pages:
1. Find all pages affected by schema change
2. Dry-run: show what would change
3. On approval: apply changes, re-score affected pages
4. Log the bulk operation with before/after

## Privacy by Default Principles

1. **Filter first, ingest second**: Never let raw sources touch the wiki before filtering
2. **Default deny**: Unknown patterns are treated as potentially sensitive. If unsure, flag
   for human review rather than risking a leak.
3. **Scope awareness**: Private knowledge stays private unless explicitly promoted
4. **Auditable**: Every action has a paper trail. If something goes wrong, you can trace
   exactly how.
5. **Reversible**: Bulk operations can be undone. Archives preserve content.
6. **Minimal retention**: Don't keep raw sources longer than needed. Once entities are
   extracted and confidence is established, the raw source can be discarded or archived.

## Compliance Considerations

For regulated environments:
- **Data classification**: Tag entities with classification levels (public, internal, confidential, restricted)
- **Retention policies**: Set per-classification retention rules in config.json
- **Access control**: Scope enforcement at the entity level
- **Right to be forgotten**: Support entity-level deletion with cascade (delete entity + all edges + trail references)
- **Data export**: Support full data export in portable format for compliance requests
