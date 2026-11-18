"""Exercise version visibility through normal compile and query entry points."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]


def _run(project: Path, script: str, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / script), *map(str, args)],
        cwd=project,
        env={**os.environ, "LLM_WIKI_DIR": str(project / ".wiki")},
        capture_output=True,
        text=True,
        timeout=20,
    )


def _ok(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _compile(project: Path, source: Path) -> Path:
    result = _ok(_run(project, "wiki.py", "compile", source, "--mode", "agent"))
    todo, _, _ = result.partition(" ordered tasks)")
    return Path(todo.rsplit("Todo: ", 1)[1].rsplit(" (", 1)[0])


def _query(project: Path, query: str) -> list[dict]:
    runner = (
        "import json, sys; from wiki import cmd_query; "
        "print(json.dumps(cmd_query(sys.argv[1], synthesis=False, fmt='json'), default=str))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", runner, query],
        cwd=project,
        env={
            **os.environ,
            "LLM_WIKI_DIR": str(project / ".wiki"),
            "PYTHONPATH": str(REPO / "scripts"),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(_ok(completed))["source_details"]


def _write_concept(todo: Path, identifier: str, phrase: str, quote: str | None) -> dict:
    metadata = json.loads(todo.read_text())["metadata"]
    item = json.loads(todo.read_text())["items"][0]
    page = Path(metadata["staged_pages"]) / f"{identifier}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {"id": identifier, "type": "concept", "title": phrase}
    if quote is not None:
        frontmatter["source_citations"] = [{"artifact": item["source_citation"], "quote": quote}]
    page.write_text(
        "---\n" + yaml.safe_dump(frontmatter) + "---\n\n# " + phrase + "\n\n" + phrase + "\n",
        encoding="utf-8",
    )
    return item


def _start(project: Path, todo: Path, item: dict) -> None:
    _ok(_run(project, "compile_todo.py", "start", todo, item["id"]))


def _complete(project: Path, todo: Path, item: dict, output: str) -> dict:
    return json.loads(
        _ok(_run(project, "compile_todo.py", "complete", todo, item["id"], "--output", output))
    )


def _verify(project: Path, todo: Path) -> dict:
    return json.loads(_ok(_run(project, "compile_todo.py", "verify", todo)))


def test_same_name_manuals_remain_independent_and_interrupted_update_never_publishes(tmp_path):
    wiki = tmp_path / ".wiki"
    first = tmp_path / "north" / "manual.md"
    second = tmp_path / "south" / "manual.md"
    for source in (first, second):
        source.parent.mkdir()
    secret = "sk-" + "SyntheticPlaceholderOnly1234567890XYZ"
    generic_secret = "test_fixture_value_for_password_42"
    first.write_text(f'# amberfalcon baseline\n\napi_key: "{secret}"\n', encoding="utf-8")
    second.write_text(f"# cobaltlynx unique\n\npassword = '{generic_secret}'\n", encoding="utf-8")

    north = _compile(tmp_path, first)
    assert not _query(tmp_path, "amberfalcon")
    north_item = _write_concept(
        north, "concepts/north", "amberfalcon baseline", "amberfalcon baseline"
    )
    _start(tmp_path, north, north_item)
    assert not _complete(tmp_path, north, north_item, "concepts/north")["coverage_complete"]
    assert not _query(tmp_path, "amberfalcon")
    initial = _verify(tmp_path, north)

    south = _compile(tmp_path, second)
    south_item = _write_concept(south, "concepts/south", "cobaltlynx unique", "cobaltlynx unique")
    _start(tmp_path, south, south_item)
    _complete(tmp_path, south, south_item, "concepts/south")
    south_revision = _verify(tmp_path, south)
    assert initial["metadata"]["source_id"] != south_revision["metadata"]["source_id"]
    for query, revision in (("amberfalcon", initial), ("cobaltlynx", south_revision)):
        matches = _query(tmp_path, query)
        assert matches
        assert {hit["source_id"] for hit in matches} == {revision["metadata"]["source_id"]}

    first.write_text(f'# scarletotter revision\n\napi_key: "{secret}"\n', encoding="utf-8")
    interrupted = _compile(tmp_path, first)
    interrupted_item = _write_concept(
        interrupted, "concepts/north", "scarletotter revision", "not in the source"
    )
    _start(tmp_path, interrupted, interrupted_item)
    rejected = _run(
        tmp_path,
        "compile_todo.py",
        "complete",
        interrupted,
        interrupted_item["id"],
        "--output",
        "concepts/north",
    )
    assert rejected.returncode != 0 and "quote does not match" in rejected.stderr
    _ok(
        _run(
            tmp_path,
            "compile_todo.py",
            "fail",
            interrupted,
            interrupted_item["id"],
            "--error",
            f"interrupted with test credential {secret}",
        )
    )
    assert _run(tmp_path, "compile_todo.py", "verify", interrupted).returncode != 0
    assert _query(tmp_path, "amberfalcon") and not _query(tmp_path, "scarletotter")

    retry = _compile(tmp_path, first)
    retry_item = _write_concept(
        retry, "concepts/north", "scarletotter revision", "scarletotter revision"
    )
    _start(tmp_path, retry, retry_item)
    _complete(tmp_path, retry, retry_item, "concepts/north")
    assert _query(tmp_path, "amberfalcon") and not _query(tmp_path, "scarletotter")

    # Terminate the publishing process after it actually writes a live page.
    runner = """
