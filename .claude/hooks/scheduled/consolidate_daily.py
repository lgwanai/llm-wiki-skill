#!/usr/bin/env python
"""llm-wiki: Daily Consolidation Hook

Runs memory consolidation across tiers and decay.
Intended to be run as a scheduled/cron task.

Replaces: .claude/hooks/scheduled/consolidate-daily.sh
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow importing from scripts/ directory
_project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from scripts._hook_utils import (  # noqa: E402
    get_project_root,
    get_wiki_dir,
    wiki_dir_exists,
    run_python_script,
)


def main() -> None:
    root = get_project_root()

    if not wiki_dir_exists(root):
        wiki_path = get_wiki_dir(root)
        print(f"Wiki not found at {wiki_path} — skipping daily consolidation")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{timestamp}] Starting daily consolidation...")

    # Consolidate across tiers
    result = run_python_script(
        "consolidate.py",
        ["--tiers", "working,episodic,semantic"],
        root=root,
    )
    if result.returncode != 0:
        print("⚠ Consolidation completed with warnings")

    # Run decay
    decay_result = run_python_script("consolidate.py", ["--decay-only"], root=root)
    if decay_result.returncode != 0:
        print("⚠ Decay completed with warnings")

    print("[✓] Daily consolidation complete")


if __name__ == "__main__":
    main()
