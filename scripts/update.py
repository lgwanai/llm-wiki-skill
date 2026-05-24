#!/usr/bin/env python3
"""update.py — Pull latest skill code from GitHub, backup old files to backup/."""

import os
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO_URL = "https://github.com/lgwanai/llm-wiki-skill"
ROOT = Path(__file__).parent.parent
BACKUP_DIR = ROOT / "backup"


def cmd_update():
    print("=" * 60)
    print("llm-wiki-skill update")
    print("=" * 60)

    # Step 1: Backup current files
    print("\n[1/3] Backing up current files...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"llm-wiki-{timestamp}.tar.gz"
    backup_path = BACKUP_DIR / backup_name

    exclude_dirs = {".git", "__pycache__", ".venv", "venv", "dist", "backup", ".wiki"}
    files_to_backup = []
    for f in ROOT.rglob("*"):
        if f.is_dir():
            continue
        parts = f.relative_to(ROOT).parts
        if any(p in exclude_dirs for p in parts):
            continue
        files_to_backup.append(f)

    with tarfile.open(backup_path, "w:gz") as tar:
        for f in sorted(files_to_backup):
            rel = f.relative_to(ROOT)
            tar.add(str(f), arcname=str(rel))

    size_kb = backup_path.stat().st_size / 1024
    print(f"  Created: {backup_name} ({size_kb:.0f} KB, {len(files_to_backup)} files)")

    # Step 2: Git pull
    print("\n[2/3] Pulling latest code...")
    os.chdir(ROOT)
    try:
        result = subprocess.run(
            ["git", "pull", "--rebase"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  {result.stdout.strip()}")
        else:
            print(f"  WARNING: git pull failed: {result.stderr.strip()}")
    except FileNotFoundError:
        print("  ERROR: git not found. Install git first.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("  ERROR: git pull timed out. Check network.")

    # Step 3: Report
    print("\n[3/3] Summary")
    backups = sorted(BACKUP_DIR.glob("*.tar.gz"))
    print(f"  Backups: {len(backups)} total in {BACKUP_DIR}/")
    for b in backups[-5:]:
        print(f"    {b.name}")
    print("\nDone.")


if __name__ == "__main__":
    cmd_update()
