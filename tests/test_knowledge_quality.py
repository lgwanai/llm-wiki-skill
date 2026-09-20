"""End-to-end regression tests for understanding and retrieval quality."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

import scripts.benchmark as benchmark
import scripts.knowledge_claims as knowledge_claims
import scripts.okf as okf
import scripts.query as query
import scripts.query_understanding as query_understanding
import scripts.rerank as rerank
import scripts.search as search


def _write_page(path: Path, metadata: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + body,
        encoding="utf-8",
    )


def test_extract_claims_preserves_table_qualifiers_and_footnotes() -> None:
    metadata = {
        "title": "差旅制度",
        "jurisdiction": "上海",
        "audience": ["正式员工"],
        "effective_from": "2026-10-01",
    }
    body = """# 差旅制度

## Key Facts
| Attribute | Value |
|---|---|
| 住宿上限 | 800元/晚[^a] |

## 城市标准
| 城市 | 上限 | 等级 |
|---|---:|---|
| 上海 | 800元 | A |

[^a]: 展会期间按审批结果执行。
"""

    claims = knowledge_claims.extract_claims(metadata, body, "entities/travel-policy")

    limit_claim = next(claim for claim in claims if claim["predicate"] == "住宿上限")
    assert limit_claim["jurisdiction"] == ["上海"]
    assert limit_claim["audience"] == ["正式员工"]
    assert limit_claim["effective_from"] == "2026-10-01"
    table_claim = next(claim for claim in claims if claim["source_kind"] == "table")
    assert table_claim["source"]["columns"] == ["城市", "上限", "等级"]
    assert "展会期间" in " ".join(limit_claim["footnotes"])


def test_compile_normalizer_materializes_atomic_claims() -> None:
    import scripts.compile_v2 as compile_v2

    page = """---
type: policy
title: API 限额
document_status: official
source_authority: 1.0
jurisdiction: 中国大陆
---
# API 限额

## Key Facts
| Attribute | Value |
|---|---|
| 每分钟请求数 | 1200 |
"""

    parsed = compile_v2._okf_page_from_model(page, "policy.pdf")

    assert parsed is not None
    normalized, metadata, page_id, _ = parsed
    assert page_id == "entities/api-限额"
    assert metadata["document_status"] == "official"
    assert metadata["source_authority"] == 1.0
    assert metadata["claims"][0]["predicate"] == "每分钟请求数"
    assert "claims:" in normalized


def test_okf_validator_reports_malformed_claim_extension(tmp_path: Path) -> None:
    _write_page(
        tmp_path / "bad.md",
        {"type": "policy", "title": "Bad", "claims": [{"subject": "A"}]},
        "# Bad\n",
    )

    report = okf.validate_bundle(tmp_path)

    assert report["valid"] is True
    assert any("predicate is required" in warning["message"] for warning in report["warnings"])


def test_entity_resolution_fuzzy_match_requires_type_and_clear_winner(tmp_path: Path) -> None:
    import scripts.compile_v2 as compile_v2

    catalog = [
        {
            "id": "concepts/rate-limit-policy",
            "path": tmp_path / "rate.md",
            "type": "concept",
            "title": "Rate Limiting Policy",
            "names": {"Rate Limiting Policy"},
            "keys": {compile_v2._identity_key("Rate Limiting Policy")},
        }
    ]

    resolved = compile_v2._resolve_existing_concept(
        {"type": "concept", "title": "Rate Limit Policy"},
        "concepts/new-rate-policy",
        catalog,
    )
    wrong_type = compile_v2._resolve_existing_concept(
        {"type": "framework", "title": "Rate Limit Policy"},
        "concepts/new-rate-framework",
        catalog,
    )

    assert resolved == ("concepts/rate-limit-policy", tmp_path / "rate.md")
    assert wrong_type is None


def test_structured_query_plan_extracts_scope_relation_and_constraints() -> None:
    plan = query_understanding.understand_query(
        "截至2026年9月18日，对于上海外包员工，差旅额度不得超过800元吗？"
    )

    assert plan["intent"] == "temporal_as_of"
    assert "上海" in plan["jurisdictions"]
    assert any("外包员工" in value for value in plan["audiences"])
    assert plan["numeric_constraints"][0]["value"] == "800"
    assert "active rule" not in plan["required_evidence"]
    assert "rule active at requested time" in plan["required_evidence"]


def test_claim_search_prefers_matching_scope_and_official_source(
    tmp_path: Path, monkeypatch
) -> None:
    pages = tmp_path / "pages"
    common_claim = {
        "subject": "外包员工",
        "predicate": "住宿上限",
        "value": "800元",
    }
    _write_page(
        pages / "shanghai.md",
        {
            "type": "policy",
            "title": "上海差旅",
            "jurisdiction": "上海",
            "audience": ["外包员工"],
            "document_status": "official",
            "claims": [common_claim],
        },
        "# 上海差旅\n",
    )
    _write_page(
        pages / "beijing.md",
        {
            "type": "policy",
            "title": "北京差旅",
            "jurisdiction": "北京",
            "audience": ["正式员工"],
            "document_status": "draft",
            "claims": [common_claim],
        },
        "# 北京差旅\n",
    )
    monkeypatch.setattr(search, "_CLAIM_CACHE_FILE", tmp_path / "claims.json")
    monkeypatch.setattr(search, "_cache_marker", None)
    plan = query.plan_query("上海外包员工住宿上限")

    results = search.claim_search("上海外包员工住宿上限", str(pages), 5, plan)

    assert results[0]["file"] == "shanghai"
    assert results[0]["source_authority"] == 1.0
    assert results[0]["matched_claim"]["jurisdiction"] == ["上海"]


def test_compiled_claim_is_retrievable_through_official_query_pipeline(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.compile_v2 as compile_v2

    page = """---
