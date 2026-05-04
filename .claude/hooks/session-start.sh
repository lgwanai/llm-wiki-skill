#!/bin/bash
# llm-wiki: Session Start Hook
# Injects wiki context at the beginning of each Claude Code session.
#
# Behavior:
# 1. Check if .wiki/ directory exists (wiki is initialized)
# 2. If exists, find relevant context based on recent activity
# 3. Surface top entities and recent session digests to Claude
#
# This hook is read-only — it surfaces context but doesn't modify anything.

set -euo pipefail

WIKI_DIR=".wiki"
WIKI_PATH="${CLAUDE_PROJECT_DIR:-$PWD}/$WIKI_DIR"

if [ ! -d "$WIKI_PATH" ]; then
    # Wiki not yet initialized — skip silently
    exit 0
fi

# Surface the wiki state as context for this session
echo "📚 Wiki context loaded — $WIKI_PATH"
echo ""

# Show entity count if graph exists
if [ -f "$WIKI_PATH/graph/entities.json" ]; then
    ENTITY_COUNT=$(python3 -c "import json; d=json.load(open('$WIKI_PATH/graph/entities.json')); print(len(d))" 2>/dev/null || echo "?")
    echo "Entities: $ENTITY_COUNT"
fi

# Show recent session digests
if [ -d "$WIKI_PATH/pages/sessions" ]; then
    RECENT=$(ls -t "$WIKI_PATH/pages/sessions"/*.md 2>/dev/null | head -3 || true)
    if [ -n "$RECENT" ]; then
        echo "Recent sessions:"
        for f in $RECENT; do
            echo "  - $(basename "$f" .md)"
        done
    fi
fi

echo ""
echo "Commands: ingest source | search wiki | lint wiki | crystallize session"
