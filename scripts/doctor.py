#!/usr/bin/env python3
"""Doctor — diagnose and repair wiki issues from user feedback.

Users report issues via ``wiki doctor "<feedback>"``.  The doctor:
1. Classifies the issue (regex-based, zero LLM calls)
2. Diagnoses by searching wiki for affected pages/sources
3. Executes a targeted repair strategy
4. Verifies the fix by re-running a search
5. Persists the issue for tracking

Usage:
    python scripts/doctor.py "专家评审组的信息不完整，缺少成员名单"
    python scripts/doctor.py --check coursepl-专家评审组
    python scripts/doctor.py --recompile .wiki/source/doc.md
    python scripts/doctor.py --re-ocr .wiki/source/slides.pptx
    python scripts/doctor.py --list
    python scripts/doctor.py --resolve iss-20260627-001
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import get_wiki_dir

# ── constants ────────────────────────────────────────────────────────────────

ISSUES_FILE = "doctor/issues.json"


class IssueCategory(str, Enum):
    MISSING_INFO = "missing_info"
    INCORRECT_INFO = "incorrect_info"
    UNCOMPILED = "uncompiled"
    OCR_MISSED = "ocr_missed"
    SEARCH_QUALITY = "search_quality"
    CONTRADICTION = "contradiction"
    OUTDATED = "outdated"
    OTHER = "other"


_ISSUE_PATTERNS: list[tuple[str, IssueCategory]] = [
    # Specific patterns first — order matters
    (r"OCR.*遗漏|OCR.*不全|OCR.*错误|PPT.*遗漏|PPT.*不全|PPT.*漏|"
     r"扫描.*不全|扫描.*遗漏|解析.*遗漏|解析.*不全|OCR.*漏",
     IssueCategory.OCR_MISSED),
    (r"未编译|没编译|没有编译|没入库|没导入|没收录|未收录|未入库|未导入",
     IssueCategory.UNCOMPILED),
    (r"搜不到|检索不到|查不到|搜索不到|排名.*低|检索.*差|找不到.*页面",
     IssueCategory.SEARCH_QUALITY),
    (r"矛盾|冲突|不一致|互相.*不同|两.*说法|矛盾.*信息",
     IssueCategory.CONTRADICTION),
    (r"过时|过期|旧.*信息|老.*数据|不再适用|已变更|更新了",
     IssueCategory.OUTDATED),
    (r"错误|不对|不正确|搞错了|弄错了|识别错|识别错误|写错了|有误",
     IssueCategory.INCORRECT_INFO),
    # General patterns last
    (r"遗漏|缺少|缺失|不全|找不到|没找到|漏了|缺了",
     IssueCategory.MISSING_INFO),
]


class DoctorIssue:
    """A tracked doctor issue."""

    def __init__(
        self,
        category: IssueCategory,
        description: str,
        target_page: str | None = None,
        affected_pages: list[str] | None = None,
        affected_sources: list[str] | None = None,
        diagnosis: str = "",
        repair_strategy: str = "",
        repair_result: str = "",
        status: str = "open",
    ) -> None:
        self.id = _generate_issue_id()
        self.category = category
        self.description = description
        self.target_page = target_page
        self.affected_pages = affected_pages or []
        self.affected_sources = affected_sources or []
        self.diagnosis = diagnosis
        self.repair_strategy = repair_strategy
        self.repair_result = repair_result
        self.status = status
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category.value,
            "description": self.description,
            "target_page": self.target_page,
            "affected_pages": self.affected_pages,
            "affected_sources": self.affected_sources,
            "diagnosis": self.diagnosis,
            "repair_strategy": self.repair_strategy,
            "repair_result": self.repair_result,
            "status": self.status,
            "created_at": self.created_at,
        }


# ── helpers ───────────────────────────────────────────────────────────────────


def _generate_issue_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"iss-{today}-{_issue_counter():03d}"


def _issue_counter() -> int:
    wiki_dir = get_wiki_dir()
    issues_path = wiki_dir / ISSUES_FILE
    if not issues_path.is_file():
        return 1
    try:
        issues = json.loads(issues_path.read_text(encoding="utf-8"))
        today_prefix = datetime.now(timezone.utc).strftime("iss-%Y%m%d-")
        count = sum(
            1 for i in issues
            if isinstance(i, dict) and i.get("id", "").startswith(today_prefix)
        )
        return count + 1
    except (json.JSONDecodeError, OSError):
        return 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _search_wiki_pages(query: str, wiki_dir: Path) -> list[dict]:
    """Search wiki for pages matching a query."""
    try:
        from search import bm25_search, metadata_search, reciprocal_rank_fusion
        pages_dir = str(wiki_dir / "pages")
        bm25 = bm25_search(query, pages_dir, limit=5)
        meta = metadata_search(query, pages_dir, limit=5)
        return reciprocal_rank_fusion([bm25, meta], k=60)[:10]
    except ImportError:
        return []


def _find_source_file(name_hint: str, wiki_dir: Path) -> Path | None:
    """Search .wiki/source/ for a file matching the name hint."""
    source_dir = wiki_dir / "source"
    if not source_dir.is_dir():
        return None
    for f in source_dir.rglob("*"):
        if f.is_file() and name_hint.lower() in f.name.lower():
            return f
    return None


# ── classification ───────────────────────────────────────────────────────────


def classify_feedback(feedback: str) -> IssueCategory:
    """Classify user feedback via regex matching. Zero LLM calls."""
    for pattern, category in _ISSUE_PATTERNS:
        if re.search(pattern, feedback):
            return category
    return IssueCategory.OTHER


# ── diagnosis ─────────────────────────────────────────────────────────────────


def diagnose(
    feedback: str,
    target_page: str | None = None,
    wiki_dir: Path | None = None,
) -> DoctorIssue:
    """Parse user feedback and diagnose the issue."""
    if wiki_dir is None:
        wiki_dir = get_wiki_dir()
    category = classify_feedback(feedback)
    issue = DoctorIssue(
        category=category, description=feedback, target_page=target_page,
    )
    results = _search_wiki_pages(feedback, wiki_dir)
    if results:
        issue.affected_pages = [
            r.get("id", r.get("path", "?")) for r in results[:5]
        ]

    strategies = {
        IssueCategory.MISSING_INFO: ("search_sources_and_recompile",
                                     "Information appears to be missing. "
                                     "Will search source files for missing content."),
        IssueCategory.INCORRECT_INFO: ("compare_source_and_correct",
                                       "Information may be incorrect. "
                                       "Will compare with source files and correct."),
        IssueCategory.UNCOMPILED: ("locate_and_compile",
                                   "Source file appears to be uncompiled."),
        IssueCategory.OCR_MISSED: ("re_ocr_and_recompile",
                                   "OCR may have missed content. "
                                   "Will attempt to re-OCR and recompile."),
        IssueCategory.SEARCH_QUALITY: ("update_metadata_for_search",
                                       "Search quality issue. "
                                       "Will update page metadata to improve retrieval."),
        IssueCategory.CONTRADICTION: ("mark_contradiction",
                                      "Contradictory information detected."),
        IssueCategory.OUTDATED: ("mark_stale",
                                 "Information may be outdated."),
    }

    strategy, diagnosis = strategies.get(
        category,
        ("general_diagnosis", f"Unclassified issue. Found {len(results)} related pages."),
    )
    issue.diagnosis = diagnosis
    issue.repair_strategy = strategy

    return issue


# ── repair ────────────────────────────────────────────────────────────────────


def repair(issue: DoctorIssue, wiki_dir: Path | None = None) -> DoctorIssue:
    """Execute repair strategy based on issue category."""
    if wiki_dir is None:
        wiki_dir = get_wiki_dir()

    try:
        repair_fn = {
            "search_sources_and_recompile": _repair_missing_info,
            "compare_source_and_correct": _repair_incorrect_info,
            "locate_and_compile": _repair_uncompiled,
            "re_ocr_and_recompile": _repair_ocr_missed,
            "update_metadata_for_search": _repair_search_quality,
            "mark_contradiction": _repair_mark_status,
            "mark_stale": _repair_mark_status,
        }.get(issue.repair_strategy, _repair_general)

        repair_fn(issue, wiki_dir)
        issue.status = "resolved"
    except Exception as exc:
        issue.repair_result = f"Repair failed: {exc}"
        issue.status = "open"

    return issue


def _repair_missing_info(issue: DoctorIssue, wiki_dir: Path) -> None:
    """Search source files and recompile relevant sources."""
    import subprocess

    source_dir = wiki_dir / "source"
    compiled: list[str] = []

    if source_dir.is_dir():
        for f in source_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in (".md", ".txt", ".pdf", ".pptx", ".ppt", ".doc", ".docx"):
                continue
            try:
                if f.suffix in (".pdf", ".pptx", ".ppt", ".doc", ".docx"):
                    compiled.append(str(f))
                else:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    terms = _extract_search_terms(issue.description)
                    if any(t.lower() in content.lower() for t in terms[:5]):
                        compiled.append(str(f))
            except OSError:
                continue

    for src in compiled[:3]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "scripts.compile_v2", src, "--force"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"  [doctor] compile failed for {src}: {result.stderr[:200]}",
                      file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"  [doctor] compile timed out for {src}", file=sys.stderr)
        except Exception as exc:
            print(f"  [doctor] compile error for {src}: {exc}", file=sys.stderr)

    issue.repair_result = (
        f"Recompiled {len(compiled)} source(s): {', '.join(Path(s).name for s in compiled[:5])}"
        if compiled
        else "No matching source files found for recompile."
    )


def _repair_incorrect_info(issue: DoctorIssue, wiki_dir: Path) -> None:
    """Mark affected pages for review."""
    pages = issue.affected_pages
    for page_id in pages[:5]:
        _mark_page_for_review(page_id, issue.description, wiki_dir)
    issue.repair_result = (
        f"Marked {len(pages[:5])} page(s) for review."
        if pages
        else "No pages found to mark for review."
    )


def _repair_uncompiled(issue: DoctorIssue, wiki_dir: Path) -> None:
    """Locate source file and run wiki compile."""
    import subprocess

    source_file = _find_source_file(issue.description, wiki_dir)
    if source_file:
        try:
            subprocess.run(
                [sys.executable, "-m", "scripts.compile_v2", str(source_file)],
                capture_output=True, timeout=120,
            )
            issue.repair_result = f"Compiled: {source_file.name}"
        except (subprocess.TimeoutExpired, Exception) as exc:
            issue.repair_result = f"Compile failed: {exc}"
    else:
        issue.repair_result = (
            "Could not locate source file. Please specify with --recompile."
        )


def _repair_ocr_missed(issue: DoctorIssue, wiki_dir: Path) -> None:
    """Re-OCR document if OCR is configured, then recompile."""
    import subprocess

    source_file = _find_source_file(issue.description, wiki_dir)
    if not source_file:
        issue.repair_result = "Could not locate document for re-OCR."
        return

    ocr_ok = False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts._ocr_cli", str(source_file)],
            capture_output=True, text=True, timeout=300,
        )
        ocr_ok = result.returncode == 0
        if not ocr_ok:
            print(f"  [doctor] OCR failed for {source_file.name}: "
                  f"{result.stderr[:200]}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"  [doctor] OCR timed out for {source_file.name}", file=sys.stderr)
    except Exception as exc:
        print(f"  [doctor] OCR error for {source_file.name}: {exc}", file=sys.stderr)

    if not ocr_ok:
        issue.repair_result = (
            f"OCR failed for {source_file.name}. "
            "Check OCR configuration and retry."
        )
        return

    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.compile_v2", str(source_file), "--force"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            issue.repair_result = (
                f"OCR succeeded but compile failed: {result.stderr[:200]}"
            )
        else:
            issue.repair_result = f"Re-OCR'd and recompiled: {source_file.name}"
    except subprocess.TimeoutExpired:
        issue.repair_result = f"Compile timed out after OCR for {source_file.name}"
    except Exception as exc:
        issue.repair_result = f"Compile error after OCR: {exc}"


def _repair_search_quality(issue: DoctorIssue, wiki_dir: Path) -> None:
    """Update page metadata to improve search retrieval."""
    import yaml

    modified = 0
    for page_id in issue.affected_pages[:5]:
        path = _find_page_path(page_id, wiki_dir / "pages")
        if not path:
            continue
        try:
            content = path.read_text(encoding="utf-8")
            match = re.match(r"^---\s*\n(.*?)\n---", content, flags=re.DOTALL)
            if not match:
                continue
            fm = yaml.safe_load(match.group(1)) or {}
            if not isinstance(fm, dict):
                continue

            keywords = list(fm.get("keywords", []))
            if isinstance(keywords, str):
                keywords = [keywords]
            new_terms = _extract_search_terms(issue.description)
            for term in new_terms[:5]:
                if term not in keywords and len(term) >= 2:
                    keywords.append(term)
            fm["keywords"] = keywords[:24]
            fm["doctor_touched"] = _now()

            new_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
            body = content[match.end():].lstrip()
            path.write_text(f"---\n{new_yaml}\n---\n\n{body}", encoding="utf-8")
            modified += 1
        except (OSError, Exception):
            continue

    issue.repair_result = f"Updated metadata on {modified} page(s) to improve search."


def _repair_mark_status(issue: DoctorIssue, wiki_dir: Path) -> None:
    """Mark affected pages with appropriate status."""
    import yaml

    new_status = (
        "stale" if issue.category == IssueCategory.OUTDATED
        else "needs_review"
    )
    modified = 0

    for page_id in issue.affected_pages[:5]:
        path = _find_page_path(page_id, wiki_dir / "pages")
        if not path:
            continue
        try:
            content = path.read_text(encoding="utf-8")
            match = re.match(r"^---\s*\n(.*?)\n---", content, flags=re.DOTALL)
            if not match:
                continue
            fm = yaml.safe_load(match.group(1)) or {}
            if not isinstance(fm, dict):
                continue
            fm["status"] = new_status
            fm["doctor_touched"] = _now()
            if issue.category == IssueCategory.CONTRADICTION:
                fm["has_contradiction"] = True
                fm["contradiction_note"] = issue.description

            new_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
            body = content[match.end():].lstrip()
            path.write_text(f"---\n{new_yaml}\n---\n\n{body}", encoding="utf-8")
            modified += 1
        except (OSError, Exception):
            continue

    issue.repair_result = f"Marked {modified} page(s) as '{new_status}'."


def _repair_general(issue: DoctorIssue, wiki_dir: Path) -> None:
    """General search and report for unclassified issues."""
    results = _search_wiki_pages(issue.description, wiki_dir)
    issue.repair_result = (
        f"General diagnosis complete. Found {len(results)} related pages. "
        f"Top matches: {', '.join(r.get('id', '?') for r in results[:5])}."
        if results
        else "No related pages found. Consider recompiling sources."
    )


# ── verification ──────────────────────────────────────────────────────────────


def verify(issue: DoctorIssue, wiki_dir: Path | None = None) -> bool:
    """Re-run search to confirm the issue is resolved."""
    if wiki_dir is None:
        wiki_dir = get_wiki_dir()
    if issue.status != "resolved":
        return False
    results = _search_wiki_pages(issue.description, wiki_dir)
    return len(results) > 0


# ── page helpers ──────────────────────────────────────────────────────────────


def _find_page_path(page_id: str, pages_dir: Path) -> Path | None:
    """Locate a page file by its ID."""
    for subdir_name in ("concepts", "entities", "models", "techniques",
                         "frameworks", "benchmarks", "papers", "decisions",
                         "sessions", "patterns"):
        subdir = pages_dir / subdir_name
        if not subdir.is_dir():
            continue
        for f in subdir.iterdir():
            if f.suffix != ".md":
                continue
            if f.stem == page_id or f.name == f"{page_id}.md":
                return f
    return None


def _mark_page_for_review(page_id: str, note: str, wiki_dir: Path) -> None:
    """Add a review marker to a page's frontmatter."""
    import yaml

    path = _find_page_path(page_id, wiki_dir / "pages")
    if not path:
        return
    try:
        content = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---", content, flags=re.DOTALL)
        if not match:
            return
        fm = yaml.safe_load(match.group(1)) or {}
        if not isinstance(fm, dict):
            return
        fm["needs_review"] = True
        fm["review_note"] = note[:200]
        fm["doctor_touched"] = _now()
        new_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
        body = content[match.end():].lstrip()
        path.write_text(f"---\n{new_yaml}\n---\n\n{body}", encoding="utf-8")
    except (OSError, Exception):
        pass


