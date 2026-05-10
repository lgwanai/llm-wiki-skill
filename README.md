# llm-wiki-skill

A Claude Code skill implementing **LLM Wiki v2** — a production-hardened pattern for building personal knowledge bases that compound over time with LLM-powered automation.

> This builds on two foundational designs:
>
> **LLM Wiki** (Karpathy) — [gist.github.com/karpathy/442a6bf555914893e9891c11519de94f](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
> The original pattern: three-layer architecture (raw sources → wiki → schema), index+log, entity/concept pages, compoundable knowledge.
>
> **LLM Wiki v2** (Rohit Ghumare) — [gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)
> Production hardening with [agentmemory](https://github.com/rohitg00/agentmemory): hybrid search (BM25+vector+graph), compile pipeline, lifecycle management, consolidation tiers.

## Quick Start

### Installation

Copy this directory to your Claude Code skills directory:

```bash
cp -r llm-wiki-skill ~/.claude/skills/llm-wiki/
```

Or register in `.claude/settings.json`:

```json
{
  "skills": {
    "paths": ["~/workspace/llm-wiki-skill"]
  }
}
```

### First Use

In any Claude Code session, say:
- "Set up a wiki for this project"
- "Build a knowledge base"
- "Start tracking what we learn"

The skill triggers and guides you through Level 1 setup — creating `.wiki/` directory
structure, schema, and index.

## What This Skill Does

When triggered, Claude becomes a disciplined knowledge librarian that:

1. **Converts sources** — URLs, files, documents → Markdown using appropriate tools
2. **Ingests sources** — extracts entities, builds knowledge graph, creates structured pages
3. **Answers questions** — searches across wiki pages, graph, and embeddings with confidence scores
4. **Maintains quality** — auto-lints, detects contradictions, heals broken links
5. **Consolidates knowledge** — promotes observations through memory tiers, applies retention decay
6. **Crystallizes sessions** — distills working sessions into digestible summaries that compound over time

## Source Conversion Pipeline

Automatically convert any input to Markdown and build your wiki:

| Input | Tool | Command |
|-------|------|---------|
| URLs | lightpanda + ReaderLM-v2 | `wiki add <url>` |
| PDFs/Images | PaddleOCR-VL (remote) | `wiki add <file>` |
| Office docs | markitdown | `wiki add <file>` |
| Code/Text | Direct read | `wiki add <file>` |
| Raw content | None | `wiki add "text"` |

**Unified CLI:**
```bash
wiki add <source>     # Add source & build wiki
wiki query <query>    # Search wiki
wiki lint             # Quality check
wiki status           # Wiki statistics
wiki init             # Initialize structure
```

**Requirements:**
- lightpanda: Install from https://lightpanda.io/docs/open-source/installation
- ReaderLM-v2 API: configure in `scripts/wiki_config.yaml` (see `wiki_config.yaml.example`)

## Capability Levels

Choose your starting point based on needs:

| Level | Capabilities | When to use |
|-------|-------------|-------------|
| **1 — Minimal Wiki** | Manual ingest, query, lint. Flat pages + index. | Getting started. Runs in minutes. |
| **2 — Lifecycle** | Confidence scoring, supersession, decay, memory tiers. | When wiki accumulates noise. |
| **3 — Structure** | Entity extraction, typed relationships, graph traversal. | When flat pages aren't enough. |
| **4 — Automation** | Auto-ingest, auto-lint, context injection, crystallization. | When maintenance becomes burden. |
| **5 — Scale + Collab** | Hybrid search, mesh sync, shared/private scoping. | Teams, 500+ pages, multi-agent. |

See `references/implementation-spectrum.md` for detailed setup guides at each level.

## Project Structure

```
llm-wiki-skill/
├── SKILL.md                         # Main skill — triggers, workflows, reference pointers
├── README.md                        # This file
├── LICENSE                          # MIT
├── pyproject.toml                   # Python project configuration
├── requirements.txt                 # Python dependencies
│
├── references/                      # Deep-dive pattern docs (loaded on demand)
│   ├── lifecycle.md                 # Confidence scoring, supersession, forgetting
│   ├── knowledge-graph.md           # Entity extraction, typed relationships
│   ├── hybrid-search.md             # BM25 + vector + graph fusion
│   ├── automation.md                # Event hooks, schedules
│   ├── quality.md                   # Scoring, self-healing, contradiction resolution
│   ├── collaboration.md             # Mesh sync, shared/private scoping
│   ├── privacy-governance.md        # Filtering, audit trails
│   ├── crystallization.md           # Session → digest pipeline
│   ├── output-formats.md            # Tables, timelines, graphs, slides
│   └── implementation-spectrum.md   # Level-by-level upgrade guide
│
├── templates/                       # Reusable page templates
│   ├── schema.md                    # Wiki schema — the most important file
│   ├── entity-page.md               # Entity page with typed YAML frontmatter
│   ├── session-digest.md            # Crystallized session summary
│   └── index.md                     # Human-readable catalog
│
├── scripts/                         # Automation scripts (Python)
│   ├── wiki.py                      # Unified CLI (add, query, lint, status, init)
│   ├── ingest.py                    # Source ingestion + entity extraction
│   ├── url2markdown.py              # URL → Markdown (lightpanda + ReaderLM)
│   ├── search.py                    # Hybrid search engine
│   ├── lint.py                      # Quality linter with auto-healing
│   ├── consolidate.py               # Memory tier promotion + decay
│   ├── graph.py                     # Knowledge graph builder & querier
│   └── crystallize.py               # Session → digest pipeline
│
└── evals/                           # Test cases for skill evaluation
    └── evals.json
```

## Configuration

### Wiki Configuration

After setup, `.wiki/config.json` controls wiki behavior:

```json
{
  "hooks": {
    "on_new_source": { "enabled": true, "auto_ingest": true },
    "on_session_start": { "enabled": true, "context_injection": true },
    "on_session_end": { "enabled": true, "auto_crystallize": true }
  },
  "retention": {
    "architecture_decisions": { "half_life_days": 180 },
    "project_facts": { "half_life_days": 90 },
    "bug_reports": { "half_life_days": 14 }
  },
  "quality": {
    "auto_heal": true,
    "min_score": 0.4
  }
}
```

### Schema Co-Evolution

The wiki schema (`.wiki/schema.md`) is the most critical file. It encodes entity types,
relationship types, ingest rules, quality standards, and consolidation schedules. You
and Claude co-evolve it over time. Share it with someone in a similar domain and they
get a running start.

## Python Setup (for scripts)

If you plan to use the automation scripts:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For Level 5 search features:
```bash
pip install -r requirements.txt  # includes sentence-transformers, faiss-cpu
```

## Hooks Configuration

Hooks automate wiki operations at key points in your workflow. The skill includes
pre-configured hooks in `.claude/hooks/` that you can enable in your project.

### Available Hooks

| Hook | Trigger | Purpose |
|------|---------|---------|
| `session-start.sh` | Session start | Inject wiki context (entity count, recent sessions) |
| `session-end.sh` | Session end | Crystallize session insights to wiki |
| `on-new-source.sh` | File written | Auto-ingest new markdown/text/code files |
| `scheduled/lint-daily.sh` | Cron/schedule | Daily quality check with auto-heal |
| `scheduled/consolidate-daily.sh` | Cron/schedule | Daily memory tier consolidation |
| `scheduled/maintenance-weekly.sh` | Cron/schedule | Weekly cleanup and health check |

### Enable Hooks

Add to your project's `.claude/settings.json`:

```json
{
  "skills": {
    "paths": ["~/workspace/llm-wiki-skill"]
  },
  "hooks": {
    "SessionStart": [
      {
        "command": ".claude/hooks/session-start.sh",
        "description": "llm-wiki: inject wiki context"
      }
    ],
    "PreToolUse": [
      {
        "command": ".claude/hooks/on-new-source.sh",
        "description": "llm-wiki: auto-ingest sources"
      }
    ],
    "Stop": [
      {
        "command": ".claude/hooks/session-end.sh",
        "description": "llm-wiki: crystallize session"
      }
    ]
  }
}
```

### Schedule Hooks (Cron Configuration)

Cron jobs run maintenance tasks automatically at scheduled times.

#### Step 1: Verify Script Paths

First, ensure scripts are executable and paths are correct:

```bash
# Check your project directory
PROJECT_DIR="$HOME/workspace/llm-wiki-skill"
cd "$PROJECT_DIR"

# Verify scripts exist
ls -la scripts/lint.py scripts/consolidate.py

# Verify hooks exist
ls -la .claude/hooks/scheduled/

# Make scripts executable (if needed)
chmod +x scripts/*.py .claude/hooks/scheduled/*.sh
```

#### Step 2: Open Crontab Editor

```bash
crontab -e
```

If prompted to choose an editor, select one (nano is beginner-friendly):
- `1` for nano
- `2` for vim.basic
- `3` for vim.tiny

#### Step 3: Add Cron Entries

Paste these lines at the end of the crontab file (adjust `PROJECT_DIR` path):

```cron
# llm-wiki scheduled maintenance
# Daily lint at 9:00 AM
0 9 * * * cd /Users/wuliang/workspace/llm-wiki-skill && /usr/bin/python3 scripts/lint.py --auto-heal --report-file .wiki/reports/lint-$(date +\%Y-\%m-\%d).md >> .wiki/logs/cron.log 2>&1

# Daily consolidation at 10:00 AM
0 10 * * * cd /Users/wuliang/workspace/llm-wiki-skill && /usr/bin/python3 scripts/consolidate.py >> .wiki/logs/cron.log 2>&1

# Weekly maintenance on Monday at 8:00 AM
0 8 * * 1 cd /Users/wuliang/workspace/llm-wiki-skill && .claude/hooks/scheduled/maintenance-weekly.sh >> .wiki/logs/cron.log 2>&1
```

**Replace `/Users/wuliang/workspace/llm-wiki-skill` with your actual project path.**

#### Step 4: Create Log Directory

```bash
mkdir -p .wiki/logs
touch .wiki/logs/cron.log
```

#### Step 5: Save and Verify

Save the crontab (Ctrl+O, Enter, Ctrl+X in nano). Then verify:

```bash
# List current cron jobs
crontab -l

# Check log file exists
ls -la .wiki/logs/cron.log
```

#### Cron Time Format

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sunday=0)
│ │ │ │ │
* * * * * command
```

**Common patterns:**

| Schedule | Cron expression |
|----------|-----------------|
| Every day at 9:00 AM | `0 9 * * *` |
| Every hour | `0 * * * *` |
| Every Monday 8:00 AM | `0 8 * * 1` |
| Every 6 hours | `0 */6 * * *` |
| First day of month | `0 9 1 * *` |

#### Step 6: Test Cron Job

Force a cron job to run now (for testing):

```bash
# Run lint immediately
cd /Users/wuliang/workspace/llm-wiki-skill && python3 scripts/lint.py --auto-heal

# Run consolidation immediately
cd /Users/wuliang/workspace/llm-wiki-skill && python3 scripts/consolidate.py

# Check the log
cat .wiki/logs/cron.log
```

#### Step 7: Monitor Cron Logs

After cron runs, check logs and reports:

```bash
# View cron execution log
tail -50 .wiki/logs/cron.log

# View generated lint reports
ls -la .wiki/reports/
cat .wiki/reports/lint-*.md | head -30

# View maintenance reports
cat .wiki/reports/maintenance-*.md | head -50
```

#### Troubleshooting

**Problem: Cron not running**

1. Check cron service is active:
   ```bash
   # macOS
   sudo service cron status  # or: launchctl list | grep cron
   
   # Linux
   systemctl status cron
   ```

2. Check script permissions:
   ```bash
   ls -la scripts/lint.py scripts/consolidate.py
   # Should show: -rwxr-xr-x (executable)
   
   # Fix if needed:
   chmod +x scripts/*.py
   ```

3. Check Python path:
   ```bash
   which python3
   # Use full path in cron: /usr/bin/python3 or /usr/local/bin/python3
   ```

4. Check working directory in cron entry:
   ```bash
   # Must use `cd /path/to/project &&` before command
   # NOT: python3 /path/to/project/scripts/lint.py (wrong - relative paths fail)
   ```

**Problem: Permission denied**

```bash
# Fix script permissions
chmod +x scripts/*.py .claude/hooks/scheduled/*.sh

# Fix wiki directory permissions
chmod -R u+w .wiki/
```

**Problem: Command not found**

Use full paths in cron:

```cron
# Use full Python path
0 9 * * * cd /Users/wuliang/workspace/llm-wiki-skill && /usr/local/bin/python3 scripts/lint.py >> .wiki/logs/cron.log 2>&1
```

Find Python path:
```bash
which python3
# Output: /usr/local/bin/python3 (use this)
```

#### Disable Scheduled Hooks

To disable a cron job, remove the line from crontab:

```bash
crontab -e
# Delete the lines you want to disable
# Save and exit
crontab -l  # Verify changes
```

Or comment out (add `#` prefix):

```cron
# Disabled: 0 9 * * * cd /path/to/project && python3 scripts/lint.py
```

### Disable Hooks

Remove the corresponding entry from `.claude/settings.json` or set `enabled: false`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": ".claude/hooks/session-start.sh",
        "description": "llm-wiki: inject wiki context",
        "enabled": false
      }
    ]
  }
}
```

## Distribution

Package the skill for distribution:

```bash
./package.sh
# Output: dist/llm-wiki-skill-YYYY-MM-DD.zip
```

## License

MIT — see LICENSE file.

## References

- [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — original concept
- [agentmemory](https://github.com/rohitg00/agentmemory) — persistent memory engine for AI agents
- [Design blueprint](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2) — full v2 specification
