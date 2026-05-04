# Multi-Agent Collaboration

The original LLM Wiki is single-user, single-agent. Many real use cases involve multiple
agents or multiple people contributing to the same knowledge base. This requires
coordination, scoping, and merge strategies.

## When to Implement

- **Single user, single agent**: Don't need collaboration. Skip this.
- **Single user, multiple agents** (e.g., coding agent + research agent): Need mesh sync
- **Multiple users, same wiki** (team knowledge base): Need full collaboration patterns

## Mesh Sync

When multiple agents work in parallel (different coding sessions, different research
threads), their observations need to merge into a shared wiki.

### Conflict Strategy: Last-Write-Wins

For most wiki operations, last-write-wins works because:
- Wiki content is additive (new pages, new edges)
- Facts carry confidence scores (disagreement is handled by contradiction resolution)
- The audit trail preserves all writes (nothing is lost)

### When Last-Write-Wins Isn't Enough

For structural changes (schema updates, entity merges, bulk operations), use
timestamp-based resolution:

1. Each write carries a timestamp and agent ID
2. On conflict, compare timestamps
3. If timestamps are within 30 seconds (near-simultaneous), flag for resolution
4. Otherwise, later timestamp wins

### Sync Protocol

```
1. Agent A writes to local .wiki/
2. Agent A pushes changes to shared wiki (git push / file sync)
3. Agent B pulls changes from shared wiki
4. Agent B resolves conflicts (last-write-wins for most)
5. Agent B's audit trail records the merge
```

### Merge Hooks

After merging, run:
1. **Integrity check**: Are all referenced entities still valid?
2. **Contradiction scan**: Did the merge introduce conflicts with existing knowledge?
3. **Graph update**: Are there new entities/edges to incorporate?

## Shared vs. Private Knowledge

Not all knowledge should be visible to everyone.

### Scoping Levels

| Level | Visibility | Examples |
|-------|-----------|---------|
| **Private** | Only the agent/user who created it | Personal preferences, workflow habits, private notes |
| **Team** | All agents/users in the project | Architecture decisions, team patterns, project facts |
| **Public** | Anyone with access to the wiki | Published patterns, documentation, general knowledge |

### Scope Implementation

Use YAML frontmatter to tag scope:

```yaml
---
scope: private  # or team, public
owner: agent-sisyphus
---
```

Private content:
- Excluded from other agents' search results
- Excluded from context injection for other users
- Still participates in the owner's workflows

### Promoting from Private to Shared

Private observations often contain team-useful information. The promotion flow:

1. Agent creates private observation ("Sarah prefers tabs over spaces")
2. During consolidation, agent evaluates: is this useful for the team?
3. If yes: promote to team scope. Strip any personal details.
4. If maybe: flag for human review
5. Log promotion in audit trail

### Example: Private → Team

```
PRIVATE: "When Sarah reviews my PRs, she always checks error handling first."
  ↓ (consolidation extracts pattern)
TEAM: "Code review focus areas: error handling, test coverage, type safety (Sarah Chen)"
```

## Work Coordination

When multiple agents work on the same knowledge base, lightweight coordination prevents
duplicate work.

### Coordination File

Maintain `.wiki/coordination.json`:

```json
{
  "active_agents": [
    {"id": "agent-sisyphus", "focus": "auth-service documentation", "since": "2024-04-02T10:00:00Z"},
    {"id": "agent-explore-1", "focus": "database schema mapping", "since": "2024-04-02T11:00:00Z"}
  ],
  "claimed_entities": ["auth-service", "database-schema"],
  "blocked_entities": ["redis-config (under review by Sarah)"],
  "recent_completions": [
    {"entity": "api-gateway", "agent": "agent-sisyphus", "completed": "2024-04-02T09:30:00Z"}
  ]
}
```

### Coordination Patterns

**Claim before working**: Before extensively editing an entity, claim it in coordination.json.
Check for existing claims to avoid conflicts.

**Completion notification**: After finishing work on an entity, mark it complete. Other
agents can then pick up related work.

**Stale claim detection**: If an agent's claim is older than 24 hours without activity,
mark it as potentially stale. Other agents can "steal" stale claims after a grace period.

### Lightweight vs. Full Coordination

- **Lightweight** (2-3 agents): The coordination file is sufficient. Manual claim/release.
- **Full** (5+ agents, multiple users): Consider a task queue or project management tool.
  The wiki coordinates through it using status fields on entity pages.

## Team Wiki Governance

For team wikis, establish lightweight governance:

### Roles

- **Curator**: Reviews quality, resolves contradictions, approves schema changes
- **Contributor**: Adds and updates content, follows schema
- **Reader**: Queries and browses, no write access

### Review Process

For significant changes (schema updates, bulk operations, entity merges):

1. Agent proposes change with rationale
2. Change is written to a review queue (`.wiki/review/`)
3. Curator (human) approves or rejects
4. If approved, agent applies the change
5. Audit trail records the review decision

### Contribution Guidelines

Document in `schema.md`:
- How to add a new entity
- When to create a new page vs. update existing
- Quality standards expected
- How to handle contradictions
- Review process for significant changes

## Multi-Agent Anti-Patterns

### Avoid: Duplicate Entity Proliferation
When two agents independently discover the same entity, they might create two separate
pages. **Prevention**: Always resolve entities against `graph/entities.json` before
creating new ones. Use fuzzy matching for names.

### Avoid: Edit Wars
Two agents repeatedly changing the same fact back and forth. **Prevention**: Confidence
scoring resolves most disagreements. For persistent conflicts, escalate to human review.

### Avoid: Stale Claims
An agent claims an entity and goes silent. **Prevention**: 24-hour claim expiration.
Stale claims can be taken by other agents.

### Avoid: Knowledge Silos
One agent has valuable private knowledge that the team needs. **Prevention**: Consolidation
routinely evaluates private knowledge for team promotion. Flag private knowledge that
hasn't been accessed in 30 days.