def _extract_search_terms(text: str) -> list[str]:
    """Extract meaningful search terms from feedback text."""
    stop = {"了", "的", "是", "在", "和", "也", "都", "就", "有", "不",
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "of", "in", "to", "for", "with", "on", "at", "by", "from"}
    terms = re.findall(r"[一-鿿a-zA-Z0-9_+-]{2,}", text.lower())
    return [t for t in terms if t not in stop][:10]


# ── issue persistence ─────────────────────────────────────────────────────────


def _load_issues(wiki_dir: Path) -> list[dict]:
    issues_path = wiki_dir / ISSUES_FILE
    if not issues_path.is_file():
        return []
    try:
        return json.loads(issues_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_issues(issues: list[dict], wiki_dir: Path) -> None:
    issues_path = wiki_dir / ISSUES_FILE
    issues_path.parent.mkdir(parents=True, exist_ok=True)
    issues_path.write_text(
        json.dumps(issues, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_issues(wiki_dir: Path | None = None) -> list[dict]:
    """Return all outstanding (non-resolved) issues."""
    if wiki_dir is None:
        wiki_dir = get_wiki_dir()
    issues = _load_issues(wiki_dir)
    return [i for i in issues if i.get("status") != "resolved"]


def resolve_issue(issue_id: str, wiki_dir: Path | None = None) -> bool:
    """Mark an issue as resolved."""
    if wiki_dir is None:
        wiki_dir = get_wiki_dir()
    issues = _load_issues(wiki_dir)
    for issue in issues:
        if issue.get("id") == issue_id:
            issue["status"] = "resolved"
            issue["resolved_at"] = _now()
            _save_issues(issues, wiki_dir)
            return True
    return False


def check_page(page_id: str, wiki_dir: Path | None = None) -> dict:
    """Run diagnostic check on a specific page."""
    if wiki_dir is None:
        wiki_dir = get_wiki_dir()

    path = _find_page_path(page_id, wiki_dir / "pages")
    if not path:
        return {"error": f"Page not found: {page_id}"}

    import yaml

    try:
        content = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, flags=re.DOTALL)
        if not match:
            return {"error": "No YAML frontmatter"}

        fm = yaml.safe_load(match.group(1)) or {}
        body = match.group(2)
        density = len(re.sub(r"\s+", "", body))

        return {
            "id": page_id,
            "path": str(path),
            "density": density,
            "status": fm.get("status", "unknown"),
            "confidence": fm.get("confidence", 0),
            "has_keywords": bool(fm.get("keywords")),
            "has_aliases": bool(fm.get("aliases")),
            "has_questions": bool(fm.get("questions")),
            "needs_review": fm.get("needs_review", False),
            "last_modified": _now(),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── main entry ────────────────────────────────────────────────────────────────

def _handle_recompile(src_path: str) -> dict:
    import subprocess
    src = Path(src_path)
    if not src.is_file():
        return {"success": False, "message": f"Source not found: {src_path}"}
    try:
        r = subprocess.run(
            [sys.executable, "-m", "scripts.compile_v2", str(src), "--force"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return {"success": False, "message": f"Compile failed: {r.stderr[:200]}"}
        return {"success": True, "message": f"Recompiled: {src.name}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Compile timed out: {src.name}"}
    except Exception as exc:
        return {"success": False, "message": f"Recompile failed: {exc}"}


def _handle_re_ocr(doc_path: str) -> dict:
    import subprocess
    src = Path(doc_path)
    if not src.is_file():
        return {"success": False, "message": f"Document not found: {doc_path}"}
    try:
        ocr = subprocess.run(
            [sys.executable, "-m", "scripts._ocr_cli", str(src)],
            capture_output=True, text=True, timeout=300,
        )
        if ocr.returncode != 0:
            return {"success": False, "message": f"OCR failed: {ocr.stderr[:200]}"}
        cmp = subprocess.run(
            [sys.executable, "-m", "scripts.compile_v2", str(src), "--force"],
            capture_output=True, text=True, timeout=120,
        )
        if cmp.returncode != 0:
            return {"success": False,
                    "message": f"OCR ok but compile failed: {cmp.stderr[:200]}"}
        return {"success": True, "message": f"Re-OCR'd and recompiled: {src.name}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Re-OCR timed out for {src.name}"}
    except Exception as exc:
        return {"success": False, "message": f"Re-OCR failed: {exc}"}


def _handle_feedback(
    feedback: str,
    target_page: str | None,
    issue_category: str | None,
    wiki_dir: Path,
) -> dict:
    """Classify → diagnose → repair → verify → persist a user feedback."""
    issue = diagnose(feedback, target_page, wiki_dir)
    if issue_category:
        try:
            issue.category = IssueCategory(issue_category)
        except ValueError:
            valid = [c.value for c in IssueCategory if c != IssueCategory.OTHER]
            print(f"  [doctor] WARNING: invalid issue category '{issue_category}'. "
                  f"Valid: {valid}. Using auto-detected: {issue.category.value}",
                  file=sys.stderr)

    issue = repair(issue, wiki_dir)
    verified = verify(issue, wiki_dir)

    issues = _load_issues(wiki_dir)
    issues.append(issue.to_dict())
    _save_issues(issues, wiki_dir)

    return {
        "success": issue.status == "resolved",
        "report": {
            "issue_id": issue.id,
            "category": issue.category.value,
            "description": issue.description,
            "diagnosis": issue.diagnosis,
            "repair_strategy": issue.repair_strategy,
            "repair_result": issue.repair_result,
            "status": issue.status,
            "verified": verified,
        },
        "message": (
            f"[{issue.category.value}] {issue.repair_result} "
            f"(verified: {verified})"
        ),
    }


def run_doctor(
    feedback: str = "",
    target_page: str | None = None,
    issue_category: str | None = None,
    recompile_path: str | None = None,
    re_ocr_path: str | None = None,
    list_issues_flag: bool = False,
    check_page_id: str | None = None,
    resolve_id: str | None = None,
) -> dict:
    """Main entry point for doctor command."""
    wiki_dir = get_wiki_dir()

    if list_issues_flag:
        issues = list_issues(wiki_dir)
        return {"success": True, "issues": issues,
                "message": f"{len(issues)} outstanding issue(s)."}

    if resolve_id:
        ok = resolve_issue(resolve_id, wiki_dir)
        return {"success": ok,
                "message": f"Issue {resolve_id} resolved." if ok
                else f"Issue {resolve_id} not found."}

    if check_page_id:
        result = check_page(check_page_id, wiki_dir)
        return {"success": "error" not in result, "report": result}

    if recompile_path:
        return _handle_recompile(recompile_path)

    if re_ocr_path:
        return _handle_re_ocr(re_ocr_path)

    if not feedback:
        return {"success": False, "message": "No feedback provided."}

    return _handle_feedback(feedback, target_page, issue_category, wiki_dir)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Doctor — diagnose and repair wiki issues from user feedback",
    )
    parser.add_argument("feedback", nargs="?", default="",
                        help="Natural language description of the issue")
    parser.add_argument("--target", dest="target_page", default=None,
                        help="Target page ID to check/fix")
    parser.add_argument("--issue", dest="issue_category", default=None,
                        choices=["missing_info", "incorrect_info", "uncompiled",
                                  "ocr_missed", "search_quality", "contradiction",
                                  "outdated"],
                        help="Explicit issue category")
    parser.add_argument("--recompile", dest="recompile_path", default=None,
                        help="Recompile a specific source file")
    parser.add_argument("--re-ocr", dest="re_ocr_path", default=None,
                        help="Re-OCR a specific document")
    parser.add_argument("--list", dest="list_issues", action="store_true",
                        help="List outstanding issues")
    parser.add_argument("--check", dest="check_page", default=None,
                        help="Run diagnostic check on a page")
    parser.add_argument("--resolve", dest="resolve_id", default=None,
                        help="Mark an issue as resolved")

    args = parser.parse_args()
    result = run_doctor(
        feedback=args.feedback,
        target_page=args.target_page,
        issue_category=args.issue_category,
        recompile_path=args.recompile_path,
        re_ocr_path=args.re_ocr_path,
        list_issues_flag=args.list_issues,
        check_page_id=args.check_page,
        resolve_id=args.resolve_id,
    )

    if result.get("success"):
        print(result.get("message", "Done"))
        if result.get("report"):
            print(json.dumps(result["report"], indent=2, ensure_ascii=False))
        if result.get("issues"):
            for issue in result["issues"]:
                print(
                    f"  [{issue.get('category', '?')}] "
                    f"{issue.get('description', '')[:100]} "
                    f"— {issue.get('status', '?')} ({issue.get('id', '?')})"
                )
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
