#!/usr/bin/env python3
"""package.py — Package llm-wiki-skill into a distributable archive.

Performs security checks before packaging:
  - Scans for API keys, passwords, tokens in all files
  - Aborts if any secrets are found

Usage:
  python3 scripts/package.py          # Package to dist/
  python3 scripts/package.py --check  # Only check for secrets, don't package
"""

import os
import re
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"

EXCLUDE_PATTERNS = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "*.egg-info",
    ".venv",
    "venv",
    "env",
    ".pytest_cache",
    ".coverage",
    "htmlcov",
    "dist",
    "wiki_config.yaml",
    ".wiki",
    ".claude/cache",
    "tests",
    "references",
    ".planning",
    ".ruff_cache",
]

SECRET_PATTERNS = {
    "API key (sk-...)": re.compile(r'sk-[a-zA-Z0-9]{20,}'),
    "API key (pk-...)": re.compile(r'pk-[a-zA-Z0-9]{20,}'),
    "GitHub token": re.compile(r'gh[pousr]_[a-zA-Z0-9]{36,}'),
    "Private key": re.compile(
        r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
        re.IGNORECASE,
    ),
    "Generic secret": re.compile(r'(?:api_key|apikey|secret|password)\s*[:=]\s*["\'](?!\s*$|your-|sk-|pk-|changeme|example|xxx)[^"\'\s]{6,}["\']', re.IGNORECASE),
    "AWS key": re.compile(r'AKIA[0-9A-Z]{16}'),
    "JWT token": re.compile(r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'),
}


def should_exclude(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    for pattern in EXCLUDE_PATTERNS:
        if path.match(pattern) or rel.startswith(pattern.rstrip("/")):
            return True
    return False


def scan_for_secrets() -> list[dict]:
    violations = []

    for f in ROOT.rglob("*"):
        if f.is_dir() or should_exclude(f):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for secret_type, pattern in SECRET_PATTERNS.items():
            matches = pattern.findall(content)
            for match in matches:
                masked = match[:6] + "***" if len(match) > 9 else "***"
                violations.append({
                    "file": str(f.relative_to(ROOT)),
                    "type": secret_type,
                    "match": masked,
                })

    return violations


def package_tar(output_path: Path):
    with tarfile.open(output_path, "w:gz") as tar:
        for f in sorted(ROOT.rglob("*")):
            if f.is_dir() or should_exclude(f):
                continue
            rel = f.relative_to(ROOT)
            tar.add(str(f), arcname=str(rel))

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Created: {output_path.name} ({size_mb:.1f} MB)")


def package_zip(output_path: Path):
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(ROOT.rglob("*")):
            if f.is_dir() or should_exclude(f):
                continue
            rel = f.relative_to(ROOT)
            zf.write(str(f), arcname=str(rel))

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Created: {output_path.name} ({size_mb:.1f} MB)")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Package llm-wiki-skill")
    parser.add_argument("--check", action="store_true", help="Only scan for secrets, don't package")
    parser.add_argument("--format", choices=["tar.gz", "zip"], default="tar.gz", help="Archive format")
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
    print(f"\n[2/2] Packaging...")
    DIST.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
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
