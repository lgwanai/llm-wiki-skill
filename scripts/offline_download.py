#!/usr/bin/env python3
"""offline_download.py — Download all Python wheels for offline deployment.

Downloads every dependency from requirements.txt into offline/wheels/<platform>/
so the project can be installed without internet access on any target machine.

Usage:
    # Download for current platform
    python scripts/offline_download.py

    # Download for all platforms (macOS arm64/x86_64, Windows x86_64, Linux x86_64)
    python scripts/offline_download.py --all

    # Download for a specific platform
    python scripts/offline_download.py --platform macos
    python scripts/offline_download.py --platform windows
    python scripts/offline_download.py --platform linux

    # Include source distributions (for packages without pre-built wheels)
    python scripts/offline_download.py --include-source

Offline install on target machine:
    pip install --no-index --find-links offline/wheels/<platform>/ .
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OFFLINE_DIR = PROJECT_ROOT / "offline"

_PY_VER = f"{sys.version_info.major}{sys.version_info.minor}"

# Platform tag mapping for cross-platform pip download
_PLATFORM_TARGETS: dict[str, dict[str, tuple[str, str]]] = {
    "macos": {
        "arm64": ("macosx_14_0_arm64", f"cp{_PY_VER}"),
        "x86_64": ("macosx_10_9_x86_64", f"cp{_PY_VER}"),
    },
    "windows": {
        "x86_64": ("win_amd64", f"cp{_PY_VER}"),
    },
    "linux": {
        "x86_64": ("manylinux_2_17_x86_64", f"cp{_PY_VER}"),
    },
}


def _detect_platform() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    if s == "linux":
        return "linux"
    return s


def _detect_arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x86_64"
    return m


def _current_key() -> str:
    return f"{_detect_platform()}-{_detect_arch()}"


def _run_pip_download(
    out_dir: Path, plat_tag: str, abi: str, include_source: bool
) -> int:
    """Run pip download for a specific platform tag. Returns package count."""
    req_path = PROJECT_ROOT / "requirements.txt"
    if not req_path.is_file():
        print(f"  ✗ requirements.txt not found", file=sys.stderr)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "pip", "download",
        "-r", str(req_path),
        "-d", str(out_dir),
        "--platform", plat_tag,
        "--python-version", _PY_VER,
        "--implementation", "cp",
        "--abi", abi,
    ]
    if not include_source:
        cmd += ["--only-binary", ":all:"]

    print(f"  Target: {plat_tag} (abi={abi}) → {out_dir.name}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)

    if result.returncode != 0:
        err = result.stderr.strip()
        errors = [l for l in err.split("\n") if "ERROR" in l]
        if errors:
            print(f"  ⚠ {len(errors)} package(s) missing wheels for this platform:")
            for line in errors[:5]:
                print(f"    {line.strip()}")
        else:
            for line in err.split("\n")[-3:]:
                if line.strip():
                    print(f"    {line.strip()}")

    whl = len(list(out_dir.glob("*.whl")))
    tgz = len(list(out_dir.glob("*.tar.gz")))
    return whl + tgz


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _copy_req(out_dir: Path) -> None:
    shutil.copy2(PROJECT_ROOT / "requirements.txt", out_dir / "requirements.txt")


def download_current(include_source: bool = False) -> list[Path]:
    """Download for the current platform."""
    p, a = _detect_platform(), _detect_arch()
    targets = _PLATFORM_TARGETS.get(p, {})
    if a not in targets:
        print(f"✗ Unknown arch: {a} for {p}")
        sys.exit(1)
    plat_tag, abi = targets[a]
    out_dir = OFFLINE_DIR / "wheels" / f"{p}-{a}"
    print(f"\n  [{f'{p}-{a}'}]")
    count = _run_pip_download(out_dir, plat_tag, abi, include_source)
    print(f"  ✓ {count} packages ({_dir_size_mb(out_dir):.1f} MB)")
    _copy_req(out_dir)
    return [out_dir]


def download_all(include_source: bool = False) -> list[Path]:
    """Download for all platforms."""
    dirs: list[Path] = []
    for plat_name, archs in _PLATFORM_TARGETS.items():
        for arch_name, (plat_tag, abi) in archs.items():
            key = f"{plat_name}-{arch_name}"
            out_dir = OFFLINE_DIR / "wheels" / key
            print(f"\n  [{key}]")
            count = _run_pip_download(out_dir, plat_tag, abi, include_source)
            print(f"  ✓ {count} packages ({_dir_size_mb(out_dir):.1f} MB)")
            _copy_req(out_dir)
            dirs.append(out_dir)
    return dirs


def download_platform(target: str, include_source: bool = False) -> list[Path]:
    """Download for a named platform."""
    targets = _PLATFORM_TARGETS.get(target, {})
    if not targets:
        print(f"✗ Unknown platform: {target}")
        sys.exit(1)
    dirs: list[Path] = []
    for arch_name, (plat_tag, abi) in targets.items():
        key = f"{target}-{arch_name}"
        out_dir = OFFLINE_DIR / "wheels" / key
        print(f"\n  [{key}]")
        count = _run_pip_download(out_dir, plat_tag, abi, include_source)
        print(f"  ✓ {count} packages ({_dir_size_mb(out_dir):.1f} MB)")
        _copy_req(out_dir)
        dirs.append(out_dir)
    return dirs


def _print_install_guide(dirs: list[Path]) -> None:
    print("\n" + "=" * 60)
    print("Offline Install Guide")
    print("=" * 60)
    for d in dirs:
        key = d.name
        print(f"\n  [{key}]")
        print(f"  1. Copy offline/ to the target machine")
        print(f"  2. cd llm-wiki-skill")
        print(f"  3. pip install --no-index --find-links offline/wheels/{key}/ .")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Python wheels for offline deployment"
    )
    parser.add_argument(
        "--platform", choices=["macos", "windows", "linux"], default=None,
        help="Target platform (default: current)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Download for all supported platforms",
    )
    parser.add_argument(
        "--include-source", action="store_true",
        help="Include .tar.gz source distributions (for packages without wheels)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LLM Wiki — Offline Wheel Download")
    print("=" * 60)
    print(f"Current:  {_current_key()}")
    print(f"Python:   {sys.version_info.major}.{sys.version_info.minor}")
    print(f"Output:   {OFFLINE_DIR}/wheels/")

    if args.all:
        dirs = download_all(include_source=args.include_source)
    elif args.platform:
        dirs = download_platform(args.platform, include_source=args.include_source)
    else:
        dirs = download_current(include_source=args.include_source)

    _print_install_guide(dirs)


if __name__ == "__main__":
    main()
