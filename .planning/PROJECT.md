# llm-wiki-skill

## What This Is

A Claude Code skill implementing **LLM Wiki v2** — a production-hardened pattern for building
personal knowledge bases that compound over time with LLM-powered automation. The skill
transforms Claude into a disciplined knowledge librarian that ingests sources, builds a typed
knowledge graph, maintains quality through automated linting, consolidates observations across
memory tiers, and crystallizes working sessions into structured digests.

Based on [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
and extended with patterns from [agentmemory](https://github.com/rohitg00/agentmemory).

## Core Value

Stop re-deriving, start compiling. Every source and session adds permanent, searchable value
to a living knowledge base — with automated lifecycle management so knowledge doesn't rot.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] **SKILL-01**: Trigger on wiki/knowledge base requests with comprehensive description
- [ ] **SKILL-02**: Guide LLM through .wiki/ directory initialization (Level 1)
- [ ] **SKILL-03**: Ingest workflow — source → entity extraction → graph update → page creation
- [ ] **SKILL-04**: Query workflow — search → graph traversal → synthesize → crystallize
- [ ] **SKILL-05**: Lint workflow — quality checks + auto-healing
- [ ] **SKILL-06**: Consolidate workflow — memory tier promotion + retention decay
- [ ] **LIFE-01**: Confidence scoring on every wiki claim
- [ ] **LIFE-02**: Supersession when new facts replace old
- [ ] **LIFE-03**: Ebbinghaus retention decay with domain-specific half-lives
- [ ] **LIFE-04**: Four-tier memory pipeline (working → episodic → semantic → procedural)
- [ ] **GRAPH-01**: Entity extraction with typed attributes
- [ ] **GRAPH-02**: Typed relationships (uses, depends_on, contains, caused, fixed, supersedes)
- [ ] **GRAPH-03**: Graph traversal for impact analysis and discovery queries
- [ ] **SEARCH-01**: Hybrid search (BM25 + vector + graph) with RRF fusion
- [ ] **SEARCH-02**: Query-type-weighted stream selection
- [ ] **AUTO-01**: Event hooks (on_new_source, on_session_start, on_session_end)
- [ ] **AUTO-02**: Auto-ingest with sensitive data filtering
- [ ] **AUTO-03**: Auto-lint on schedule with self-healing
- [ ] **AUTO-04**: Auto-crystallization at session end
- [ ] **QUAL-01**: Six-dimensional quality scoring on all content
- [ ] **QUAL-02**: Contradiction detection and resolution protocol
- [ ] **QUAL-03**: Quality gates between memory tiers
- [ ] **COLLAB-01**: Mesh sync with last-write-wins
- [ ] **COLLAB-02**: Shared/private/team scoping
- [ ] **COLLAB-03**: Agent coordination via claims and completions
- [ ] **PRIV-01**: Sensitive data filter on ingest (API keys, tokens, PII)
- [ ] **PRIV-02**: Append-only audit trail (audit/trail.jsonl)
- [ ] **PRIV-03**: Bulk governance operations (archive, export, merge)
- [ ] **CRYST-01**: Session → digest pipeline with fact extraction
- [ ] **CRYST-02**: Auto-promotion of multi-session facts
- [ ] **OUT-01**: Comparison tables for entity comparison
- [ ] **OUT-02**: Mermaid timeline and dependency graph generation
- [ ] **OUT-03**: Marp slide deck generation
- [ ] **OUT-04**: Structured data export (JSON, CSV)

### Out of Scope

- Real-time collaborative editing (out of scope for v1)
- Full vector database integration (FAISS only for now, Level 5+)
- Mobile app or web UI for wiki browsing
- Integration with external knowledge bases (Notion, Obsidian sync)

## Context

### Technical Environment
- **Runtime**: OpenCode (Claude-compatible skill system)
- **Language**: Python 3.10+ for automation scripts
- **Skill format**: SKILL.md with YAML frontmatter
- **Wiki format**: Markdown pages with YAML frontmatter + JSON graph files
- **Storage**: Filesystem-based (.wiki/ directory)
- **Key dependencies**: pyyaml, numpy, sentence-transformers (Level 5), faiss-cpu (Level 5)

### Design Blueprint
Full specification from [llm-wiki v2 gist](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2):
- 9 capability layers: lifecycle, graph, search, automation, quality, collaboration, privacy, crystallization, output formats
- 5 maturity levels from minimal viable wiki to full-scale team wiki

### Current State
Core skill structure built: SKILL.md, 9 reference docs, 4 templates, 6 Python scripts (fully implemented),
project config (.gitignore, requirements.txt, pyproject.toml, LICENSE, README.md), 5 eval test cases.
All phases complete: Python scripts are implemented and tested, Claude Code hooks are integrated.

## Constraints

- **Runtime**: Must work as a Claude Code skill (SKILL.md-based)
- **Python**: >=3.10 for automation scripts
- **Wiki storage**: Filesystem only, no database required
- **Privacy**: Sensitive data must be filtered before wiki write (never stored)
- **Portability**: Wiki schema must be transferable between projects

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Markdown + YAML for wiki pages | Human-readable, works with Obsidian, git-friendly | — Pending |
| JSON for graph/entities and graph/edges | Programmatic access, easy to query in scripts | — Pending |
| .wiki/ directory convention | Self-contained, portable, git-trackable | — Pending |
| MIT License | Permissive, standard for developer tools | ✓ Good |
| Python skeleton scripts with TODO markers | Defines API contract, implementation deferred to later phases | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-04 after initialization*
