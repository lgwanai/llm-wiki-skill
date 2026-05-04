# Crystallization

Crystallization is the process of taking a completed chain of work — a research thread,
a debugging session, an analysis — and distilling it into structured knowledge that
compounds in the wiki. Your explorations are a source, just like an article or a paper.

## The Core Insight

Every session with an LLM produces valuable knowledge: decisions made, patterns observed,
bugs found and fixed, relationships discovered. If this knowledge isn't captured, it's
lost when the session ends. Crystallization captures it automatically.

## What Gets Crystallized

### From a Research Session
- **Question**: What was the research question?
- **Findings**: What was discovered? With what confidence?
- **Sources**: What sources were consulted? Which were most useful?
- **Entities**: What people, projects, libraries, concepts were involved?
- **Decisions**: What was decided based on the research?
- **Open questions**: What remains unanswered?

### From a Debugging Session
- **Bug**: What was the symptom?
- **Root cause**: What caused it?
- **Fix**: How was it resolved?
- **Files involved**: What code was changed?
- **Pattern**: Is this a recurring class of bug?
- **Lesson**: What should be done differently?

### From a Code Review
- **Project**: What was reviewed?
- **Findings**: What issues were found?
- **Severity**: How critical were they?
- **Patterns**: What patterns emerged?
- **Decisions**: What changes were requested/accepted?

## Crystallization Pipeline

### Step 1: Session Wrap-Up

At session end (or when crystallization is triggered):
1. Review the conversation for structured outputs and decisions
2. Identify distinct "threads" (separate topics or work units)
3. For each thread, extract: question, findings, entities, decisions

### Step 2: Digest Creation

Create a session digest at `pages/sessions/<date>-<topic>.md` using `templates/session-digest.md`:

```yaml
---
id: session-2024-04-02-redis-config
type: session
date: 2024-04-02
threads: [redis-config-review, auth-service-performance]
entities: [redis-caching, auth-service, docker-compose.yml]
quality_score: 0.8
confidence: 0.7
---
```

The digest should be:
- **Structured**: Clear sections, not just conversation dump
- **Compressed**: Key insights, not every exchange
- **Linked**: Wikilinks to entities, decisions, patterns
- **Scored**: Quality score based on completeness and structure

### Step 3: Fact Extraction

From the digest, extract standalone facts:
1. Each fact is a single claim about a single entity
2. Facts get confidence scores based on source quality and reinforcement
3. Facts are added to working memory

Example:
```
Digest: "Redis configuration review found v7.0 in docker-compose.yml, confirmed
it's used for session caching and rate limiting in auth-service."

Extracted facts:
1. Redis version is 7.0 (confidence: 0.9, source: docker-compose.yml)
2. auth-service uses Redis for session caching (confidence: 0.85, source: codebase)
3. auth-service uses Redis for rate limiting (confidence: 0.85, source: codebase)
```

### Step 4: Graph Update

Update the knowledge graph:
1. Add new entities discovered during the session
2. Add new edges (uses, depends_on, contains, etc.)
3. Update existing entity attributes
4. Link session digest to all involved entities

### Step 5: Contradiction Check

Before finalizing:
1. Check if any extracted facts contradict existing knowledge
2. If contradiction found: resolve or flag (see quality.md)
3. Update confidence scores for all affected claims

### Step 6: Consolidation Trigger

After crystallization, trigger consolidation:
1. Group the new observations with existing working memory
2. Promote facts confirmed across multiple sessions to episodic/semantic memory
3. Apply retention decay

## Crystallization Quality

Not all sessions produce equal-quality knowledge. The crystallization should be honest
about quality:

### High-Quality Crystallization
- Multiple sources confirm the same finding
- Sources are primary (code, logs, official docs)
- Clear decisions with rationale
- Entities are well-defined with attributes

### Low-Quality Crystallization
- Single source, unverified claims
- Sources are secondary (conversation, speculation)
- No clear decisions — just exploration
- Entities are vague

Mark low-quality digests with `confidence: 0.4` and note that findings need verification.

## Auto-Crystallization Triggers

Crystallization should trigger:

| Trigger | Action |
|---------|--------|
| Session end | Full crystallization of all session threads |
| Significant decision | Mini-crystallize just the decision (don't wait for session end) |
| Bug fix | Mini-crystallize the bug + fix + lesson |
| New entity discovered | Create entity page immediately |
| User says "remember this" | Crystallize the current context |

## Human Review

After crystallization, present the digest to the user:

```
## Session Crystallized

I've distilled our session into [[session-2024-04-02-redis-config]].

### Extracted
- 5 new facts (confidence: 0.7-0.9)
- 2 updated entities: [[redis-caching]], [[auth-service]]
- 1 new relationship: auth-service → uses → redis-caching

### Quality
- Digest score: 0.8 (well-structured, sources cited)
- 1 contradiction flagged: [[deployment-process]] claims Redis v6.2
  → Our review confirms v7.0. Should I supersede the old claim?

### Next
- Review the digest for accuracy
- Resolve the contradiction
- Run `lint` if you want a full quality sweep
```

The human stays in the loop for curation but doesn't have to do the bookkeeping.

## Crystallization as Compound Interest

Each crystallization adds to the wiki's value. Over time:

- **Week 1**: 3 sessions crystallized. 15 facts. Wiki size: 12 pages.
- **Month 1**: 15 sessions. 60 facts. Some reinforced across sessions. Wiki size: 40 pages.
- **Month 6**: 90 sessions. 300+ facts. Strong confidence on recurring patterns. Wiki
  size: 150+ pages. Automated consolidation running. Graph used for impact analysis.

The wiki compounds. Early sessions create the foundation. Later sessions mostly reinforce
and refine rather than discover entirely new things. This is the goal: the wiki reaches
a steady state where it knows most of what the team knows, and new knowledge is integrated
quickly.
