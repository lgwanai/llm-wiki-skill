# Requirements: llm-wiki-skill

**Defined:** 2026-05-04
**Core Value:** Stop re-deriving, start compiling — build a living knowledge base that compounds over time

## v1 Requirements

### Skill Definition (SKILL)

- [ ] **SKILL-01**: SKILL.md triggers on wiki/knowledge base requests with pushy description
- [ ] **SKILL-02**: Guide LLM through .wiki/ directory initialization (Level 1 quick start)
- [ ] **SKILL-03**: Ingest workflow documented — source → entity extraction → graph update → page creation
- [ ] **SKILL-04**: Query workflow documented — search → graph traversal → synthesize → crystallize
- [ ] **SKILL-05**: Lint workflow documented — quality checks + auto-healing
- [ ] **SKILL-06**: Consolidate workflow documented — memory tier promotion + retention decay
- [ ] **SKILL-07**: Implementation spectrum (Level 1-5) with upgrade triggers
- [ ] **SKILL-08**: Reference file pointers with "when to load" guidance

### Memory Lifecycle (LIFE)

- [ ] **LIFE-01**: Confidence scoring formulas and YAML fields
- [ ] **LIFE-02**: Supersession protocol (detect → evaluate → link → mark → preserve)
- [ ] **LIFE-03**: Ebbinghaus retention decay with 6 decay categories
- [ ] **LIFE-04**: Four-tier memory pipeline with promotion rules
- [ ] **LIFE-05**: Consolidation schedule and decay application

### Knowledge Graph (GRAPH)

- [ ] **GRAPH-01**: 8 entity types with required/optional attributes
- [ ] **GRAPH-02**: 12 typed relationship types with semantic meanings
- [ ] **GRAPH-03**: Graph traversal for impact analysis and discovery
- [ ] **GRAPH-04**: Entity registry (entities.json) and edges (edges.json) format

### Hybrid Search (SEARCH)

- [ ] **SEARCH-01**: BM25 keyword search with stemming and synonym expansion
- [ ] **SEARCH-02**: Vector/embedding search via sentence-transformers
- [ ] **SEARCH-03**: Graph traversal search via entity walking
- [ ] **SEARCH-04**: Reciprocal Rank Fusion for result merging
- [ ] **SEARCH-05**: Query-type-weighted stream selection

### Automation (AUTO)

- [ ] **AUTO-01**: 7 event hook types defined
- [ ] **AUTO-02**: Auto-ingest hook with sensitive data filtering
- [ ] **AUTO-03**: Auto-lint hook with schedule configuration
- [ ] **AUTO-04**: Auto-crystallization hook at session end
- [ ] **AUTO-05**: Context injection hook at session start
- [ ] **AUTO-06**: Config.json schema for hook configuration

### Quality (QUAL)

- [ ] **QUAL-01**: 6-dimension quality scoring rubric
- [ ] **QUAL-02**: Self-healing rules (orphans, stale claims, broken links)
- [ ] **QUAL-03**: Contradiction detection and resolution algorithm
- [ ] **QUAL-04**: Quality gates between memory tiers
- [ ] **QUAL-05**: Lint report format specification

### Collaboration (COLLAB)

- [ ] **COLLAB-01**: Mesh sync protocol with last-write-wins
- [ ] **COLLAB-02**: Shared/private/team scoping with YAML field
- [ ] **COLLAB-03**: Coordination file format (coordination.json)
- [ ] **COLLAB-04**: Anti-patterns documentation

### Privacy & Governance (PRIV)

- [ ] **PRIV-01**: Sensitive data filter patterns (8 categories)
- [ ] **PRIV-02**: Audit trail format (trail.jsonl with 8 operation types)
- [ ] **PRIV-03**: Bulk operation protocols (delete, export, merge)
- [ ] **PRIV-04**: Compliance considerations

### Crystallization (CRYST)

- [ ] **CRYST-01**: 6-step crystallization pipeline
- [ ] **CRYST-02**: Session digest template with all required fields
- [ ] **CRYST-03**: Fact extraction from digest content
- [ ] **CRYST-04**: Auto-crystallization triggers documentation

### Output Formats (OUT)

