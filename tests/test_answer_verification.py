"""Verify the answer delivered by either synthesis mode before writing it back."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import query

POLICY = "# 客户记录政策\n\n员工禁止导出客户记录。客户记录留存期限为120天，申诉期限为20天。\n"
CITE = " [客户记录政策](/concepts/policy.md)"


@pytest.fixture
def policy_wiki(tmp_path, monkeypatch):
    wiki = tmp_path / ".wiki"
    pages = wiki / "pages" / "concepts"
    pages.mkdir(parents=True)
    policy = pages / "policy.md"
    policy.write_text("---\ntype: Policy\ntitle: 客户记录政策\n---\n" + POLICY, encoding="utf-8")
    monkeypatch.setattr(query, "WIKI_DIR", wiki)
    monkeypatch.setattr(query, "PAGES_DIR", wiki / "pages")
    return wiki, policy


@pytest.mark.parametrize(
    ("question", "wrong", "correct", "finding"),
    [
        (
            "员工可以导出客户记录吗？",
            "员工允许导出客户记录。",
            "员工禁止导出客户记录。",
            "polarity_conflicts",
        ),
        (
            "客户记录留存期限为多少天？",
            "客户记录留存期限为20天。",
            "客户记录留存期限为120天。",
            "unverified_values",
        ),
    ],
)
@pytest.mark.parametrize("mode", ["agent", "llm"])
def test_synthesis_paths_refuse_to_file_wrong_answers(
    policy_wiki,
    monkeypatch,
    mode,
    question,
    wrong,
    correct,
    finding,
):
    wiki, policy = policy_wiki
    original_policy = policy.read_bytes()
    monkeypatch.setattr(
        query,
        "search_wiki",
        lambda *_args, **_kwargs: [
            {"id": "concepts/policy", "type": "policy", "path": str(policy), "score": 1.0}
        ],
    )
    # Turning off informational LLM verification must not disable a write-back gate.
    monkeypatch.setattr(
        query,
        "get_query_config",
        lambda: {"synthesis_mode": mode, "verify_answers": False, "multi_hop_enabled": False},
    )

    def unexpected_model(*_args, **_kwargs):
        pytest.fail("Agent verification must reuse its draft and run without a model")

    if mode == "agent":
        monkeypatch.setattr(query, "call_llm", unexpected_model)
        task = query.query_wiki(question, mode=mode, file_back=True)
        assert task["file_back_skipped"] == "pending_agent_verification"
        assert "--verify-agent-answer" in task["answer"]
        assert not task.get("filed")

        def submit(answer):
            return query.verify_agent_answer(task["answer_task"], answer)
    else:

        def submit(answer):
            monkeypatch.setattr(query, "call_llm", lambda *_args, **_kwargs: answer)
            return query.query_wiki(question, mode=mode, file_back=True)

    rejected = submit(wrong + CITE)
    assert rejected["verification"]["status"] == "warning"
    assert rejected["verification"][finding]
    assert rejected["file_back_skipped"] == "verification_failed"
    assert not rejected.get("filed")
    assert list((wiki / "pages/concepts").iterdir()) == [policy]
    assert policy.read_bytes() == original_policy
    assert not (wiki / "graph").exists()

    approved = submit(correct + CITE)
    assert approved["verification"]["status"] == "pass"
    filed = Path(approved["filed"])
    assert correct in filed.read_text(encoding="utf-8")
    assert wrong not in filed.read_text(encoding="utf-8")

    graph = wiki / "graph" / "entities.json"
    original_answer = filed.read_bytes()
    original_graph = graph.read_bytes()
    if mode == "agent":
        task = query.query_wiki(question, mode=mode, file_back=True)
    try:
        retry = submit(wrong + CITE)
        assert retry["file_back_skipped"] == "verification_failed"
        assert filed.read_bytes() == original_answer
        assert graph.read_bytes() == original_graph
    finally:
        if mode == "agent":
            Path(task["answer_task"]).unlink(missing_ok=True)


@pytest.mark.parametrize(
    "claim",
    [
        "Employees are allowed to export customer records.",
        "The retention period is 20 days.",
        "The retention period is 120 hours.",
    ],
)
def test_english_policy_claims_are_bound_to_the_cited_clause(claim):
    page = {
        "id": "concepts/policy",
        "text": (
            "Employees are prohibited from exporting customer records. "
            "The retention period is 120 days. The appeal period is 20 days."
        ),
    }
    assert query.verify_answer_evidence(claim + CITE, [page])["status"] == "warning"


def test_default_agent_cli_uses_original_evidence_and_verifies_stdin(policy_wiki):
    wiki, policy = policy_wiki
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    env = {
        **os.environ,
        "LLM_WIKI_DIR": str(wiki),
        "LLM_WIKI_SEARCH_STREAMS": "bm25",
    }

    def run(script, *args, draft=None):
        return subprocess.run(
            [sys.executable, str(scripts / script), *args],
            env=env,
            cwd=wiki.parent,
            input=draft,
            text=True,
            capture_output=True,
            timeout=15,
        )

    search = run("wiki.py", "query", "客户记录留存期限", "--mode", "agent", "--file-back", "--json")
    assert search.returncode == 0, search.stderr
    task = json.loads(search.stdout)["answer_task"]
    bad = run(
        "query.py",
        "--verify-agent-answer",
        task,
        draft="客户记录留存期限为20天。" + CITE,
    )
    assert bad.returncode == 1, bad.stderr
    assert json.loads(bad.stdout)["verification"]["unverified_values"][0]["value"] == "20"
    assert list((wiki / "pages/concepts").iterdir()) == [policy]
    good = run(
        "query.py",
        "--verify-agent-answer",
        task,
        draft="客户记录留存期限为120天。" + CITE,
    )
    assert good.returncode == 0, good.stderr
    assert Path(json.loads(good.stdout)["filed"]).is_file()


def test_agent_file_back_rejects_evidence_changed_after_retrieval(policy_wiki, monkeypatch):
    wiki, policy = policy_wiki
    page = {"id": "concepts/policy", "type": "policy", "path": str(policy), "score": 1.0}
    monkeypatch.setattr(query, "search_wiki", lambda *_args, **_kwargs: [page])
    task = query.query_wiki("客户记录的留存期限", mode="agent", file_back=True)
    try:
        policy.write_text(POLICY.replace("120天", "90天"), encoding="utf-8")
        rejected = query.verify_agent_answer(
            task["answer_task"], "客户记录留存期限为120天。" + CITE
        )
        assert rejected["verification"]["reason"] == "evidence_changed"
        assert rejected["file_back_skipped"] == "verification_failed"
        assert list((wiki / "pages/concepts").iterdir()) == [policy]
    finally:
        Path(task["answer_task"]).unlink(missing_ok=True)


def test_number_binding_prefers_the_local_field_over_the_shared_subject() -> None:
    page = {
        "id": "concepts/policy",
        "text": "青榫站工单录音留存期限为 40 天。申诉窗口为 87 天。",
    }
    answer = "青榫站工单录音争议申诉窗口为 87 天。" + CITE
    assert query.verify_answer_evidence(answer, [page])["status"] == "pass"
    wrong = query.verify_answer_evidence(answer.replace("87 天", "40 天"), [page])
    assert wrong["status"] == "warning"
    assert wrong["unverified_values"][0]["evidence_values"] == ["87"]
    both = "青榫站工单录音留存期限为 40 天和申诉窗口为 87 天。" + CITE
    swapped = "青榫站工单录音留存期限为 87 天和申诉窗口为 40 天。" + CITE
    assert query.verify_answer_evidence(both, [page])["status"] == "pass"
    rejected = query.verify_answer_evidence(swapped, [page])
    assert rejected["status"] == "warning"
    expected_by_claim = {
        entry["value"]: entry["evidence_values"] for entry in rejected["unverified_values"]
    }
    assert expected_by_claim == {"87": ["40"], "40": ["87"]}


@pytest.mark.parametrize("mode", ["agent", "llm"])
def test_applicability_checks_the_boundary_and_blocks_inactive_file_back(
    policy_wiki,
    monkeypatch,
    mode,
):
    wiki, old = policy_wiki
    new = old.with_name("policy-new.md")
    future = old.with_name("policy-future.md")
    old.write_text(
        "---\ntype: Policy\ntitle: 回传规则甲版\neffective_from: 2026-02-10\n"
        "effective_until: 2026-07-01\n---\n# 回传规则甲版\n\n回传宽限为 13 分钟。",
        encoding="utf-8",
    )
    new.write_text(
        "---\ntype: Policy\ntitle: 回传规则乙版\neffective_from: 2026-07-01\n"
        "effective_until: 2026-12-01\n---\n# 回传规则乙版\n\n回传宽限为 26 分钟。",
        encoding="utf-8",
    )
    future.write_text(
        "---\ntype: Policy\ntitle: 回传规则丙版\neffective_from: 2026-12-01\n"
        "---\n# 回传规则丙版\n\n回传宽限为 42 分钟。",
        encoding="utf-8",
    )
    original_policies = {path: path.read_bytes() for path in (old, new, future)}
    pages = [
        {"id": f"concepts/{page.stem}", "type": "policy", "path": str(page), "score": 1.0}
        for page in (old, new, future)
    ]
    question = "截至 2026 年 7 月 1 日，回传宽限是多少分钟？"
    monkeypatch.setattr(query, "search_wiki", lambda *_args, **_kwargs: pages)
    monkeypatch.setattr(query, "get_query_config", lambda: {"multi_hop_enabled": False})

    if mode == "agent":
        monkeypatch.setattr(
            query, "call_llm", lambda *_args, **_kwargs: pytest.fail("No model needed")
        )
        task = query.query_wiki(question, mode=mode, file_back=True)

        def submit(answer):
            return query.verify_agent_answer(task["answer_task"], answer)
    else:

        def submit(answer):
            monkeypatch.setattr(query, "call_llm", lambda *_args, **_kwargs: answer)
            return query.query_wiki(question, mode=mode, file_back=True)

    for wrong, reason in [
        ("当日适用甲版，回传宽限为 13 分钟。" + CITE, "cited_policy_not_effective"),
        (
            "当日适用丙版，回传宽限为 42 分钟。 [政策](/concepts/policy-future.md)",
            "cited_policy_not_effective",
        ),
        (
            "截至2026-07-02，适用乙版，回传宽限为 26 分钟。 [政策](/concepts/policy-new.md)",
            "answer_date_differs_from_query",
        ),
        (
            "2026-07-02 有效的乙版规定回传宽限为 26 分钟。 [政策](/concepts/policy-new.md)",
            "answer_date_differs_from_query",
        ),
        (
            "当日适用丙版，回传宽限为 26 分钟。 [政策](/concepts/policy-new.md)",
            "applicable_version_unverified",
        ),
    ]:
        result = submit(wrong)
        assert result["verification"]["temporal_conflicts"][0]["reason"] == reason
        assert result["file_back_skipped"] == "verification_failed"
        assert not result.get("filed")
        assert {
            path: path.read_bytes() for path in (wiki / "pages" / "concepts").iterdir()
        } == original_policies
        assert not (wiki / "graph").exists()

    alternate = query.verify_answer_evidence(
        "2026-07-01 有效的乙版规定回传宽限为 26 分钟。 [政策](/concepts/policy-new.md)",
        pages,
        question,
    )
    assert alternate["status"] == "pass"
    result = submit(
        "2026 年 7 月 1 日适用的乙版回传宽限为 26 分钟。 [政策](/concepts/policy-new.md)"
    )
    assert result["verification"]["status"] == "pass"
    assert Path(result["filed"]).is_file()


def test_raw_temporal_evidence_binds_to_the_same_source_revision(tmp_path):
    old = tmp_path / "old.md"
    old.write_text(
        "---\ntype: Policy\nsource_id: example-id\nsource_version: previous\n"
        "effective_from: 2026-02-10\n---\n# 旧规则\n回传宽限为 13 分钟。",
        encoding="utf-8",
    )
    new = tmp_path / "new.md"
    new.write_text(
        "---\ntype: Policy\nsource_id: example-id\nsource_version: current\n"
        "effective_from: 2026-07-01\n---\n# 新规则\n回传宽限为 26 分钟。",
        encoding="utf-8",
    )
    raw_id = "source/evidence/example/pages/page-0001"
    question = "截至2026-06-25，规则规定的回传宽限是多少分钟？"
    selected = [{"id": "old", "path": str(old)}, {"id": "new", "path": str(new)}]
    raw = {"id": raw_id, "type": "source_evidence", "source_id": "example-id"}
    reject = query.verify_answer_evidence(
        f"回传宽限为 26 分钟。 [原文](/{raw_id}.md)",
        [*selected, {**raw, "source_version": "current", "text": "回传宽限为 26 分钟。"}],
        question,
    )
    assert reject["temporal_conflicts"][0]["reason"] == "cited_policy_not_effective"
    accept = query.verify_answer_evidence(
        f"回传宽限为 13 分钟。 [原文](/{raw_id}.md)",
        [*selected, {**raw, "source_version": "previous", "text": "回传宽限为 13 分钟。"}],
        question,
    )
    assert accept["status"] == "pass"


def test_as_of_rule_requires_interval_even_when_the_undated_text_matches():
    evidence = [{"id": "concepts/policy", "text": "回传宽限为 26 分钟。"}]
    result = query.verify_answer_evidence(
        "回传宽限为 26 分钟。" + CITE, evidence, "截至2026-09-03，回传规则的宽限是多久？"
    )
    assert result["temporal_conflicts"][0]["reason"] == "effective_interval_unverified"
    assert result["status"] == "warning"


@pytest.mark.parametrize(
    "statement",
    [
        "潮桥工坊借具窗口在周一至周四于 7.40pm 停止开放，周二适用该时段。",
        "潮桥工坊借具窗口周二在周一至周四的营业时段内，7.40pm 停止借具。",
    ],
)
def test_weekday_reference_requires_the_same_supported_hours(statement: str) -> None:
    page = {
        "id": "concepts/policy",
        "text": (
            "潮桥工坊借具窗口开放时间如下。\n"
            "Monday to Thursday: 10.00am–7.40pm\nFriday: 10.00am–5.00pm"
        ),
    }
    answer = statement + CITE
    assert query.verify_answer_evidence(answer, [page])["status"] == "pass"
    assert (
        query.verify_answer_evidence(answer.replace("周二", "周日"), [page])["status"] == "warning"
    )
    assert (
        query.verify_answer_evidence(answer.replace("7.40pm", "5.00pm"), [page])["status"]
        == "warning"
    )
    assert (
        query.verify_answer_evidence(answer.replace("7.40pm", "7.40am"), [page])["status"]
        == "warning"
    )
    assert (
        query.verify_answer_evidence(answer.replace("周四", "周五"), [page])["status"] == "warning"
    )
