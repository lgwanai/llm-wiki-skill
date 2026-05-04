#!/bin/bash
# llm-wiki: on_new_source Hook
# Auto-ingests files when the user drops or writes a source.
#
# Behavior:
# 1. Detect if a file was written/created by Claude (via CLAUDE_TOOL_NAME env var)
# 2. If the file looks like a source (markdown, text, code), auto-ingest it
# 3. Also accepts explicit file path as argument for manual trigger
#
# Usage:
#   .claude/hooks/on-new-source.sh [file_path]
#   (set as PreToolUse hook in .claude/settings.json for auto-detection)

set -euo pipefail

WIKI_DIR=".wiki"
WIKI_PATH="${CLAUDE_PROJECT_DIR:-$PWD}/$WIKI_DIR"
INGEST_SCRIPT="${CLAUDE_PROJECT_DIR:-$PWD}/scripts/ingest.py"

if [ ! -d "$WIKI_PATH" ]; then
    exit 0
fi

AUTO_INGEST=false
TARGET_FILE=""

# Case 1: Explicit file path argument (manual trigger)
if [ $# -ge 1 ] && [ -f "$1" ]; then
    TARGET_FILE="$1"
    AUTO_INGEST=true
fi

# Case 2: PreToolUse hook — Claude is about to write a file
if [ -n "${CLAUDE_TOOL_NAME:-}" ] && [ "${CLAUDE_TOOL_NAME}" = "Write" ]; then
    TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"
    FILE_PATH=$(echo "$TOOL_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_path',''))" 2>/dev/null || true)
    if [ -n "$FILE_PATH" ] && [ -f "$FILE_PATH" ]; then
        EXT="${FILE_PATH##*.}"
        case "$EXT" in
            md|txt|py|js|ts|tsx|json|yaml|yml|toml|rst|adoc)
                TARGET_FILE="$FILE_PATH"
                AUTO_INGEST=true
                ;;
        esac
    fi
fi

if $AUTO_INGEST && [ -n "$TARGET_FILE" ]; then
    echo "📥 Auto-ingesting: $TARGET_FILE"

    if [ -f "$INGEST_SCRIPT" ]; then
        if python3 "$INGEST_SCRIPT" "$TARGET_FILE" --embed 2>/dev/null; then
            echo "✓ Ingested successfully"
        else
            echo "⚠ Ingest completed with warnings"
        fi
    else
        echo "⚠ ingest.py not found — skipping auto-ingest"
    fi
fi
