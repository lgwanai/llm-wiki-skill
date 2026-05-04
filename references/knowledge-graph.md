# Knowledge Graph

Flat pages with wikilinks work up to a point. Beyond that, you need a typed knowledge
graph layered on top of your pages. The graph enables structural discovery — finding
connections that keyword search would miss.

## Entities

Every meaningful "thing" in the domain becomes an entity. Each entity has:
- A unique ID (derived from the name, slugified)
- A type (person, project, library, concept, file, decision, tool)
- Attributes (key-value pairs specific to the entity type)
- A markdown page in `pages/entities/` for human reading

### Entity Types

| Type | Attributes | Example |
|------|-----------|---------|
| `person` | role, team, email, expertise | "Sarah Chen, backend lead, auth system owner" |
| `project` | status, repo, language, owner | "Auth Migration, active, github.com/acme/auth-v2" |
| `library` | version, language, purpose, docs_url | "Redis, v7.0, in-memory cache, redis.io/docs" |
| `concept` | domain, definition, related_to | "Eventual Consistency, distributed systems, CAP" |
| `file` | path, language, purpose, last_modified | "src/auth/middleware.ts, TypeScript, JWT validation" |
| `decision` | date, status, rationale, alternatives | "ADR-003: Use Redis over Memcached for session store" |
| `tool` | category, vendor, cost, usage | "Datadog, monitoring, $500/mo, all production services" |
| `pattern` | category, frequency, confidence | "Database migration pattern, seen 8 times, confidence 0.9" |

### Entity Page Format

Every entity gets a markdown page at `pages/entities/<slug>.md` using `templates/entity-page.md`:

```yaml
---
id: redis-caching
type: library
name: Redis
version: 7.0
status: active
confidence: 0.9
sources:
  - session-2024-03-15-config-review
  - codebase-scan-redis-config
last_confirmed: 2024-04-02
tags: [caching, infrastructure, database]
---
```

### Entity Registry

In addition to markdown pages, maintain `graph/entities.json` for programmatic access:

```json
{
  "redis-caching": {
    "id": "redis-caching",
    "type": "library",
    "name": "Redis",
    "attributes": {"version": "7.0", "purpose": "session caching"},
    "confidence": 0.9,
    "page": "pages/entities/redis-caching.md"
  }
}
```

## Typed Relationships

Not all connections are equal. Use typed edges to capture the semantics of how things
relate:

### Relationship Types

| Type | Meaning | Example |
|------|---------|---------|
| `uses` | A depends on B for functionality | "Auth service uses Redis for sessions" |
| `depends_on` | A requires B to function (stronger than uses) | "API gateway depends_on Auth service" |
| `owns` | A is responsible for B | "Sarah owns Auth Migration project" |
| `contains` | A is composed of / includes B | "auth-service repo contains middleware.ts" |
| `implements` | A realizes B (pattern, interface) | "Rate limiter implements Token Bucket pattern" |
| `contradicts` | A conflicts with B | "Claim: Redis is primary DB contradicts Claim: Postgres is primary DB" |
| `supersedes` | A replaces B (newer/updated version) | "Redis v7.0 config supersedes Redis v6.2 config" |
| `caused` | A led to B (causal relationship) | "Missing index caused slow query" |
| `fixed` | A resolved B (bug, issue) | "PR #456 fixed rate limiting bug" |
| `related_to` | General connection (fallback when type unclear) | "Microservices related_to Event Sourcing" |
| `before` / `after` | Temporal ordering | "Database migration before deployment" |

### Edge Format

Store edges in `graph/edges.json`:

```json
{
  "edges": [
    {
      "id": "edge-001",
      "source": "auth-service",
      "target": "redis-caching",
      "type": "uses",
      "confidence": 0.9,
      "sources": ["session-2024-03-15", "codebase-scan-redis-config"],
      "description": "Auth service uses Redis for session token storage",
      "created_at": "2024-03-15T14:30:00Z"
    }
  ]
}
```

