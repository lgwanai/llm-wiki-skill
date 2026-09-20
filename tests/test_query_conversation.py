"""Conversation resolution must affect retrieval while preserving evidence boundaries."""

import json

import pytest

from scripts import query, query_conversation


def test_history_is_bounded_and_role_ordered() -> None:
    valid = [{"role": "user", "content": "Falcon"}, {"role": "assistant", "content": "3 retries"}]
    assert query_conversation.validate_history(valid) == valid
    for invalid in [
        None,
        {},
        [valid[0]],
        valid * 7,
        [{"role": "system", "content": "bad"}, valid[1]],
        [valid[0], {"role": "assistant", "content": "x" * 8001}],
        [{"role": item["role"], "content": "x" * 5000} for item in valid] * 3,
    ]:
        with pytest.raises(ValueError):
            query_conversation.validate_history(invalid)


def test_resolution_receives_history_and_current_question(monkeypatch) -> None:
    history = [{"role": "user", "content": "Falcon retries"}, {"role": "assistant", "content": "3"}]
    calls = []

    def model(system: str, user: str, **kwargs) -> str:
        calls.append((system, json.loads(user)))
        return "Falcon retry wait time?"

    monkeypatch.setattr(query_conversation, "call_llm", model)
    assert query_conversation.resolve_followup("How long?", history) == "Falcon retry wait time?"
    assert calls[0][1] == {"conversation": history, "current_question": "How long?"}
    assert "切换了话题" in calls[0][0]


def test_empty_rewrite_fails_instead_of_unrelated_search(monkeypatch) -> None:
    monkeypatch.setattr(query_conversation, "call_llm", lambda *a, **kw: "")
    with pytest.raises(ValueError, match="未能理解"):
        query_conversation.resolve_followup("Why?", [])


def test_followup_search_uses_resolved_question_and_synthesis_gets_original(monkeypatch) -> None:
    import query_conversation as runtime

    history = [{"role": "user", "content": "Falcon retries"}, {"role": "assistant", "content": "3"}]
    monkeypatch.setattr(runtime, "resolve_followup", lambda *a: "Falcon wait time")
    monkeypatch.setattr(
        query, "get_query_config", lambda: {"multi_hop_enabled": False, "verify_answers": False}
    )
    searched = []

    def search(question: str, **kwargs) -> list:
        searched.append(question)
        return [{"id": "falcon", "type": "guide", "score": 1, "description": "wait five seconds"}]

    monkeypatch.setattr(query, "search_wiki", search)
    synthesis = []

    def answer(question: str, pages: list, **kwargs) -> str:
        synthesis.append(question)
        return "Wait five seconds."

    monkeypatch.setattr(query, "synthesize_answer", answer)
    result = query.query_wiki("How long?", mode="llm", conversation=history)
    assert searched == ["Falcon wait time"]
    assert synthesis[0].startswith("How long?")
    assert "不是事实证据" in synthesis[0]
    assert "Falcon retries" in synthesis[0]
    assert result["query"] == "How long?"
    assert result["retrieval_query"] == "Falcon wait time"