import os, sys
from pathlib import Path
from compile_todo import verify_manifest
import source_versions
original_write = source_versions.atomic_bytes
def interrupted_write(path, data):
    original_write(path, data)
    if path == Path(sys.argv[2]):
        os._exit(23)
source_versions.atomic_bytes = interrupted_write
verify_manifest(sys.argv[1])
"""
    crashed = subprocess.run(
        [sys.executable, "-c", runner, str(retry), str(wiki / "pages/concepts/north.md")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(REPO / "scripts"), "LLM_WIKI_DIR": str(wiki)},
        timeout=20,
    )
    assert crashed.returncode == 23
    assert _query(tmp_path, "amberfalcon") and not _query(tmp_path, "scarletotter")

    published = _verify(tmp_path, retry)
    assert _verify(tmp_path, retry)["published_revision"] == published["published_revision"]
    assert published["metadata"]["source_id"] == initial["metadata"]["source_id"]
    assert published["metadata"]["source_version"] != initial["metadata"]["source_version"]
    assert not _query(tmp_path, "amberfalcon")
    assert _query(tmp_path, "scarletotter") and _query(tmp_path, "cobaltlynx")
    old_bundle = Path(initial["metadata"]["evidence_manifest"]).parent
    assert "amberfalcon" in (old_bundle / "raw.md").read_text()
    assert (old_bundle / "compiled_pages/concepts/north.md").is_file()
    for path in wiki.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert secret.encode() not in data, path
            assert generic_secret.encode() not in data, path
    assert secret in first.read_text()
    assert generic_secret in second.read_text()


def test_llm_compile_publishes_only_after_pipeline_succeeds(tmp_path, monkeypatch):
    import compile_v2
    import ledger
    from raw_evidence import search_raw_evidence

    wiki = tmp_path / ".wiki"
    source = tmp_path / "north" / "manual.md"
    other = tmp_path / "south" / "manual.md"
    for file in (source, other):
        file.parent.mkdir()
    monkeypatch.setattr(ledger, "LEDGER_DB", wiki / "ledger" / "ledger.duckdb")
    monkeypatch.setattr(compile_v2, "WIKI_DIR", wiki)
    for attr, path in {
        "PAGES_DIR": wiki / "pages",
        "ENTITIES_DIR": wiki / "pages/entities",
        "CONCEPTS_DIR": wiki / "pages/concepts",
        "INDEX_FILE": wiki / "pages/index.md",
    }.items():
        monkeypatch.setattr(compile_v2, attr, path)

    def reply(phrase: str) -> str:
        return (
            f"---\ntype: concept\ntitle: Manual\n---\n\n# Manual\n\n{phrase}\n\n"
            f"## Data\n| Name | Value |\n| --- | --- |\n| Lookup | {phrase} |\n===PAGE_END==="
        )

    source.write_text("amberfalcon baseline")
    monkeypatch.setattr(compile_v2, "call_llm", lambda *_: reply(source.read_text()))
    first = compile_v2.compile_source(str(source))
    other.write_text("cobaltlynx unique")
    monkeypatch.setattr(compile_v2, "call_llm", lambda *_: reply(other.read_text()))
    other_result = compile_v2.compile_source(str(other))
    assert other_result["pages"][0]["id"] != first["pages"][0]["id"]
    assert search_raw_evidence("cobaltlynx", wiki)
    assert ledger.search_ledgers("amberfalcon")
    monkeypatch.setattr(compile_v2, "call_llm", lambda *_: reply(source.read_text()))

    source.write_text("scarletotter revision")
    publish_graph = compile_v2.update_graph

    def interrupt(*args, **kwargs):
        assert search_raw_evidence("amberfalcon", wiki)
        assert not search_raw_evidence("scarletotter", wiki)
        raise RuntimeError("simulated compiler interruption")

    monkeypatch.setattr(compile_v2, "update_graph", interrupt)
    with pytest.raises(RuntimeError, match="simulated compiler interruption"):
        compile_v2.compile_source(str(source))
    assert "amberfalcon" in (wiki / "pages/concepts/manual.md").read_text()
    assert ledger.search_ledgers("amberfalcon")
    assert not ledger.search_ledgers("scarletotter")
    monkeypatch.setattr(compile_v2, "update_graph", publish_graph)
    second = compile_v2.compile_source(str(source))
    assert "scarletotter" in (wiki / "pages/concepts/manual.md").read_text()
    assert "amberfalcon" not in (wiki / "pages/concepts/manual.md").read_text()
    assert not search_raw_evidence("amberfalcon", wiki)
    assert search_raw_evidence("scarletotter", wiki)
    assert ledger.search_ledgers("cobaltlynx")
    assert not ledger.search_ledgers("amberfalcon")
    assert ledger.search_ledgers("scarletotter")
    assert Path(first["raw_evidence"]["raw_path"]).is_file()
    assert first["raw_evidence"]["source_id"] == second["raw_evidence"]["source_id"]


def test_stale_worklist_cannot_replace_a_newer_publication(tmp_path):
    source = tmp_path / "manual.md"
    source.write_text("# initial draft", encoding="utf-8")
    stale = _compile(tmp_path, source)
    first_item = _write_concept(stale, "concepts/manual", "initial draft", "initial draft")
    _start(tmp_path, stale, first_item)
    _complete(tmp_path, stale, first_item, "concepts/manual")

    source.write_text("# current revision", encoding="utf-8")
    new = _compile(tmp_path, source)
    second_item = _write_concept(new, "concepts/manual", "current revision", "current revision")
    _start(tmp_path, new, second_item)
    _complete(tmp_path, new, second_item, "concepts/manual")
    _verify(tmp_path, new)
    rejected = _run(tmp_path, "compile_todo.py", "verify", stale)
    assert rejected.returncode == 1
    assert "newer revision has been published" in rejected.stdout
    assert not _query(tmp_path, "initial")
    assert _query(tmp_path, "current revision")


def test_directory_worklist_publishes_verified_children(tmp_path):
    source = tmp_path / "manuals" / "north" / "manual.md"
    source.parent.mkdir(parents=True)
    source.write_text("# northbound procedure", encoding="utf-8")

    directory = _compile(tmp_path, tmp_path / "manuals")
    parent_item = json.loads(directory.read_text())["items"][0]
    _start(tmp_path, directory, parent_item)

    child = _compile(tmp_path, Path(parent_item["source_path"]))
    child_item = _write_concept(
        child, "concepts/manual", "northbound procedure", "northbound procedure"
    )
    _start(tmp_path, child, child_item)
    _complete(tmp_path, child, child_item, "concepts/manual")
    result = _verify(tmp_path, child)
    assert result["metadata"]["source_id"] == parent_item["source_id"]

    _ok(
        _run(
            tmp_path, "compile_todo.py", "complete", directory, parent_item["id"], "--child", child
        )
    )
    assert _verify(tmp_path, directory)["coverage_complete"]
    assert _query(tmp_path, "northbound")
