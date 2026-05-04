# Quality & Self-Correction

Not all LLM-generated content is good. Without quality controls, the wiki accumulates
noise. The goal is a wiki that tends toward health on its own — self-healing what it can,
flagging what needs human attention.

## Quality Scoring

Every piece of content the LLM writes should get a quality score. Score on creation,
re-score on lint.

### Scoring Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Structure | 20% | Is the page well-organized? Clear sections? Appropriate use of templates? |
| Completeness | 20% | Does it cover the topic adequately? Missing key information? |
| Source citation | 15% | Are claims backed by sources? Are citations specific? |
| Consistency | 20% | Is it consistent with other wiki pages? No contradictions? |
| Freshness | 10% | Is the content current? Past its retention threshold? |
| Readability | 15% | Clear writing? Appropriate detail level? Jargon explained? |

### Scoring Process

1. **Self-evaluation**: The LLM scores its own output immediately after writing
2. **Second-pass evaluation**: During lint, re-score with a different prompt to catch
   self-evaluation bias
3. **User feedback**: User corrections and ratings feed into scoring

### Score Ranges

| Score | Label | Action |
|-------|-------|--------|
| 0.8 - 1.0 | Excellent | No action needed |
| 0.6 - 0.8 | Good | Minor improvements optional |
| 0.4 - 0.6 | Needs work | Flagged for improvement, still visible |
| 0.2 - 0.4 | Poor | Hidden from default search, flagged for rewrite |
| 0.0 - 0.2 | Unusable | Archived, needs complete rewrite |

### Scoring in YAML Frontmatter

```yaml
---
quality_score: 0.85
quality_dimensions:
  structure: 0.9
  completeness: 0.8
  source_citation: 0.75
  consistency: 0.9
  freshness: 0.95
  readability: 0.8
last_scored: 2024-04-02T10:30:00Z
---
```

## Self-Healing

The lint operation should fix what it can automatically. Don't just report problems —
resolve them when the fix is clear.

### Auto-Healable Issues

| Issue | Detection | Auto-Fix |
|-------|-----------|----------|
| Orphan pages (no incoming links) | Count incoming edges in graph | Find related entities by keyword match, add `related_to` edges |
| Stale claims (past retention) | Compare `last_confirmed` to retention curve | Mark as `status: stale`, add warning banner |
| Broken wikilinks | Validate `[[links]]` against graph/entities.json | Find best match by edit distance, suggest replacement |
| Missing YAML frontmatter | Parse page, check for required fields | Add missing fields with reasonable defaults |
| Outdated cross-references | Entity renamed or merged | Update references throughout wiki |
| Inconsistent entity types | Entity type doesn't match attributes | Flag (can't auto-fix reliably) |

### Non-Auto-Healable Issues

| Issue | Why Not Auto | Human Action Needed |
|-------|-------------|-------------------|
| Contradictory claims | Needs judgment on which is correct | Review both claims, decide which supersedes |
| Low-quality content | Rewriting requires understanding | Review and manually improve or replace |
| Schema violations | Schema might need updating, not just content | Review schema, decide if rule changed |
| Duplicate entities | Might be intentional (similar names, different things) | Review, merge if truly duplicate |

## Contradiction Resolution

When two claims conflict, the wiki needs a resolution process:

### Detection

During ingest and lint, compare new claims against existing knowledge:
- Same entity, different attribute values ("Redis is v7.0" vs "Redis is v6.2")
- Opposing claims ("We use Postgres" vs "We use MySQL")
- Incompatible relationships ("A depends on B" vs "A is independent of B")

### Resolution Algorithm

1. **Compare source recency**: Newer source usually wins, but not always
2. **Compare source authority**: Primary source (code, logs) beats secondary (conversation)
3. **Compare reinforcement**: Claim confirmed 5 times beats claim confirmed once
4. **Compute winner confidence**: How certain is the winner?
5. **If clear winner** (confidence difference > 0.3): Auto-supersede
6. **If unclear** (confidence difference < 0.3): Flag both for human review

### Resolution Output

```
CONTRADICTION DETECTED: "Redis version"
- Claim A: Redis v7.0 (confidence: 0.85, source: codebase-scan, 3 days ago)
- Claim B: Redis v6.2 (confidence: 0.4, source: session-2024-01-15, 90 days ago)
RESOLUTION: Claim A supersedes Claim B (newer source, higher confidence)
ACTION: Marked Claim B as superseded. Linked to Claim A.
```

## Lint Report Format

After each lint pass, produce a structured report:

```markdown
# Wiki Health Report — 2024-04-02

## Summary
- Pages: 47 | Entities: 32 | Edges: 89
- Average quality score: 0.78 (+0.02 from last lint)
- Issues found: 12 | Auto-healed: 8 | Needs attention: 4

## Auto-Healed (8)
- ✅ Linked orphan page [[redis-migration]] to [[auth-service]] (related_to)
- ✅ Marked 3 stale claims in [[deployment-process]] (last confirmed > 90 days)
- ✅ Repaired 2 broken wikilinks → best match replacements
- ✅ Added missing frontmatter to [[session-2024-03-28]]

## Needs Attention (4)
### 🔴 Contradiction: Database choice
  [[data-storage]] claims Postgres. [[session-2024-03-15]] claims MySQL.
  → Both have confidence > 0.6. Please review.

### 🟡 Low quality: [[meeting-notes-2024-02-01]]
  Score: 0.35. Missing structure, no entity extraction.
  → Consider rewriting or archiving.

### 🟡 Duplicate entities: "redis-cache" and "redis-caching"
  Both describe Redis in the same context.
  → Merge into one entity?

### 🟡 Missing source: [[performance-benchmarks]]
  Claims unverified performance numbers. No sources cited.
  → Add sources or mark as unverified.
```

## Quality Gates

Before promoting content between memory tiers, apply quality gates:

### Working → Episodic Gate
- Observation must have at least one source
- Observation must be more than one sentence
- Must not be a duplicate of existing working memory observation

### Episodic → Semantic Gate
- Fact must appear in at least 2 episodes (or have confidence > 0.7)
- Must not be contradicted by higher-confidence facts
- Episode source must be from different sessions (not same session twice)

### Semantic → Procedural Gate
- Pattern must appear in at least 5 semantic facts
- Must have been observed across at least 2 different contexts
- Requires explicit human approval (manual gate)

## Preventing Quality Decay

The most common failure mode: the wiki starts great, then slowly fills with noise.
Countermeasures:

1. **Gate on ingest**: Don't accept everything. If a source is low-quality, say so
   and ingest with low confidence.
2. **Aggressive decay on transient content**: Meeting notes, bug reports, one-off
   observations should decay fast. Don't let them clutter the wiki.
3. **Regular lint**: Daily lint catches quality issues early, before they compound.
4. **Schema enforcement**: The schema defines quality standards. Enforce them strictly.
   If content doesn't meet the bar, flag it.
5. **User feedback loop**: When the user corrects or rejects wiki content, learn from
   it. Update quality scoring to prevent similar issues.
