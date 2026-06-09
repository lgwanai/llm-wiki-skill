#!/usr/bin/env python
"""llm-wiki: on_new_source Hook

Auto-ingests files when Claude writes or creates a source document.
Detects file creation via CLAUDE_TOOL_NAME env var (PreToolUse hook).

Replaces: .claude/hooks/on-new-source.sh
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow importing from scripts/ directory
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from scripts._hook_utils import (  # noqa: E402
    get_project_root,
    get_wiki_dir,
    wiki_dir_exists,
    run_python_script,
)


# File extensions that trigger auto-ingestion
ALLOWED_EXTENSIONS = frozenset({
    ".md", ".txt", ".py", ".js", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".rst", ".adoc",
})


def main() -> None:
    root = get_project_root()

    if not wiki_dir_exists(root):
        return

    wiki_path = get_wiki_dir(root)
    auto_ingest = False
    target_file = ""

    # Case 1: Explicit file path argument (manual trigger)
    if len(sys.argv) >= 2:
        explicit_path = Path(sys.argv[1])
        if explicit_path.is_file():
            target_file = str(explicit_path)
            auto_ingest = True

    # Case 2: PreToolUse hook — Claude is about to write a file
    if not auto_ingest:
        tool_name = os.environ.get("CLAUDE_TOOL_NAME", "")
        if tool_name in ("Write", "Edit"):
            tool_input_raw = os.environ.get("CLAUDE_TOOL_INPUT", "")
            if tool_input_raw:
                try:
                    tool_input = json.loads(tool_input_raw)
                    file_path_str = tool_input.get("file_path", "")
                    if file_path_str:
                        fp = Path(file_path_str)
                        if fp.is_file():
                            ext = fp.suffix.lower()
                            if ext in ALLOWED_EXTENSIONS:
                                target_file = str(fp)
                                auto_ingest = True
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass

    if not auto_ingest or not target_file:
        return

    print(f"\n📥 Auto-ingesting: {target_file}")

    wiki_script = root / "scripts" / "wiki.py"
    if not wiki_script.is_file():
        print("⚠ wiki.py not found — skipping auto-ingest")
        return

    # Compile
    result = run_python_script("wiki.py", ["compile", target_file], root=root)
    if result.returncode == 0:
        print("✓ Compiled successfully")
        # Update embeddings
        embed_result = run_python_script("wiki.py", ["embed"], root=root)
        if embed_result.returncode == 0:
            print("✓ Embeddings updated")
    else:
        print("⚠ Compilation completed with warnings or failed")


if __name__ == "__main__":
    main()