### Bidirectional Relationships

Most relationships are directed (A → B). When the reverse is also meaningful, create a
second edge. For example:
- `auth-service uses redis-caching` → `redis-caching used_by auth-service`
- Always add the reverse edge so graph traversal works in both directions

## Graph Operations

### Entity Extraction During Ingest

When ingesting a source, extract entities and relationships:

1. **Named Entity Recognition**: Scan the source text for entity names (people, projects,
   libraries, files, concepts)
2. **Entity Resolution**: Check if each entity already exists in `graph/entities.json`.
   If so, update it. If not, create it.
3. **Relationship Extraction**: For each pair of related entities, determine the
   relationship type. Use the context to choose the most specific type.
4. **Confidence Scoring**: New entities start at 0.5. Existing entities get reinforced.
5. **Cross-Reference**: Check if the new relationship creates a contradiction with
   existing edges.

### Graph Traversal for Queries

When answering a question that requires understanding connections:

1. **Start at relevant entities**: Find entities matching the query terms
2. **Walk edges**: Traverse `uses`, `depends_on`, `contains`, `owns` edges outward
3. **Filter by type**: Only follow edges relevant to the query (e.g., for impact analysis,
   follow `depends_on` and `uses`; for ownership, follow `owns`)
4. **Depth limit**: Usually 1-2 hops is sufficient. Beyond 3 hops, relevance drops sharply.
5. **Rank results**: Sort by path confidence (product of edge confidences along the path)
   and relevance to the query.

### Example: Impact Analysis

Query: "What would break if we upgrade Redis?"

Traversal:
1. Find entity `redis-caching`
2. Follow inbound `uses` and `depends_on` edges → finds `auth-service`, `rate-limiter`,
   `session-store`
3. For each, follow outbound `contains` edges → finds specific files
4. Report: "Redis upgrade would impact auth-service (session tokens), rate-limiter
   (request counters), and session-store. Affected files: middleware.ts, rateLimit.ts,
   sessionStore.ts"

### Example: Knowledge Discovery

Query: "What patterns does Sarah's team use?"

Traversal:
1. Find entity `sarah-chen` (type: person)
2. Follow outbound `owns` edges → finds `auth-migration` (project)
3. Follow outbound `contains` edges from `auth-migration` → finds files
4. Follow `uses` edges from those files → finds libraries, patterns
5. Cross-reference `implements` edges to find recurring patterns
6. Report: "Sarah's team primarily uses JWT authentication pattern, Token Bucket rate
   limiting, and Repository pattern for data access"

## Maintaining the Graph

### When to Update

- **On every ingest**: Extract entities and edges from new sources
- **On lint**: Check for orphan entities (no incoming edges), stale edges, contradictions
- **On consolidate**: Update confidence scores, detect new semantic facts from episodes
- **On manual edit**: When the user updates a wiki page, re-extract entities from the
   updated content

### Graph Health Checks

Run periodically via `scripts/lint.py`:
1. **Orphan detection**: Entities with no edges (neither source nor target)
2. **Stale edges**: Edges where the source entity has been superseded
3. **Contradiction detection**: Two edges of type "contradicts" between the same entities
   should be resolved
4. **Density check**: If the graph is too sparse (avg edges per entity < 1), the wiki
   may need more ingests or better extraction

## Integration with Markdown Pages

The graph augments markdown pages. It doesn't replace them.

- **Pages are for reading**: Human-friendly prose, context, examples
- **Graph is for navigation**: Programmatic queries, impact analysis, discovery
- **Wikilinks in pages**: Use `[[entity-slug]]` wikilinks in markdown. These can be
  validated against `graph/entities.json` during lint.
- **Backlinks**: At the bottom of each entity page, list incoming edges with their types.
  Example:
  ```markdown
  ## Referenced by
  - [[auth-service]] *uses* this for session storage
  - [[rate-limiter]] *uses* this for request counters
  ```
