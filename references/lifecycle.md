# Memory Lifecycle

Knowledge has a lifecycle. A bug from last week matters more than one from six months ago.
A pattern seen twelve times is more reliable than one seen once. Treating all wiki content
as equally valid forever is the fastest path to a junk drawer.

## Confidence Scoring

Every fact in the wiki carries a confidence score: a number from 0.0 to 1.0 reflecting
how reliable the claim is. The score is computed from:

- **Source count**: How many independent sources support this claim?
- **Recency**: When was it last confirmed? Newer = higher confidence.
- **Source authority**: Is the source primary (code, logs) or secondary (hearsay)?
- **Contradictions**: Are there competing claims? Presence of contradictions lowers confidence.
- **Reinforcement count**: How many times has this fact been accessed/confirmed?

```json
{
  "claim": "Project X uses Redis for caching",
  "confidence": 0.85,
  "sources": ["session-2024-03-15-config-review", "codebase-scan-redis-config"],
  "last_confirmed": "2024-04-02T10:30:00Z",
  "reinforcements": 4,
  "contradictions": [],
  "decay_base": 0.95
}
```

### Computing Confidence

Base formula (tune parameters per domain):

```
confidence = base_score * recency_factor * authority_factor * (1 - contradiction_penalty)

base_score       = min(1.0, source_count / target_sources)
recency_factor   = decay_base ^ (days_since_last_confirmation / half_life_days)
authority_factor = 1.0 for primary sources, 0.7 for secondary
contradiction_penalty = min(0.5, contradiction_count * 0.15)
```

Example: target 3 sources, half-life 30 days, decay base 0.95
- 2 sources, confirmed 14 days ago, no contradictions, primary source
- confidence = (2/3) * 0.95^(14/30) * 1.0 * 1.0 = 0.667 * 0.976 * 1.0 = 0.65

### When to Update Confidence

Recalculate when:
- A new source confirms the claim → increment reinforcement
- A new source contradicts the claim → add to contradictions, recalculate
- Time passes without reinforcement → decay applies
- A source is found to be unreliable → adjust authority

## Supersession

When new information contradicts or updates an existing claim, the old claim shouldn't
just sit there. The new one explicitly supersedes it.

### Supersession Protocol

1. **Detect**: During ingest, check if new claim conflicts with existing knowledge
2. **Evaluate**: Which claims more likely correct? Consider source recency, authority,
   and reinforcement count.
3. **Link**: The new claim gets a `supersedes` edge pointing to the old claim's ID
4. **Mark**: The old claim gets `status: "superseded"`, `superseded_by: <new_id>`,
   and `superseded_at: <timestamp>`
5. **Preserve**: The old claim is NOT deleted. It stays in the wiki for historical context
6. **Update graph**: `supersedes` is a typed relationship in the knowledge graph

### When NOT to Supersede

