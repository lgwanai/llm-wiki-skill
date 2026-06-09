#!/usr/bin/env python
"""llm-wiki: Daily Lint Hook

Runs quality checks on the wiki and generates a lint report.
Intended to be run as a scheduled/cron task.

Replaces: .claude/hooks/scheduled/lint-daily.sh
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
        print(f"Wiki not found at {wiki_path} — skipping daily lint")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{timestamp}] Starting daily quality check...")

    wiki_path = get_wiki_dir(root)
    reports_dir = wiki_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_filename = datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".md"
    report_path = reports_dir / report_filename

    result = run_python_script(
        "lint.py",
        ["--auto-heal", "--report-file", str(report_path)],
        root=root,
    )
    if result.returncode != 0:
        print("⚠ Lint completed with warnings — check report for details")

    print(f"[✓] Daily lint complete — report: {report_path}")


if __name__ == "__main__":
    main()
