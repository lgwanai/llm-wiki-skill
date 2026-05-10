#!/bin/bash
# package.sh — Package llm-wiki-skill for distribution
# Creates a date-stamped zip archive in dist/

set -e

DATE=$(date +%Y-%m-%d)
DIST_DIR="dist"
PACKAGE_NAME="llm-wiki-skill-${DATE}.zip"

mkdir -p "$DIST_DIR"

zip -r "$DIST_DIR/$PACKAGE_NAME" \
  SKILL.md \
  README.md \
  LICENSE \
  CLAUDE.md \
  pyproject.toml \
  requirements.txt \
  scripts/ \
  references/ \
  templates/ \
  evals/ \
  .claude/ \
  -x "*.pyc" \
  -x "*__pycache__*" \
  -x "*.egg-info*" \
  -x ".DS_Store"

echo ""
echo "Package created: $DIST_DIR/$PACKAGE_NAME"
ls -lh "$DIST_DIR/$PACKAGE_NAME"