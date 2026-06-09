# AGENTS.md — llm-wiki-skill

## Project Identity

This is **llm-wiki-skill** — a Codex skill implementing LLM Wiki v2, a production-hardened pattern for building personal knowledge bases. See `.planning/PROJECT.md` for full context.

## Workflow

This project uses **GSD** (Get Shit Done) for structured development. Key commands:

- `/gsd-progress` — Check current phase status and next actions
- `/gsd-discuss-phase <N>` — Gather context before planning
- `/gsd-plan-phase <N>` — Create detailed plan for a phase
- `/gsd-execute-phase <N>` — Execute a phase
- `/gsd-settings` — Adjust workflow preferences

## Current State

All 7 phases complete. 44/50 tests passing (6 skipped pending lazy WIKI_DIR init). Production-ready.

Key scripts: `wiki.py` (CLI), `compile_v2.py` (LLM compile pipeline), `query.py` (search + answer).

## Coding Standards

### Python (scripts/)
- PEP 8 via ruff + black
- Type annotations on all function signatures
- Use `scripts/__init__.py` for package imports
- Skeleton scripts: implement the TODO markers, don't change function signatures

### Markdown (SKILL.md, references/, templates/)
- YAML frontmatter required on wiki templates
- Wikilinks use `[[double brackets]]` format
- Reference files are loaded on demand by the LLM

### Project Configuration
- See `pyproject.toml` for formatter/linter settings
- See `requirements.txt` for dependencies

## Key Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill — triggers and core workflows |
| `references/*.md` | Deep-dive pattern documentation |
| `templates/*.md` | Reusable wiki page templates |
| `scripts/*.py` | Automation scripts (skeletons → implementation) |
| `.planning/PROJECT.md` | Living project context |
| `.planning/ROADMAP.md` | Phase structure and success criteria |
| `.planning/REQUIREMENTS.md` | Checkable requirements with traceability |
