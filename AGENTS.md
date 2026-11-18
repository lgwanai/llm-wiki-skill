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

### AI resource readiness

At the start of work that integrates a model or Agent, tell the user what AI
resources the flow needs and who supplies them. Confirm the host Agent is
available for Agent mode. For standalone model calls, surface the endpoint,
model ID, and API key requirements before implementation or ingestion. Reuse an
existing confirmed connection. Ask users to configure credentials through an
environment variable or secret store and report any access or quota constraints
before committing to the workflow.

## Current State

All 7 project phases are complete. Run `python -m pytest -q` for the current test status.

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
