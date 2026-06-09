#!/usr/bin/env python
"""llm-wiki: Session Start Hook

Injects wiki context at the beginning of each Claude Code session.
This is a read-only hook — it surfaces context but doesn't modify anything.

Replaces: .claude/hooks/session-start.sh
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing from scripts/ directory
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from scripts._hook_utils import (  # noqa: E402
    get_project_root,
    get_wiki_dir,
    wiki_dir_exists,
    print_hook_header,
)


def main() -> None:
    root = get_project_root()

    if not wiki_dir_exists(root):
        # Wiki not yet initialized — skip silently
        return

    wiki_path = get_wiki_dir(root)

    print_hook_header("Session Start")
    print(f"\n📚 Wiki context loaded — {wiki_path}")
    print()

    # Show entity count if graph exists
    entities_file = wiki_path / "graph" / "entities.json"
    if entities_file.is_file():
        try:
            import json

            data = json.loads(entities_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                count = len(data)
            elif isinstance(data, list):
                count = len(data)
            else:
                count = "?"
        except Exception:
            count = "?"
        print(f"Entities: {count}")

    # Show recent session digests
    sessions_dir = wiki_path / "pages" / "sessions"
    if sessions_dir.is_dir():
        session_files = sorted(
            sessions_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:3]
        if session_files:
            print("Recent sessions:")
            for f in session_files:
                print(f"  - {f.stem}")

    print()
    print("Commands: ingest source | search wiki | lint wiki | crystallize session")


if __name__ == "__main__":
    main()
