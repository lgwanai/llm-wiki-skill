#!/usr/bin/env bash
# package.sh — Build distributable skill zip to dist/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATE=$(date +%Y-%m-%d)
OUTPUT="$ROOT/dist/llm-wiki-skill-${DATE}.zip"

cd "$ROOT"
mkdir -p dist

find scripts -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
rm -f dist/llm-wiki-skill-*.zip

zip -r "$OUTPUT" \
  SKILL.md README.md pyproject.toml requirements.txt \
  wiki_config.yaml.example \
  scripts/ references/ templates/ .claude/ \
  -x "*.pyc" "*/__pycache__/*" ".DS_Store" \
  -x ".wiki/*" ".planning/*" ".git/*" "tests/*" "dist/*" \
  -x "wiki_config.yaml" ".env*" ".claude/cache/*" \
  -x "scripts/package.sh"

echo "Packaged: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
