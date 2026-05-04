# Implementation Spectrum

All of llm-wiki v2 is modular. Pick your entry point based on current needs.

## Level 1 — Minimal Viable Wiki

**What you get**: Raw sources → wiki pages. Manual workflows. Start here.

### Setup

```bash
mkdir -p .wiki/{pages/{entities,decisions,sessions,patterns},graph,memory,audit}
```

### Files to Create
- `.wiki/schema.md` — use `templates/schema.md`
- `.wiki/pages/index.md` — use `templates/index.md`
- `.wiki/config.json` — basic config with hooks disabled

### Workflows (Manual)
- **Ingest**: User provides source → Claude extracts entities → writes page → updates index
- **Query**: Claude searches index.md → finds relevant pages → synthesizes answer
- **Lint**: User asks for lint → Claude checks orphans, broken links → suggests fixes
- **Consolidate**: Not implemented at this level

### When to Upgrade
- Index.md gets too long to read in one pass (>100-200 pages)
- Wiki starts accumulating noise (outdated information)
- You want automatic maintenance

## Level 2 — Add Lifecycle

**What you add**: Confidence scoring, supersession, basic decay, memory tiers.

### Additional Setup
1. Add confidence YAML fields to entity pages
2. Initialize `memory/working.json`, `memory/episodic.json`, `memory/semantic.json`
3. Enable basic decay in config.json

### New Capabilities
- Every claim carries a confidence score
- Old claims are superseded, not deleted
- Facts decay with time if not reinforced
- Observations grouped into episodes

### Workflows
- **Consolidate**: Manual trigger. Promotes working → episodic → semantic
- **Lint**: Now checks staleness, contradictions, confidence scores

### When to Upgrade
- You want the wiki to automatically surface connections
- Flat pages aren't enough for discovery
- You're making decisions based on wiki content and need better structure

## Level 3 — Add Structure

**What you add**: Entity extraction, typed relationships, knowledge graph, graph traversal.

### Additional Setup
1. Create entity extraction pipeline (manual or scripted)
2. Create `graph/entities.json` and `graph/edges.json`
3. Add typed relationship logic to ingest workflow
4. Implement basic graph traversal for queries

### New Capabilities
- All entities are extracted and typed
- Relationships carry semantic meaning (uses, depends_on, caused, etc.)
- Graph traversal enables impact analysis and discovery queries
- Wikilinks validated against entity registry

### Workflows
- **Ingest**: Now includes entity extraction + graph update
- **Query**: Now can use graph traversal for relationship queries
- **Lint**: Now validates graph integrity

### When to Upgrade
- Maintenance burden is becoming noticeable
- You're forgetting to run lint and consolidate
- You want the wiki to be self-maintaining

## Level 4 — Add Automation

**What you add**: Event hooks, auto-lint, context injection, consolidation pipeline.

### Additional Setup
1. Configure hooks in `.wiki/config.json` (enable auto-ingest, auto-lint, etc.)
2. Implement hook scripts or Claude Code hooks
3. Set up consolidation schedule
4. Enable quality scoring on all new content
5. Enable self-healing during lint

### New Capabilities
- Sources auto-ingested on drop
- Wiki context injected at session start
- Sessions auto-crystallized at session end
- Lint runs on schedule, auto-heals what it can
- Consolidation pipeline runs automatically
- Quality scores assigned to all content

### Workflows
- Everything from Level 3, but automatic
- Human only needs to: review contradictions, approve schema changes, set direction

### When to Upgrade
- Wiki has grown past 500 pages
- You need better search than grep + index.md
- You're working with multiple agents or a team
- Search quality is declining

## Level 5 — Add Scale & Collaboration

**What you add**: Hybrid search, mesh sync, shared/private scoping, work coordination.

### Additional Setup
1. Implement hybrid search (BM25 + vector + graph)
2. Set up embedding generation pipeline
3. Configure mesh sync (git-based or file sync)
4. Add scope fields to entity pages
5. Create coordination file

### New Capabilities
- Search combines keyword, semantic, and graph results
- Multiple agents can contribute to the same wiki
- Private and shared knowledge are properly scoped
- Agents coordinate to avoid duplicate work
- Bulk operations with governance (audited, reversible)

### Workflows
- **Search**: Hybrid search with RRF fusion, query-type weighting
- **Sync**: Mesh sync with last-write-wins, conflict resolution
- **Coordination**: Claim entities before editing, coordination file

### Maintenance
- Weekly re-index for search
- Monthly schema review
- Periodic bulk archive of deeply decayed content
- Audit trail rotation

## Level Selection Guide

Start at Level 1. Upgrade when you feel pain:

| Pain Point | Upgrade To |
|-----------|-----------|
| "I can't find anything in this wiki" | Level 3 (graph structure) or Level 5 (hybrid search) |
| "This information is outdated" | Level 2 (lifecycle/decay) |
| "I keep forgetting to update the wiki" | Level 4 (automation) |
| "Multiple people/agents need this" | Level 5 (collaboration) |
| "The wiki keeps growing but quality is dropping" | Level 2 (quality scoring) then Level 4 (auto-lint) |

## Upgrading Between Levels

Upgrades are additive. You never lose functionality from lower levels.

1. **Read the reference file for the new level's features**
2. **Enable in config.json** — each feature has an enabled flag
3. **Initialize new data structures** — run setup scripts for new files
4. **Run a full lint** — validate existing content against new quality rules
5. **Run consolidation** — backfill confidence scores, extract entities from existing pages
6. **Verify** — query the wiki, check that new features work