- The contradiction is low-confidence (< 0.3 on the new claim)
- The contradiction is from a lower-authority source
- The user or schema specifies that both claims can coexist (e.g., "team A uses Postgres,
  team B uses MySQL" — these don't supersede, they coexist)

When in doubt, flag for human review rather than auto-superseding.

## Forgetting (Retention Decay)

Not everything should live forever. A wiki that never forgets becomes noisy.

### Ebbinghaus Forgetting Curve

Model retention using an exponential decay function:

```
R(t) = e^(-t / S)

Where:
- R(t) is retention at time t (days since last reinforcement)
- S is the relative strength of the memory (higher S = slower decay)
- Each reinforcement resets t to 0 and increases S slightly
```

### Decay Categories

Apply different decay rates for different types of knowledge:

| Knowledge Type | Decay Rate | Half-Life | Retention Curve |
|---------------|------------|-----------|-----------------|
| Architecture decisions | Very slow | 180 days | S = 260 |
| Project facts (tech stack, dependencies) | Slow | 90 days | S = 130 |
| Bug reports / transient issues | Fast | 14 days | S = 20 |
| Meeting notes / conversations | Very fast | 7 days | S = 10 |
| Code patterns / workflows | Slow | 60 days | S = 87 |
| Personal preferences | Very slow | 365 days | S = 527 |

### What Happens When Facts Decay

- **Above 0.5**: Full visibility in search results, full confidence in answers
- **0.3 - 0.5**: Still searchable but deprioritized. Include with caveat in answers
- **0.15 - 0.3**: Hidden from default search. Visible only with `--include-stale` flag.
  Equivalent to moving something to a bottom drawer.
- **Below 0.15**: Archived (moved to `.wiki/archive/`). Not deleted, but out of the
  active knowledge set.

### Reinforcement

Each time a fact is accessed (queried, confirmed by new source, explicitly referenced):
1. Reset the retention timer (t = 0)
2. Slightly increase S (learning effect: S_new = S_old * 1.05, capped at 10x original)

This means frequently-used knowledge strengthens and persists. Unused knowledge fades.

## Consolidation Tiers

Raw observations aren't the same as established facts. Build a pipeline with four tiers:

### Working Memory
- **Content**: Recent observations, raw notes, unprocessed ingest outputs
- **Lifetime**: Hours to days
- **Format**: `memory/working.json` — array of observation objects
- **Processing**: Grouped into episode summaries during consolidation
- **Example**: "Claude noticed that the Redis config in docker-compose.yml uses password
  'redis123'"

### Episodic Memory
- **Content**: Session summaries, compressed from working memory observations
- **Lifetime**: Days to weeks
- **Format**: `memory/episodic.json` — array of episode objects with structured fields
- **Processing**: Cross-referenced to extract facts during consolidation
- **Example**: "Session 2024-03-15: Reviewed Redis configuration. Found password in
  docker-compose.yml (security concern), confirmed Redis is used for session caching
  and rate limiting."

### Semantic Memory
- **Content**: Cross-session facts, consolidated from episodes
- **Lifetime**: Months to permanent (with decay)
- **Format**: `memory/semantic.json` — array of fact objects with confidence scores
- **Processing**: Promoted from episodes when confirmed across multiple sessions
- **Example**: "Project X uses Redis (v7.0) for session caching. Configuration at
  docker-compose.yml:45. Last confirmed 2024-04-02. Confidence: 0.85."

### Procedural Memory
- **Content**: Workflows and patterns, extracted from repeated semantic memories
- **Lifetime**: Permanent (reviewed, not decayed)
- **Format**: `pages/patterns/` as wiki pages
- **Processing**: Manually promoted when a pattern has been observed 5+ times
- **Example**: "Deployment checklist: 1. Run tests, 2. Build Docker image, 3. Push to
  registry, 4. Update k8s manifest, 5. Apply with kubectl"

### Promotion Rules

```
Working → Episodic: When ≥ 5 observations accumulate OR session ends
Episodic → Semantic: When same fact appears in ≥ 2 episodes OR confidence > 0.7
Semantic → Procedural: When same pattern appears in ≥ 5 semantic facts (manual gate)
```

### Consolidation Schedule

Run consolidation:
- Automatically at the end of each session (Level 4+)
- On schedule: daily for active wikis, weekly for dormant ones
- On demand when the user wants to clean up

## Implementation

### Setting Up Lifecycle Tracking

1. Add confidence fields to entity pages in YAML frontmatter:
   ```yaml
   ---
   confidence: 0.85
   sources: ["session-2024-03-15", "codebase-scan-redis"]
   last_confirmed: 2024-04-02
   reinforcements: 4
   contradictions: []
   status: active
   ---
   ```

2. Initialize `memory/working.json`, `memory/episodic.json`, `memory/semantic.json`
   with empty arrays.

3. Set up the consolidation schedule in `config.json`.

4. Run `scripts/consolidate.py` on schedule or on demand.

### Tuning Parameters

The default parameters (half-lives, decay rates, promotion thresholds) work for most
projects. Tune them in `config.json` when:
- Your domain moves faster/slower than defaults
- You want more/less aggressive forgetting
- You have specific retention requirements (compliance, etc.)
