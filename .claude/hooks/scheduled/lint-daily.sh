#!/bin/bash
# llm-wiki: on_lint_due Hook
# Runs quality lint on schedule (daily recommended).
#
# Set up via crontab:
#   0 9 * * * cd /path/to/project && .claude/hooks/scheduled/lint-daily.sh
#
# Or run manually:
#   .claude/hooks/scheduled/lint-daily.sh

set -euo pipefail

WIKI_DIR=".wiki"
WIKI_PATH="${CLAUDE_PROJECT_DIR:-$PWD}/$WIKI_DIR"
LINT_SCRIPT="${CLAUDE_PROJECT_DIR:-$PWD}/scripts/lint.py"

if [ ! -d "$WIKI_PATH" ]; then
    echo "Wiki not initialized — skipping lint"
    exit 0
fi

if [ ! -f "$LINT_SCRIPT" ]; then
    echo "lint.py not found"
    exit 1
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
REPORT_DIR="$WIKI_PATH/reports"
mkdir -p "$REPORT_DIR"
REPORT_FILE="$REPORT_DIR/lint-$(date +%Y-%m-%d).md"

echo "🔍 Running wiki lint — $TIMESTAMP"
python3 "$LINT_SCRIPT" --auto-heal --report-file "$REPORT_FILE" 2>&1

echo "✓ Lint complete — report: $REPORT_FILE"
