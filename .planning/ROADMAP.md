# Roadmap: llm-wiki-skill

**Created:** 2026-05-04
**Granularity:** Standard (7 phases)
**Mode:** YOLO (auto-advance)

## Phase Summary

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Core Knowledge & References | Define the complete llm-wiki 2.0 pattern in SKILL.md + 9 reference docs | SKILL-01..08, LIFE-01..05, GRAPH-01..04, SEARCH-01..05, AUTO-01..06, QUAL-01..05, COLLAB-01..04, PRIV-01..04, CRYST-01..04, OUT-01..06 | 3 |
| 2 | Templates & Page Structure | Create reusable templates for wiki pages | TMPL-01..04 | 2 |
| 3 | Python Script Skeletons | Define API contracts for all automation scripts | SCR-01..06 | 2 |
| 4 | Project Infrastructure | Complete project configuration and packaging | INFRA-01..05 | 3 |
| 5 | Claude Code Integration | CLAUDE.md, hooks, and skill registration | CC-01..03 | 2 |
| 6 | Python Script Implementation | Implement core logic in all 6 scripts | SCR-01..06 (impl) | 3 |
| 7 | Testing & Validation | Unit tests, integration tests, eval execution | TEST-01..05 | 3 |

---

## Phase 1: Core Knowledge & References

**Goal:** Define the complete llm-wiki 2.0 pattern as a Claude Code skill with comprehensive reference documentation covering all 9 capability layers from the design blueprint.

**Requirements:** SKILL-01..08, LIFE-01..05, GRAPH-01..04, SEARCH-01..05, AUTO-01..06, QUAL-01..05, COLLAB-01..04, PRIV-01..04, CRYST-01..04, OUT-01..06

**Success Criteria:**
1. SKILL.md loads correctly as a Claude Code skill (valid YAML frontmatter, pushy description triggers on related requests)
2. All 9 reference documents are self-contained, follow consistent format, and cover their domain thoroughly
3. Implementation spectrum (Level 1-5) provides clear upgrade paths with concrete "when to upgrade" triggers

**UI hint:** no

---

## Phase 2: Templates & Page Structure

**Goal:** Create reusable, well-documented templates that the LLM uses to generate consistent wiki pages.

**Requirements:** TMPL-01..04

**Success Criteria:**
1. Schema template (schema.md) defines all entity types, relationship types, and quality standards
2. Entity page template includes all required YAML frontmatter fields and section structure

**UI hint:** no

---

## Phase 3: Python Script Skeletons

**Goal:** Define clear API contracts for all automation scripts with module docstrings, function signatures, and TODO markers.

**Requirements:** SCR-01..06

**Success Criteria:**
1. All 6 scripts have clear module docstrings describing purpose and usage
2. All function signatures include type annotations and descriptive docstrings

**UI hint:** no

---

## Phase 4: Project Infrastructure

**Goal:** Complete project configuration for a production-ready Python project.

**Requirements:** INFRA-01..05

**Success Criteria:**
1. .gitignore covers Python, macOS, IDE, and wiki artifact patterns
2. requirements.txt lists all dependencies with minimum versions
3. pyproject.toml configures black, isort, ruff, and pytest correctly

**UI hint:** no

---

## Phase 5: Claude Code Integration

**Goal:** Register the skill in the Claude Code ecosystem with workflow guidance and hook integration.

**Requirements:** CC-01..03

**Success Criteria:**
1. CLAUDE.md provides GSD workflow enforcement guidance and project context
2. Hook scripts for session start/end trigger wiki context injection and crystallization

**UI hint:** no

---

## Phase 6: Python Script Implementation

**Goal:** Implement core logic in all 6 automation scripts with working ingest, search, lint, consolidate, graph, and crystallize pipelines.

**Requirements:** SCR-01..06 (implementation)

**Success Criteria:**
1. ingest.py correctly filters sensitive data, extracts entities, and updates graph files
2. search.py implements RRF fusion with at least BM25 + graph streams
3. lint.py detects orphans, stale claims, broken links, and contradictions

**UI hint:** no

---

## Phase 7: Testing & Validation

**Goal:** Ensure the skill and scripts work correctly with comprehensive tests and eval execution.

**Requirements:** TEST-01..05

**Success Criteria:**
1. All unit tests pass (sensitive data filter, confidence scoring, retention decay)
2. Integration test for full ingest pipeline produces correct wiki output
3. All 5 eval test cases pass with expected outputs

**UI hint:** no
