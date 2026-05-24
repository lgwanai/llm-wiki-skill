#!/usr/bin/env python3
"""update.py — Update skill from GitHub: clone or pull, backup old files to backup/."""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

REPO_URL = "https://github.com/lgwanai/llm-wiki-skill"
ROOT = Path(__file__).parent.parent
BACKUP_DIR = ROOT / "backup"

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "dist", "backup", ".wiki", "node_modules",
             "__MACOSX"}
SKIP_GLOBS = ["*.pyc", ".DS_Store", "Thumbs.db", "*.egg-info"]


def _should_backup(p: Path) -> bool:
    parts = p.relative_to(ROOT).parts
    if any(d in SKIP_DIRS for d in parts):
        return False
    if any(p.match(g) for g in SKIP_GLOBS):
        return False
    return p.is_file()


def backup_files():
    """Create dated backup of all project files."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"llm-wiki-{timestamp}.tar.gz"

    files = [f for f in ROOT.rglob("*") if _should_backup(f)]

    with tarfile.open(backup_path, "w:gz") as tar:
        for f in sorted(files):
            tar.add(str(f), arcname=str(f.relative_to(ROOT)))

    print(f"  Created: {backup_path.name} ({backup_path.stat().st_size / 1024:.0f} KB, {len(files)} files)")
    return len(files)


def sync_files(src: Path):
    """Copy all project files from src to ROOT (overwrite), ignoring .git/config."""
    for f in src.rglob("*"):
        rel = f.relative_to(src)
        parts = rel.parts
        if any(d in SKIP_DIRS for d in parts):
            continue
        if f.is_dir():
            (ROOT / rel).mkdir(parents=True, exist_ok=True)
        else:
            shutil.copy2(str(f), str(ROOT / rel))
    # Preserve local .git config if it existed
    local_config = ROOT / ".git" / "config"
    if local_config.exists():
        existing = local_config.read_text(encoding="utf-8")
        if "lgwanai" not in existing:
            local_config.write_text(
                existing.replace("url =", f"# url =") + 
                f'\n[remote "origin"]\n\turl = {REPO_URL}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
            )


def cmd_update():
    print("=" * 60)
    print("llm-wiki-skill update")
    print("=" * 60)

    is_git_repo = (ROOT / ".git").is_dir()

    if is_git_repo:
        print("\n[1/3] Backing up current files...")
        backup_files()

        print("\n[2/3] Pulling latest code...")
        os.chdir(ROOT)

        # Check for unstaged changes — stash if needed
        has_changes = subprocess.run(
            ["git", "diff", "--quiet"], capture_output=True
        ).returncode != 0

        stashed = False
        if has_changes:
            result = subprocess.run(
                ["git", "stash", "--include-untracked"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                stashed = True
                print("  Stashed local changes before pull.")

        try:
            result = subprocess.run(
                ["git", "pull", "--rebase", "origin", "main"],
                capture_output=True, text=True, timeout=60
            )
            print(f"  {result.stdout.strip()}")
            if result.returncode != 0:
                print(f"  WARNING: {result.stderr.strip()}")
        finally:
            if stashed:
                subprocess.run(
                    ["git", "stash", "pop"],
                    capture_output=True, text=True, timeout=30
                )
                print("  Restored local changes.")
    else:
        print("\n[1/3] No .git found — backing up then cloning...")
        backup_files()

        print("\n[2/3] Cloning from GitHub...")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", REPO_URL, tmp],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode != 0:
                    print(f"  ERROR: clone failed: {result.stderr.strip()}")
                    sys.exit(1)
                print(f"  {result.stdout.strip()}")

                # Copy .git and all files from clone
                print("  Syncing files...")
                shutil.copytree(
                    str(Path(tmp) / ".git"), str(ROOT / ".git"),
                    dirs_exist_ok=True
                )
                sync_files(Path(tmp))
            except subprocess.TimeoutExpired:
                print("  ERROR: clone timed out. Check network.")
                sys.exit(1)

    print("\n[3/3] Summary")
    backups = sorted(BACKUP_DIR.glob("*.tar.gz"))
    print(f"  Backups: {len(backups)} total in {BACKUP_DIR}/")
    if backups:
        for b in backups[-5:]:
            print(f"    {b.name}")
    print("\nDone.")


if __name__ == "__main__":
    cmd_update()
