"""Regression coverage for legacy confidence metadata in graph retrieval."""

import json

import graph
import pytest
import search
from confidence import normalize_confidence


@pytest.mark.parametrize(
    "value,expected",
    [
        ("high", 0.9),
        (" Medium ", 0.5),
        ("low", 0.3),
        ("0.85", 0.85),
        (0, 0.0),
        (None, 0.7),
        ("unknown", 0.7),
        ([], 0.7),
        (True, 0.7),
        ("nan", 0.7),
        ("inf", 0.7),
        (-1, 0.0),
        (2, 1.0),
    ],
)
def test_normalize_confidence(value: object, expected: float) -> None:
    assert normalize_confidence(value, default=0.7) == expected


def test_graph_search_reads_legacy_labels(tmp_path) -> None:
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "entities.json").write_text(
        json.dumps(
            {
                "expert": {"name": "expert", "confidence": "high"},
                "expert-zero": {"name": "expert", "confidence": 0},
                "expert-invalid": {"name": "expert", "confidence": "invalid"},
            }
        )
    )
    results = search.graph_search("expert", str(graph_dir))
    assert len(results) == 3
    scores = {r["entity_id"]: r["confidence"] for r in results}
    assert scores["expert"] > scores["expert-invalid"] > scores["expert-zero"]


def test_graph_build_normalizes_confidence(tmp_path) -> None:
    pages = tmp_path / "pages"
    entities = pages / "entities"
    entities.mkdir(parents=True)
    (entities / "expert.md").write_text(
        "---\nid: expert\nconfidence: high\n---\n" "## Relationships\n- *uses* [[tool]] — example\n"
    )
    assert graph.build_entity_registry(str(pages))["expert"]["confidence"] == 0.9
    assert graph.build_edges(str(pages))[0]["confidence"] == 0.9


@pytest.mark.parametrize("value,expected", [("high", 0.9), ("nan", 0.8), (True, 0.8), (0, 0.0)])
def test_claim_confidence(value: object, expected: float) -> None:
    from knowledge_claims import normalize_claim

    claim = normalize_claim({"predicate": "uses", "value": "tool", "confidence": value}, "expert")
    assert claim["confidence"] == expected
    json.dumps(claim, allow_nan=False)


def test_legacy_confidence_in_lint_and_memory(tmp_path, monkeypatch) -> None:
    import crystallize
    import lint

    entities_file = tmp_path / "entities.json"
    entities_file.write_text(
        json.dumps(
            {
                "a": {"name": "Expert", "confidence": "high"},
                "b": {"name": "Expert", "confidence": "low"},
            }
        )
    )
    monkeypatch.setattr(lint, "_get_entities_file", lambda: str(entities_file))
    monkeypatch.setattr(lint, "_get_pages_dir", lambda: tmp_path / "pages")
    assert any(c["type"] == "confidence_mismatch" for c in lint.find_contradictions())
    assert len(lint.rescore_content()) == 2
    monkeypatch.setattr(crystallize, "ENTITIES_FILE", str(entities_file))
    conflicts = crystallize.check_contradictions(
        [{"content": "Expert uses tool", "confidence": "0.1"}]
    )
    assert conflicts[0]["existing_confidence"] == 0.9


def test_bulk_confidence_stats_and_safe_delete(tmp_path, monkeypatch) -> None:
    import bulk

    monkeypatch.setattr(bulk, "GRAPH_DIR", tmp_path)
    monkeypatch.setattr(bulk, "PAGES_DIR", tmp_path / "pages")
    entities_file = tmp_path / "entities.json"
    entities_file.write_text(
        json.dumps(
            {
                "a": {"confidence": "high"},
                "b": {"confidence": "low"},
                "c": {"confidence": "unknown"},
                "d": {"confidence": 0},
            }
        )
    )
    stats = bulk.cmd_stats()
    assert stats["avg_confidence"] == pytest.approx(0.512, abs=0.001)
    result = bulk.cmd_delete_low_confidence(0.4, dry_run=True)
    assert {item["id"] for item in result["items"]} == {"b", "d"}
    assert len(json.loads(entities_file.read_text())) == 4


def test_extractor_normalizes_single_chunk(monkeypatch) -> None:
    from _llm_extract import LLMExtractor

    extractor = LLMExtractor("unused", "http://unused", "unused")
    monkeypatch.setattr(
        extractor,
        "_call",
        lambda *args, **kwargs: json.dumps(
            {
                "entities": [{"id": "expert", "confidence": "high"}],
                "relationships": [{"confidence": "nan"}],
            }
        ),
    )
    result = extractor.extract("short text")
    assert result["entities"][0]["confidence"] == 0.9
    assert result["relationships"][0]["confidence"] == 0.5


def test_extractor_reinforces_legacy_confidence(monkeypatch) -> None:
    from _llm_extract import LLMExtractor

    extractor = LLMExtractor("unused", "http://unused", "unused")
    monkeypatch.setattr(extractor, "_chunk_text", lambda text: ["first", "second"])
    monkeypatch.setattr(
        extractor,
        "_call",
        lambda *args, **kwargs: json.dumps(
            {
                "entities": [{"id": "expert", "confidence": "high"}],
                "relationships": [{"source": "expert", "target": "tool", "confidence": "low"}],
            }
        ),
    )
    result = extractor.extract("two chunks", max_workers=1)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["confidence"] == 1.0
    assert all(rel["confidence"] == 0.3 for rel in result["relationships"])


def test_memory_graph_writes_numeric_confidence(tmp_path, monkeypatch) -> None:
    import crystallize

    entities_file = tmp_path / "entities.json"
    edges_file = tmp_path / "edges.json"
    monkeypatch.setattr(crystallize, "ENTITIES_FILE", str(entities_file))
    monkeypatch.setattr(crystallize, "EDGES_FILE", str(edges_file))
    crystallize.update_graph(
        [{"id": "expert", "confidence": "high"}],
        [{"source": "expert", "target": "tool", "confidence": "low"}],
    )
    assert json.loads(entities_file.read_text())["expert"]["confidence"] == 0.9
    assert json.loads(edges_file.read_text())["edges"][0]["confidence"] == 0.3
