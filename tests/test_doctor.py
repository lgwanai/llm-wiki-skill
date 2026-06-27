"""Tests for doctor.py — diagnose and repair wiki issues."""

import pytest


class TestClassifyFeedback:
    def test_missing_info(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("信息不完整，缺少成员名单") == IssueCategory.MISSING_INFO

    def test_ocr_missed(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("OCR遗漏了关键数据") == IssueCategory.OCR_MISSED

    def test_uncompiled(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("这个文档没有编译") == IssueCategory.UNCOMPILED

    def test_search_quality(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("搜不到这个页面") == IssueCategory.SEARCH_QUALITY

    def test_incorrect_info(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("这段内容写错了") == IssueCategory.INCORRECT_INFO

    def test_outdated(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("信息已经过时了") == IssueCategory.OUTDATED

    def test_contradiction(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("两段话互相矛盾") == IssueCategory.CONTRADICTION

    def test_other_fallback(self):
        from scripts.doctor import classify_feedback, IssueCategory
        assert classify_feedback("xyzzy arbitrary text") == IssueCategory.OTHER


class TestRunDoctor:
    def test_no_feedback_returns_error(self):
        from scripts.doctor import run_doctor
        r = run_doctor(feedback="")
        assert r["success"] is False

    def test_list_mode(self):
        from scripts.doctor import run_doctor
        r = run_doctor(list_issues_flag=True)
        assert r["success"] is True and "issues" in r

    def test_resolve_nonexistent(self):
        from scripts.doctor import run_doctor
        r = run_doctor(resolve_id="iss-20990101-999")
        assert r["success"] is False


class TestDoctorIssue:
    def test_to_dict_fields(self):
        from scripts.doctor import DoctorIssue, IssueCategory
        issue = DoctorIssue(
            category=IssueCategory.MISSING_INFO,
            description="test issue",
            diagnosis="test diagnosis",
        )
        d = issue.to_dict()
        assert d["category"] == "missing_info"
        assert d["status"] == "open"
        assert d["id"].startswith("iss-")
