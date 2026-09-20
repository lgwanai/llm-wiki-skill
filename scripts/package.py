#!/usr/bin/env python3
"""package.py — Package llm-wiki-skill into a distributable archive.

Performs security checks before packaging:
  - Packages only an explicit allowlist of distributable files
  - Scans candidate files for API keys, passwords, and tokens
  - Aborts if any secrets are found

Usage:
  python3 scripts/package.py          # Package to dist/
  python3 scripts/package.py --check  # Only check for secrets, don't package
"""

import re
import sys
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"

# Keep release archives intentionally small and auditable.  In particular, do
# not package repository metadata, local agent settings, private wiki content,
# tests/evaluation artifacts, build output, or machine-local configuration.
INCLUDE_FILES = {
    "CONFIGURATION.md",
    "LICENSE",
    "README.md",
    "README_CN.md",
    "SKILL.md",
    "pyproject.toml",
    "requirements.txt",
    "wiki_config.yaml.example",
}

INCLUDE_DIRS = {
    "docs",
    "ocr",
    "references",
    "scripts",
    "templates",
}

EXCLUDE_PATTERNS = [
    ".DS_Store",
    ".claude/cache",
    ".claude/settings.local.json",
    ".codegraph",
    ".codex",
    ".coverage",
    ".eggs",
    ".env",
    ".env.local",
    ".git",
    ".gitignore",
    ".idea",
    ".planning",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    ".wiki",
    "*.egg",
    "*.egg-info",
    "*.local.yaml",
    "*.pyc",
    "*.pyd",
    "*.pyo",
    "*.secret.*",
    "*.so",
    "*.swp",
    "*.swo",
    "*~",
    "Thumbs.db",
    "__pycache__",
    "backup",
    "build",
    "dist",
    "env",
    "evals",
    "htmlcov",
    "icon.png",
    "install.bat",
    "install.ps1",
    "models",
    "ocr/mineru.json",
    "offline",
    "tests",
    "venv",
    "wiki_config.yaml",
]

SECRET_PATTERNS = {
    "API key (sk-...)": re.compile(r"sk-(?:proj-|ant-api\d{2}-)?[a-zA-Z0-9_-]{20,}"),
    "API key (pk-...)": re.compile(r"pk-[a-zA-Z0-9]{20,}"),
    "Google API key": re.compile(r"AIza[a-zA-Z0-9_-]{35}"),
    "GitHub token": re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}"),
    "Private key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        r"\s+[a-zA-Z0-9+/=\r\n]{80,}"
        r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE | re.DOTALL,
    ),
    "Generic secret": re.compile(
        r'(?:api_key|apikey|secret|password)\s*[:=]\s*["\']'
        r'(?!\s*$|\$|your-|sk-|pk-|changeme|example|xxx)[^"\'\s]{6,}["\']',
        re.IGNORECASE,
    ),
    "AWS key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "JWT token": re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
}


def should_include(path: Path) -> bool:
    """Return whether *path* belongs to the distributable allowlist."""
    rel = path.relative_to(ROOT).as_posix()
    if rel in INCLUDE_FILES:
        return True
    return bool(path.parts) and path.relative_to(ROOT).parts[0] in INCLUDE_DIRS


def should_exclude(path: Path) -> bool:
    if not should_include(path):
        return True
    rel = str(path.relative_to(ROOT))
    for pattern in EXCLUDE_PATTERNS:
        if path.match(pattern) or rel.startswith(pattern.rstrip("/")):
            return True
    # Also check parent directories against directory-like patterns
    for parent in path.parents:
        if parent == ROOT:
            break
        parent_rel = str(parent.relative_to(ROOT))
        for pattern in EXCLUDE_PATTERNS:
            if parent.match(pattern) or parent_rel.startswith(pattern.rstrip("/")):
                return True
    return False


def scan_for_secrets() -> list[dict]:
    violations = []

    for f in ROOT.rglob("*"):
        if f.is_dir() or f.is_symlink() or should_exclude(f):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for secret_type, pattern in SECRET_PATTERNS.items():
            matches = pattern.findall(content)
            for match in matches:
                masked = match[:6] + "***" if len(match) > 9 else "***"
                violations.append(
                    {
                        "file": str(f.relative_to(ROOT)),
                        "type": secret_type,
                        "match": masked,
                    }
                )

    return violations


def package_tar(output_path: Path):
    with tarfile.open(output_path, "w:gz") as tar:
        for f in sorted(ROOT.rglob("*")):
            if f.is_dir() or f.is_symlink() or should_exclude(f):
                continue
            rel = f.relative_to(ROOT)
            tar.add(str(f), arcname=str(rel))

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Created: {output_path.name} ({size_mb:.1f} MB)")


def package_zip(output_path: Path):
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(ROOT.rglob("*")):
            if f.is_dir() or f.is_symlink() or should_exclude(f):
                continue
            rel = f.relative_to(ROOT)
            zf.write(str(f), arcname=str(rel))

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Created: {output_path.name} ({size_mb:.1f} MB)")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Package llm-wiki-skill")
    parser.add_argument("--check", action="store_true", help="Only scan for secrets, don't package")
    parser.add_argument(
        "--format",
        choices=["tar.gz", "zip"],
        default="tar.gz",
        help="Archive format",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("llm-wiki-skill packaging")
    print("=" * 60)

    # Step 1: Security scan
    print("\n[1/2] Scanning for secrets...")
    violations = scan_for_secrets()

    if violations:
        print(f"\n  FAILED: {len(violations)} secret(s) found!")
        for v in violations:
            print(f"    {v['file']}: {v['type']} → {v['match']}")
        print("\n  Packaging ABORTED. Remove secrets before packaging.")
        sys.exit(1)

    print("  OK: No secrets detected.")

    if args.check:
        return

    # Step 2: Package
    print("\n[2/2] Packaging...")
    DIST.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    if args.format == "zip":
        output = DIST / f"llm-wiki-skill-{date_str}.zip"
        package_zip(output)
    else:
        output = DIST / f"llm-wiki-skill-{date_str}.tar.gz"
        package_tar(output)

    print(f"\n  Output: {output}")
    print("  Done.")


if __name__ == "__main__":
    main()