- [ ] **OUT-01**: Comparison table format with confidence display
- [ ] **OUT-02**: Mermaid timeline format
- [ ] **OUT-03**: Mermaid dependency graph format
- [ ] **OUT-04**: Marp slide deck format
- [ ] **OUT-05**: Structured export formats (JSON, CSV)
- [ ] **OUT-06**: Executive summary/brief format

### Templates (TMPL)

- [ ] **TMPL-01**: Schema template (.wiki/schema.md) with all entity/relationship types
- [ ] **TMPL-02**: Entity page template with typed YAML frontmatter
- [ ] **TMPL-03**: Session digest template
- [ ] **TMPL-04**: Index template with category-based navigation

### Python Scripts (SCR)

- [x] **SCR-01**: ingest.py — source ingestion with sensitive data filter
- [x] **SCR-02**: search.py — hybrid search with RRF fusion
- [x] **SCR-03**: lint.py — quality linter with auto-healing
- [x] **SCR-04**: consolidate.py — memory tier promotion + decay
- [x] **SCR-05**: graph.py — knowledge graph builder and querier
- [x] **SCR-06**: crystallize.py — session-to-digest pipeline

### Project Infrastructure (INFRA)

- [ ] **INFRA-01**: .gitignore with Python + macOS + IDE patterns
- [ ] **INFRA-02**: requirements.txt with pinned dependencies
- [ ] **INFRA-03**: pyproject.toml with black/isort/ruff/pytest config
- [ ] **INFRA-04**: MIT LICENSE
- [ ] **INFRA-05**: README.md with install/usage/capability docs

### Claude Code Integration (CC)

- [x] **CC-01**: CLAUDE.md with GSD workflow guidance
- [x] **CC-02**: Hook scripts in .claude/hooks/ for session start/end
- [x] **CC-03**: Eval test cases (5 scenarios)

### Testing (TEST)

- [x] **TEST-01**: Unit tests for sensitive data filtering
- [x] **TEST-02**: Unit tests for confidence scoring formulas
- [x] **TEST-03**: Unit tests for retention decay calculations
- [x] **TEST-04**: Integration test: full ingest pipeline
- [x] **TEST-05**: Integration test: full lint pass

## v2 Requirements

Deferred to future release.

### Advanced Features

- **ADV-01**: Full FAISS vector index integration (Level 5 search)
- **ADV-02**: Multi-agent mesh sync implementation
- **ADV-03**: Obsidian vault integration (bidirectional sync)
- **ADV-04**: Web dashboard for wiki browsing
- **ADV-05**: Slack/Discord notification hooks for wiki events

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time collaborative wiki editing | Not a real-time system; filesystem-based |
| Full database backend | Filesystem-first design; portability over performance |
| Mobile app | Skill is triggered within Claude Code sessions |
| Integration with Notion/Confluence | Separate integration effort; out of v1 scope |
| Multi-language wiki content | v1 focuses on English; i18n deferred |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SKILL-01 through SKILL-08 | Phase 1 | ✅ Complete |
| LIFE-01 through LIFE-05 | Phase 1 | ✅ Complete |
| GRAPH-01 through GRAPH-04 | Phase 1 | ✅ Complete |
| SEARCH-01 through SEARCH-05 | Phase 1 | ✅ Complete |
| AUTO-01 through AUTO-06 | Phase 1 | ✅ Complete |
| QUAL-01 through QUAL-05 | Phase 1 | ✅ Complete |
| COLLAB-01 through COLLAB-04 | Phase 1 | ✅ Complete |
| PRIV-01 through PRIV-04 | Phase 1 | ✅ Complete |
| CRYST-01 through CRYST-04 | Phase 1 | ✅ Complete |
| OUT-01 through OUT-06 | Phase 1 | ✅ Complete |
| TMPL-01 through TMPL-04 | Phase 1 | ✅ Complete |
| SCR-01 through SCR-06 | Phase 2 | ✅ Complete |
| INFRA-01 through INFRA-05 | Phase 3 | ✅ Complete |
| CC-01 through CC-03 | Phase 4 | ✅ Complete |
| TEST-01 through TEST-05 | Phase 5 | ✅ Complete |

**Coverage:**
- v1 requirements: 74 total
- Mapped to phases: 74
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-04*
*Last updated: 2026-05-04 after initial definition*
