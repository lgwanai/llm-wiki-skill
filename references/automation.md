# Automation & Event Hooks

The biggest practical gap in a manual wiki is that everything requires remembering to do
it. Automation turns the wiki from a chore into infrastructure. Hooks fire automatically
so bookkeeping happens without human effort.

## Event Types

### Source Events

- **on_new_source**: Fires when the user drops a source (file, URL, text) for ingestion
- **on_source_update**: Fires when a previously ingested source changes

### Session Events

- **on_session_start**: Before the user starts working — load relevant wiki context
- **on_session_end**: After the user finishes — compress session into observations

### Memory Events

- **on_memory_write**: After a fact is written to working memory — check for
  contradictions, trigger supersession if needed
- **on_consolidation_due**: When the consolidation schedule fires

### Quality Events

- **on_lint_due**: When the lint schedule fires — run quality checks
- **on_low_quality**: When content is scored below threshold — flag for review

### Schedule Events

- **on_schedule**: Periodic events (daily, weekly) for maintenance tasks

## Hook Implementations

### on_new_source — Auto-Ingest

```yaml
trigger: User provides a source (file path, URL, pasted text)
action:
  1. Parse the source (extract text, detect format)
  2. Strip sensitive data (API keys, tokens, PII)
  3. Extract entities and relationships
  4. Check for contradictions with existing knowledge
  5. Create/update entity pages
  6. Update graph/entities.json and graph/edges.json
  7. Add observation to memory/working.json
  8. Log to audit/trail.jsonl
  9. Report summary: "Ingested [source]. Found 3 new entities, 5 relationships.
     No contradictions detected."
```

### on_session_start — Context Injection

```yaml
trigger: User begins a new working session
action:
  1. Check recent activity (last few session digests)
  2. Find entities related to current context (from user's opening message)
  3. Load relevant wiki pages into context:
     - Top 5 most relevant entities
     - Last 3 session digests
     - Any active decisions or patterns
  4. Surface: "Based on your wiki, here's relevant context for this session:
     - [[auth-service]] (last modified 3 days ago)
     - [[redis-caching]] (confidence 0.9, confirmed last week)
     - [[Session 2024-04-01]] (last session summary)"
```

### on_session_end — Compress & File

```yaml
trigger: User ends a working session (or significant pause)
action:
  1. Review the conversation for insights worth preserving
  2. Identify: new facts, decisions made, patterns observed, bugs found
  3. Group observations into a session digest using templates/session-digest.md
  4. Write digest to pages/sessions/<date>-<topic>.md
  5. Promote high-confidence observations to episodic memory
  6. Update graph with any new entities/edges discovered
  7. Report: "Session crystallized. 5 new observations filed, 2 facts promoted
     to episodic memory."
```

### on_memory_write — Contradiction Check

```yaml
trigger: A new fact is written to any memory tier
action:
  1. Check if the fact contradicts existing knowledge
  2. If contradiction found:
     - Compare source recency and authority
     - Propose resolution (which claim is more likely correct?)
     - If clear winner: supersede old claim
     - If unclear: flag both for human review
  3. Update confidence scores for related claims
```

### on_lint_due — Quality Sweep

```yaml
trigger: Lint schedule fires (default: daily for active wikis)
action:
  1. Scan all pages for orphans (no incoming links)
  2. Check for stale claims (past retention threshold)
  3. Validate wikilinks (broken references)
  4. Detect contradictions in the graph
  5. Re-score content quality
  6. Auto-heal what can be auto-healed:
     - Auto-link orphans to relevant pages
     - Mark stale claims
     - Suggest fixes for broken references
  7. Report issues that need human attention
```

### on_consolidation_due — Memory Pipeline

```yaml
trigger: Consolidation schedule fires (default: daily)
action:
  1. Group working memory observations into episode summaries
  2. Cross-reference episodes to find recurring facts
  3. Promote multi-session facts to semantic memory
  4. Apply retention decay to all facts
  5. Deprioritize/archive facts below decay threshold
  6. Report: "Consolidation complete. 12 observations → 3 episodes. 2 facts
     promoted to semantic memory. 5 facts decayed below threshold."
```

### on_schedule — Maintenance

```yaml
trigger: Periodic schedule (configurable)
actions:
  daily:
    - Lint sweep (Level 4+)
    - Consolidation cycle (Level 4+)
    - Decay application
  weekly:
    - Full re-index for search (Level 5)
    - Graph health check
    - Audit trail review (flag anomalies)
  monthly:
    - Schema review (does schema.md need updating?)
    - Bulk archive of deeply decayed content
    - Statistics report (entities, edges, pages, confidence distribution)
```

## Configuration

Hooks are configured in `.wiki/config.json`:

```json
{
  "hooks": {
    "on_new_source": {
      "enabled": true,
      "auto_ingest": true,
      "sensitive_data_filter": true
    },
    "on_session_start": {
      "enabled": true,
      "context_injection": true,
      "max_context_pages": 5
    },
    "on_session_end": {
      "enabled": true,
      "auto_crystallize": true
    },
    "on_memory_write": {
      "enabled": true,
      "contradiction_check": true,
      "auto_supersede_threshold": 0.8
    },
    "schedules": {
      "lint": {
        "enabled": true,
        "interval": "daily",
        "auto_heal": true
      },
      "consolidation": {
        "enabled": true,
        "interval": "daily",
        "retention_decay": true
      },
      "maintenance": {
        "enabled": true,
        "reindex_interval": "weekly",
        "schema_review_interval": "monthly"
      }
    }
  }
}
```

## Implementing Hooks

### In Claude Code

Claude Code supports hooks natively via `.claude/hooks/`. You can wire up wiki hooks:

1. Create hook scripts in `.claude/hooks/`:
   ```
   .claude/hooks/
   ├── session-start.sh    # Calls scripts/search.py for context injection
   ├── session-end.sh      # Calls scripts/consolidate.py for crystallization
   └── pre-tool-use.sh     # Detects source drops, triggers ingest
   ```

2. Configure in `.claude/settings.json`:
   ```json
   {
     "hooks": {
       "SessionStart": [
         { "command": ".claude/hooks/session-start.sh" }
       ],
       "Stop": [
         { "command": ".claude/hooks/session-end.sh" }
       ]
     }
   }
   ```

### Manual Triggers (Level 1-3)

Before setting up automated hooks, the LLM manually triggers these actions:

- **After ingest**: "I've ingested this source. Should I run lint to check for
  contradictions?"
- **Session start**: "Let me check your wiki for context relevant to this session."
- **Session end**: "Before we wrap up, let me crystallize what we learned into your wiki."
- **Periodic**: "It's been a week since your last consolidation. Want me to run it?"

The transition from manual to automated (Level 3 → Level 4) is the single biggest
productivity gain in the wiki lifecycle.

## Error Handling

Hooks should be resilient:

- **Failed ingest**: Log the error, flag the source, continue. Don't block other hooks.
- **Failed lint**: Report what failed, continue with partial results.
- **Hook timeout**: Set reasonable timeouts (5-10 seconds for most hooks). If a hook
  hangs, skip it and report.

## Debugging Hooks

When hooks misbehave:
1. Check `audit/trail.jsonl` for operation logs
2. Look for error entries in the audit trail
3. Run the hook manually to reproduce the issue
4. Check `config.json` for misconfiguration
