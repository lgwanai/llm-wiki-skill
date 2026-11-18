"""Replay the original mixed-Wiki answers in both hint configurations."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "evals" / "p1_mixed_wiki"
CORPUS_SHA256 = "039769d6d95c52829bc3ea806a6fbc69918d4ea07f61d672d4bc4b0afb7d02bf"
EXPECTED_HINTS = {"C01": ("workshop", "7.40pm"), "C02": ("market", "2.15pm")}


@pytest.fixture(scope="module")
def fixed_answer_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("p1-mixed-wiki")
    report = root / "report.json"
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("LLM_WIKI_") and not name.endswith("_API_KEY")
    }
    for command in (
        ("prepare", "--rounds", "1"),
        ("score", "--replay-baseline", str(EVAL / "results.json"), "--output", str(report)),
    ):
        process = subprocess.run(
            [sys.executable, str(EVAL / "run.py"), *command, "--workspace", str(root / "run")],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert process.returncode == 0, f"{command[0]} failed\n{process.stdout}\n{process.stderr}"

    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["corpus_sha256"] == CORPUS_SHA256
    assert set(result["arms"]) == {"on", "off"}
    return result


@pytest.mark.parametrize("arm", ["on", "off"])
def test_fixed_answers_retrieve_and_pass_verification(fixed_answer_report: dict, arm: str) -> None:
    rows = fixed_answer_report["arms"][arm]["rows"]
    assert len(rows) == 27
    failures = []
    for row in rows:
        case = f"{row['id']} (hints={arm})"
        if row["answerable"]:
            if row["evidence_hits"] != len(row["expected"]):
                failures.append(f"{case}: missing evidence")
            if not row["fully_supported"]:
                failures.append(f"{case}: unsupported citations {row['claims']}")
            if row["local_verify_status"] != "pass":
                failures.append(f"{case}: verification failed {row['local_verify_reasons']}")
        elif not row["correct_refusal"]:
            failures.append(f"{case}: expected refusal, got {row['status']} {row['claims']}")
    assert not failures, "\n" + "\n".join(failures)


@pytest.mark.parametrize("arm", ["on", "off"])
def test_hint_ablation_keeps_hints_with_their_source(fixed_answer_report: dict, arm: str) -> None:
    failures = []
    for row in fixed_answer_report["arms"][arm]["rows"]:
        case = f"{row['id']} (hints={arm})"
        expected = EXPECTED_HINTS.get(row["id"]) if arm == "on" else None
        hints = row["visible_hints"]
        if expected is None:
            if row["hint_kinds"] or row["hint_exposed"] or hints:
                failures.append(f"{case}: unexpected hint {hints or row['hint_kinds']}")
            continue

        if (
            row["hint_kinds"] != ["weekday_closing_time"]
            or not row["hint_exposed"]
            or len(hints) != 1
        ):
            failures.append(f"{case}: expected one closing-time hint, got {hints}")
            continue
        hint = hints[0]
        origin, value = expected
        prefix = rf"- weekday_closing_time: {re.escape(value)}(?:\s|$)"
        if hint["doc"] != origin or not re.match(prefix, hint["statement"]):
            failures.append(f"{case}: expected {value} from {origin}, got {hint}")
    assert not failures, "\n" + "\n".join(failures)
