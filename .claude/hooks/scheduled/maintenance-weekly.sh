#!/bin/bash
# llm-wiki: on_schedule Hook — Weekly Maintenance
# Runs comprehensive wiki maintenance: lint, consolidate, stats, schema review.
#
# Set up via crontab:
#   0 8 * * 1 cd /path/to/project && .claude/hooks/scheduled/maintenance-weekly.sh
#
# Or run manually:
#   .claude/hooks/scheduled/maintenance-weekly.sh

set -euo pipefail

WIKI_DIR=".wiki"
WIKI_PATH="${CLAUDE_PROJECT_DIR:-$PWD}/$WIKI_DIR"
SCRIPTS_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/scripts"

if [ ! -d "$WIKI_PATH" ]; then
    echo "Wiki not initialized — skipping maintenance"
    exit 0
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
REPORT_DIR="$WIKI_PATH/reports"
mkdir -p "$REPORT_DIR"
WEEKLY_REPORT="$REPORT_DIR/maintenance-$(date +%Y-%m-%d).md"

{
    echo "# Wiki Maintenance Report"
    echo ""
    echo "**Date:** $TIMESTAMP"
    echo ""

    echo "## 1. Quality Lint"
    echo ""
    if [ -f "$SCRIPTS_DIR/lint.py" ]; then
        python3 "$SCRIPTS_DIR/lint.py" --auto-heal 2>&1 | tail -20
    else
        echo "⚠ lint.py not found"
    fi
    echo ""

    echo "## 2. Memory Consolidation"
    echo ""
    if [ -f "$SCRIPTS_DIR/consolidate.py" ]; then
        python3 "$SCRIPTS_DIR/consolidate.py" 2>&1 | tail -20
    else
        echo "⚠ consolidate.py not found"
    fi
    echo ""

    echo "## 3. Graph Statistics"
    echo ""
    if [ -f "$SCRIPTS_DIR/graph.py" ]; then
        python3 "$SCRIPTS_DIR/graph.py" stats 2>&1
    else
        echo "⚠ graph.py not found"
    fi
    echo ""

    echo "## 4. Schema Review"
    echo ""
    if [ -f "$WIKI_PATH/schema.md" ]; then
        echo "Schema exists. Review for needed updates."
        echo "Last modified: $(stat -f '%Sm' "$WIKI_PATH/schema.md" 2>/dev/null || date -r "$WIKI_PATH/schema.md" 2>/dev/null || echo 'unknown')"
    else
        echo "⚠ schema.md not found — wiki may not be fully initialized"
    fi
    echo ""

    echo "---"
    echo "*Report generated: $TIMESTAMP*"

} > "$WEEKLY_REPORT"

echo "✓ Weekly maintenance complete — report: $WEEKLY_REPORT"
