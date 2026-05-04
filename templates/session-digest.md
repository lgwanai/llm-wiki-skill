---
id: session-[YYYY-MM-DD]-[topic]
type: session
date: [YYYY-MM-DD]
duration: [approximate duration]
threads: [list of topic tags]
entities: [list of entity IDs involved]
decisions: [list of decision IDs made]
quality_score: 0.0
confidence: 0.0
scope: private
---

# Session Digest — [YYYY-MM-DD] — [Topic]

## Summary

[2-3 sentences summarizing what this session was about and the key outcome.]

## Context

[What prompted this session? What was the user working on? Any relevant background?]

## Key Findings

<!-- List the most important insights, one per bullet. Each should be a single claim. -->

- **[Finding]**: [Description, with confidence if applicable]
- **[Finding]**: [Description]
- **[Finding]**: [Description]

## Entities Discovered or Updated

<!-- New entities found or existing entities whose knowledge was updated -->

| Entity | Type | Action | Confidence |
|--------|------|--------|------------|
| [[entity-id]] | type | created/updated | 0.0-1.0 |
| [[entity-id]] | type | created/updated | 0.0-1.0 |

## Decisions Made

<!-- Decisions reached during this session. If significant, also create a decision page. -->

1. **[[decision-id]]**: [Brief description of the decision and rationale]

## Relationships Discovered

<!-- New edges added to the knowledge graph -->

| Source | Type | Target | Confidence |
|--------|------|--------|------------|
| [[entity-id]] | uses | [[entity-id]] | 0.0-1.0 |
| [[entity-id]] | depends_on | [[entity-id]] | 0.0-1.0 |

## Open Questions

<!-- Things we didn't resolve or that need follow-up -->

- [ ] [Question or follow-up item]
- [ ] [Question or follow-up item]

## Files Involved

<!-- Files that were created, modified, or referenced -->

- `[path/to/file]` — [what happened to it]
- `[path/to/file]` — [what happened to it]

## Source Quality

<!-- Honest assessment of the quality of this session's knowledge -->

- **Source type**: [code review, research, debugging, discussion, other]
- **Primary sources**: [direct observation, code, logs — high confidence]
- **Secondary sources**: [conversation, speculation — lower confidence]
- **Verification needed**: [list claims that need independent verification]
