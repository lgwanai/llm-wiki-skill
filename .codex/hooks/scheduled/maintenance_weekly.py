#!/usr/bin/env python
"""llm-wiki: Weekly Maintenance Hook

Runs comprehensive wiki maintenance: lint, consolidate, stats, and schema review.
Generates a weekly report markdown file.

Replaces: .claude/hooks/scheduled/maintenance-weekly.sh

This version fixes a bug from the original shell script:
  - The shell script used 'stat -f %Sm' which is macOS/BSD-specific
    and fails on Linux and Windows.
  - The Python version uses os.path.getmtime() which works everywhere.
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
    file_mod_time,
)


def main() -> None:
    root = get_project_root()

    if not wiki_dir_exists(root):
        wiki_path = get_wiki_dir(root)
        print(f"Wiki not found at {wiki_path} — skipping weekly maintenance")
        return

    wiki_path = get_wiki_dir(root)
    reports_dir = wiki_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    week_str = datetime.now(timezone.utc).strftime("%Y-W%W")
    report_path = reports_dir / f"weekly-{week_str}.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"[{timestamp}] Starting weekly maintenance...")

    lines: list[str] = []
    lines.append(f"# Weekly Maintenance Report — {week_str}")
    lines.append(f"**Generated**: {timestamp}")
    lines.append("")

    # --- Lint ---
    lines.append("## 1. Quality Checks (Lint)")
    lines.append("")
    lint_result = run_python_script(
        "lint.py",
        ["--auto-heal"],
        root=root,
        capture=True,
    )
    if lint_result.stdout.strip():
        # Include last 10 lines of lint output as summary
        lint_lines = lint_result.stdout.strip().split("\n")
        for line in lint_lines[-10:]:
            lines.append(f"  {line}")
    if lint_result.returncode != 0:
        lines.append("")
        lines.append("⚠ Lint completed with warnings")
    lines.append("")

    # --- Consolidation ---
    lines.append("## 2. Memory Consolidation")
    lines.append("")
    cons_result = run_python_script(
        "consolidate.py",
        ["--tiers", "working,episodic,semantic"],
        root=root,
        capture=True,
    )
    if cons_result.stdout.strip():
        cons_lines = cons_result.stdout.strip().split("\n")
        for line in cons_lines[-10:]:
            lines.append(f"  {line}")
    if cons_result.returncode != 0:
        lines.append("")
        lines.append("⚠ Consolidation completed with warnings")
    lines.append("")

    # --- Graph Stats ---
    lines.append("## 3. Graph Statistics")
    lines.append("")
    stats_result = run_python_script(
        "wiki.py",
        ["graph-stats"],
        root=root,
        capture=True,
    )
    if stats_result.stdout.strip():
        for line in stats_result.stdout.strip().split("\n"):
            lines.append(f"  {line}")
    lines.append("")

    # --- Schema Review ---
    lines.append("## 4. Schema Review")
    lines.append("")
    schema_path = wiki_path / "schema.md"
    if schema_path.is_file():
        try:
            mtime = file_mod_time(schema_path)
            lines.append(f"  Schema last modified: {mtime.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        except OSError:
            lines.append("  Schema exists (mod time unavailable)")
    else:
        lines.append("  ⚠ No schema.md found — wiki may lack type definitions")
    lines.append("")

    # --- Write Report ---
    report_content = "\n".join(lines)
    report_path.write_text(report_content, encoding="utf-8")
    print(f"[✓] Weekly maintenance complete — report: {report_path}")


if __name__ == "__main__":
    main()
