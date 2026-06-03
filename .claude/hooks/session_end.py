#!/usr/bin/env python
"""llm-wiki: Session End Hook

Crystallizes the working session into the wiki at session end.
Runs automatically — no user action needed.

Replaces: .claude/hooks/session-end.sh
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
    run_python_script,
    print_hook_header,
)


def main() -> None:
    root = get_project_root()

    if not wiki_dir_exists(root):
        return

    wiki_path = get_wiki_dir(root)
    print_hook_header("Session End")
    print(f"\n🧊 Crystallizing session to wiki — {wiki_path}")

    crystallize_script = root / "scripts" / "crystallize.py"
    if crystallize_script.is_file():
        result = run_python_script("crystallize.py", ["--auto"], root=root)
        if result.returncode != 0:
            print("⚠ Crystallization script ran with warnings — check wiki for completeness")
    else:
        print("⚠ crystallize.py not found — session not captured")
        print("  Run 'crystallize session' manually to file insights")

    print("✓ Session end hook complete")


if __name__ == "__main__":
    main()
