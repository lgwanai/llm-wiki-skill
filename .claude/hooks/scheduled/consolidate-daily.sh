#!/bin/bash
# llm-wiki: on_consolidation_due Hook
# Runs memory consolidation on schedule (daily recommended).
#
# Set up via crontab:
#   0 10 * * * cd /path/to/project && .claude/hooks/scheduled/consolidate-daily.sh
#
# Or run manually:
#   .claude/hooks/scheduled/consolidate-daily.sh

set -euo pipefail

WIKI_DIR=".wiki"
WIKI_PATH="${CLAUDE_PROJECT_DIR:-$PWD}/$WIKI_DIR"
CONSOLIDATE_SCRIPT="${CLAUDE_PROJECT_DIR:-$PWD}/scripts/consolidate.py"

if [ ! -d "$WIKI_PATH" ]; then
    echo "Wiki not initialized — skipping consolidation"
    exit 0
fi

if [ ! -f "$CONSOLIDATE_SCRIPT" ]; then
    echo "consolidate.py not found"
    exit 1
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "🧠 Running memory consolidation — $TIMESTAMP"
python3 "$CONSOLIDATE_SCRIPT" --tiers working,episodic,semantic 2>&1

echo ""
echo "📉 Applying retention decay..."
python3 "$CONSOLIDATE_SCRIPT" --decay-only 2>&1

echo "✓ Consolidation complete"
