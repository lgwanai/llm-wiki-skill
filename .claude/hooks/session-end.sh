#!/bin/bash
# llm-wiki: Session End Hook
# Crystallizes the working session into the wiki at session end.
#
# Behavior:
# 1. Check if .wiki/ directory exists
# 2. If exists and crystallize.py is available, auto-crystallize the session
# 3. Promote observations to working memory
#
# This runs automatically — no user action needed.

set -euo pipefail

WIKI_DIR=".wiki"
WIKI_PATH="${CLAUDE_PROJECT_DIR:-$PWD}/$WIKI_DIR"
CRYSTALLIZE_SCRIPT="${CLAUDE_PROJECT_DIR:-$PWD}/scripts/crystallize.py"

if [ ! -d "$WIKI_PATH" ]; then
    exit 0
fi

echo "🧊 Crystallizing session to wiki..."

# If crystallize.py exists and is executable, run it
if [ -f "$CRYSTALLIZE_SCRIPT" ]; then
    python3 "$CRYSTALLIZE_SCRIPT" --auto 2>/dev/null || {
        echo "⚠ Crystallization script ran with warnings — check wiki for completeness"
    }
else
    echo "⚠ crystallize.py not found — session not captured"
    echo "  Run 'crystallize session' manually to file insights"
fi

echo "✓ Session end hook complete"