type: policy
title: 年假制度
audience: [正式员工]
document_status: official
---
# 年假制度

## Key Facts
| Attribute | Value |
|---|---|
| 年假天数 | 10天 |
"""
    parsed = compile_v2._okf_page_from_model(page, "leave-policy.md")
    assert parsed is not None
    normalized, _, _, _ = parsed
    pages = tmp_path / "pages"
    target = pages / "leave-policy.md"
    target.parent.mkdir(parents=True)
    target.write_text(normalized, encoding="utf-8")

    monkeypatch.setattr(query, "PAGES_DIR", pages)
    monkeypatch.setattr(query, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(query, "_entities_cache", {})
    monkeypatch.setattr(
        query,
        "get_query_config",
        lambda: {"search_streams": "claim", "parallel_search": False},
    )
    monkeypatch.setattr(query, "get_embeddings_config", lambda: {"enabled": False})
    monkeypatch.setattr(query, "get_reranker_config", lambda: {"enabled": False})
    monkeypatch.setattr(search, "_CLAIM_CACHE_FILE", tmp_path / "claim-index.json")
    monkeypatch.setattr(search, "_cache_marker", None)

    results = query.search_wiki("正式员工年假天数", limit=1)

    assert results[0]["id"] == "leave-policy"
    assert results[0]["matched_claim"]["value"] == "10天"
    assert "claim" in results[0]["stream"]


def test_reranker_candidate_text_prioritizes_claim_and_late_section(tmp_path: Path) -> None:
    page = tmp_path / "long.md"
    page.write_text(
        "# Long\n\n## Background\n" + "noise " * 2000 + "\n## Limits\nThreshold 1200.\n",
        encoding="utf-8",
    )
    result = {
        "path": str(page),
        "matched_section": "Limits",
        "matched_claim": {"subject": "API", "predicate": "limit", "value": "1200"},
    }

    text = rerank._candidate_text(result, 300)

    assert text.startswith("API | limit | 1200")
    assert "Threshold 1200" in text


def test_claim_conflict_respects_jurisdiction_and_effective_interval() -> None:
    base = {
        "subject": "员工",
        "predicate": "年假",
        "value": "10天",
        "jurisdiction": ["上海"],
        "effective_from": "2025-01-01",
        "effective_until": "2026-01-01",
    }
    different_region = {**base, "value": "12天", "jurisdiction": ["北京"]}
    future_version = {
        **base,
        "value": "12天",
        "effective_from": "2026-01-01",
        "effective_until": "2027-01-01",
    }
    overlapping = {**base, "value": "12天", "effective_from": "2025-06-01"}

    assert knowledge_claims.claims_conflict(base, different_region) is False
    assert knowledge_claims.claims_conflict(base, future_version) is False
    assert knowledge_claims.claims_conflict(base, overlapping) is True


def test_answer_verification_flags_semantically_unsupported_claim(tmp_path: Path) -> None:
    page = tmp_path / "policy.md"
    page.write_text("# Policy\n\nThe API threshold is 10000 requests.", encoding="utf-8")

    report = query.verify_answer_evidence(
        "The policy guarantees unlimited storage and global legal compliance "
        "[Policy](/concepts/policy.md).",
        [{"id": "concepts/policy", "path": str(page)}],
    )

    assert report["status"] == "warning"
    assert report["unsupported_claims"]


def test_benchmark_manifest_pins_dataset_and_safe_query_config(tmp_path: Path, monkeypatch) -> None:
    eval_file = tmp_path / "cases.jsonl"
    content = json.dumps({"query": "q", "scenario": "scope"}) + "\n"
    eval_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        "config.get_query_config",
        lambda: {
            "search_streams": "claim,bm25",
            "max_results": 5,
            "api_key": "must-not-appear",
        },
    )

    manifest = benchmark.build_benchmark_manifest(
        eval_file,
        [{"query": "q", "scenario": "scope"}],
        "retrieval",
        5,
    )

    assert manifest["dataset_sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert manifest["pipeline"] == "okf-claims-hybrid-v1"
    assert manifest["scenarios"] == {"scope": 1}
    assert "api_key" not in manifest["query_config"]
