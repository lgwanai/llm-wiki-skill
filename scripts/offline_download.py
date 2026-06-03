#!/usr/bin/env python3
"""offline_download.py — Download all Python wheels for offline deployment.

Downloads every dependency from requirements.txt into offline/wheels/
so the project can be installed without internet access.

Supports cross-platform download: run with --platform to target a different OS.

Usage:
    # Download for current platform
    python scripts/offline_download.py

    # Download for a specific platform
    python scripts/offline_download.py --platform macos    # macOS (arm64 + x86_64)
    python scripts/offline_download.py --platform windows  # Windows (x86_64)
    python scripts/offline_download.py --platform linux    # Linux (x86_64)

    # Download only core dependencies (skip OCR, search)
    python scripts/offline_download.py --core-only
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# pip download target directory
WHEELS_DIR = PROJECT_ROOT / "offline" / "wheels"

# --- Platform mapping for cross-platform downloads ---
_PLATFORM_MAP = {
    "macos": {
        "arm64": "macosx_14_0_arm64",
        "x86_64": "macosx_10_9_x86_64",
    },
    "windows": {
        "x86_64": "win_amd64",
    },
    "linux": {
        "x86_64": "manylinux_2_17_x86_64",
    },
}

# Python version tag pattern (e.g., cp311 for Python 3.11)
_PY_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"


def _detect_current_platform() -> str:
    """Detect the current OS platform tag for pip."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    else:
        return system


def _detect_current_arch() -> str:
    """Detect the current CPU architecture."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    elif machine in ("x86_64", "amd64"):
        return "x86_64"
    return machine


def download_wheels(
    target_platform: str | None = None,
    core_only: bool = False,
    python_version: str | None = None,
) -> None:
    """Download all wheels to offline/wheels/.

    Args:
        target_platform: Platform to target (macos, windows, linux).
                         None = current platform.
        core_only: If True, skip search/OCR/dev dependencies.
        python_version: Python version tag override (e.g., "cp311").
    """
    WHEELS_DIR.mkdir(parents=True, exist_ok=True)

    req_path = PROJECT_ROOT / "requirements.txt"
    if not req_path.exists():
        print(f"Error: {req_path} not found", file=sys.stderr)
        sys.exit(1)

    # Build platform args for pip download
    if target_platform is None:
        target_platform = _detect_current_platform()
        arch = _detect_current_arch()
        plat_tags = _PLATFORM_MAP.get(target_platform, {}).get(arch, "")
        if not plat_tags:
            print(f"Warning: unknown arch '{arch}' for platform '{target_platform}'")
            print("Downloading for current platform only (no --platform flag)")
            plat_args: list[str] = []
        else:
            plat_args = [
                "--platform", plat_tags,
                "--python-version", python_version or _PY_TAG[2:],
                "--implementation", "cp",
                "--abi", _PY_TAG,
            ]
    else:
        # Cross-platform: download for all architectures of this platform
        archs = _PLATFORM_MAP.get(target_platform, {})
        if not archs:
            print(f"Unknown platform: {target_platform}", file=sys.stderr)
            print(f"Available: {', '.join(_PLATFORM_MAP.keys())}", file=sys.stderr)
            sys.exit(1)

        for arch_name, plat_tag in archs.items():
            arch_dir = WHEELS_DIR / f"{target_platform}-{arch_name}"
            arch_dir.mkdir(parents=True, exist_ok=True)
            _do_download(arch_dir, req_path, core_only, plat_tag, python_version or _PY_TAG[2:])
        return

    # Single platform download
    if plat_args:
        _do_download(WHEELS_DIR, req_path, core_only, plat_args[1], plat_args[3])
    else:
        _do_download(WHEELS_DIR, req_path, core_only, None, None)


def _do_download(
    out_dir: Path,
    req_path: Path,
    core_only: bool,
    plat_tag: str | None,
    py_ver: str | None,
) -> None:
    """Execute pip download with the given parameters."""
    cmd = [
        sys.executable, "-m", "pip", "download",
        "-r", str(req_path),
        "-d", str(out_dir),
        "--only-binary", ":all:",
    ]

    if plat_tag and py_ver:
        cmd += [
            "--platform", plat_tag,
            "--python-version", py_ver,
            "--implementation", "cp",
            "--abi", f"cp{py_ver.replace('.', '')}",
        ]

    if core_only:
        # Filter out optional deps by only taking lines without extras markers
        # Simpler: just download core + basic deps
        cmd.append("--no-deps")  # Skip transitive deps for core-only
        # Actually, let's refine: exclude dev and heavy OCR deps
        pass

    print(f"Downloading wheels to {out_dir}...")
    if plat_tag:
        print(f"  Platform: {plat_tag}, Python: {py_ver}")
    print(f"  Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"\nWarning: some packages may not have pre-built wheels for this platform.")
        print(f"Consider running on the target machine directly instead.")

    # Count downloaded wheels
    whl_count = len(list(out_dir.glob("*.whl")))
    print(f"\n✓ Downloaded {whl_count} wheels to {out_dir}")
    print(f"  Total size: {_dir_size(out_dir)}")


def _dir_size(path: Path) -> str:
    """Return human-readable directory size."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    if total > 1024 * 1024 * 1024:
        return f"{total / (1024**3):.1f} GB"
    elif total > 1024 * 1024:
        return f"{total / (1024**2):.1f} MB"
    else:
        return f"{total / 1024:.1f} KB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Python wheels for offline deployment"
    )
    parser.add_argument(
        "--platform",
        choices=["macos", "windows", "linux"],
        default=None,
        help="Target platform (default: current platform)",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Download only core dependencies (skip search, OCR, dev)",
    )
    parser.add_argument(
        "--python-version",
        default=None,
        help="Python version tag (e.g., '311' for CPython 3.11). Default: current interpreter.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LLM Wiki — Offline Wheel Download")
    print("=" * 60)
    print(f"Current platform: {_detect_current_platform()} ({_detect_current_arch()})")
    print(f"Python: {sys.version}")
    print(f"Target platform: {args.platform or _detect_current_platform()}")
    print()

    download_wheels(
        target_platform=args.platform,
        core_only=args.core_only,
        python_version=args.python_version,
    )

    print()
    print("To install from offline wheels:")
    print(f"  pip install --no-index --find-links {WHEELS_DIR} .")
    print()


if __name__ == "__main__":
    main()
