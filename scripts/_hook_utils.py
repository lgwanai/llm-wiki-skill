"""Cross-platform hook utilities for llm-wiki-skill.

Provides shared helpers used by all hook scripts in .claude/hooks/.
All functions are pure Python — no shell commands, no Unix assumptions.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def is_windows() -> bool:
    """Return True if running on Windows."""
    return platform.system() == "Windows"


def get_project_root() -> Path:
    """Resolve the project root directory.

    Uses CLAUDE_PROJECT_DIR env var (set by Claude Code) if available,
    otherwise walks up from the current working directory looking for CLAUDE.md.
    """
    # Claude Code sets this env var to the project root
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        root = Path(env_dir).resolve()
        if root.is_dir():
            return root

    # Fallback: walk up from CWD looking for CLAUDE.md
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "CLAUDE.md").is_file():
            return parent

    # Last resort: CWD
    return cwd


def get_wiki_dir(root: Path) -> Path:
    """Return the wiki directory path.

    Respects LLM_WIKI_DIR env var override, defaults to .wiki.
    """
    wiki_rel = os.environ.get("LLM_WIKI_DIR", ".wiki")
    return root / wiki_rel


def wiki_dir_exists(root: Path) -> bool:
    """Check if the wiki has been initialized."""
    return get_wiki_dir(root).is_dir()


def run_python_script(
    script_name: str,
    args: list[str] | None = None,
    root: Path | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a Python script in the scripts/ directory via sys.executable.

    Args:
        script_name: Name of the script (e.g. "crystallize.py", "wiki.py").
        args: Additional CLI arguments to pass.
        root: Project root. Resolved automatically if not provided.
        capture: If True, capture stdout/stderr (subprocess.run capture_output=True).

    Returns:
        The CompletedProcess result.
    """
    if root is None:
        root = get_project_root()

    script_path = root / "scripts" / script_name
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    if capture:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(root),
        )
    else:
        return subprocess.run(cmd, cwd=str(root))


def file_mod_time(path: Path) -> datetime:
    """Return file modification time as UTC datetime.

    Cross-platform replacement for 'stat -f %Sm' (macOS) and 'date -r' (Unix).
    Uses os.path.getmtime() which works on all platforms.
    """
    ts = os.path.getmtime(str(path))
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def symlink_or_copy_info(src: Path, dst: Path) -> tuple[bool, str]:
    """Try to create a symlink at dst pointing to src.

    On Windows, symlink creation requires Developer Mode or admin privileges.
    Returns (success, message) rather than raising.

    Args:
        src: The existing file/directory to link to.
        dst: Where to create the symlink.

    Returns:
        (True, "symlinked") on success, (False, error_message) on failure.
    """
    try:
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)
        return (True, "symlinked")
    except OSError as e:
        return (False, str(e))
    except NotImplementedError:
        # Windows before symlink support was added
        return (False, "symlinks not supported on this platform")


def print_hook_header(title: str) -> None:
    """Print a consistent header for hook script output."""
    print(f"\n{'=' * 60}")
    print(f"  llm-wiki: {title}")
    print(f"{'=' * 60}")
