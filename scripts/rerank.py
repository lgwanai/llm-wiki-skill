"""Optional retrieval rerankers with graceful fallback."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


def _candidate_text(result: dict, max_chars: int = 6000) -> str:
    """Use matched evidence before unrelated page prefixes."""
    claims = result.get("claim_hits") or (
        [result["matched_claim"]] if result.get("matched_claim") else []
    )
    claim_text = "\n".join(
        " | ".join(
            str(claim.get(field, ""))
            for field in ("subject", "predicate", "value", "conditions", "exceptions")
        )
        for claim in claims
        if isinstance(claim, dict)
    )
    try:
        page_text = Path(result.get("path", "")).read_text(encoding="utf-8")
    except OSError:
        page_text = str(result.get("text", ""))
    matched_heading = str(result.get("matched_section", "")).strip()
    section_text = ""
    if matched_heading and page_text:
        match = re.search(
            rf"(?ms)^#{{1,6}}\s+{re.escape(matched_heading)}\s*$.*?(?=^#{{1,6}}\s+|\Z)",
            page_text,
        )
        if match:
            section_text = match.group(0)
    combined = "\n\n".join(value for value in (claim_text, section_text, page_text) if value)
    return combined[:max_chars]


@lru_cache(maxsize=2)
def _flag_model(model_name: str):
    from FlagEmbedding import FlagReranker

    return FlagReranker(model_name, use_fp16=True)


def rerank(query: str, results: list[dict], config: dict, top_n: int) -> list[dict]:
    """Rerank top candidates; return original ranking when backend is unavailable."""
    if not config.get("enabled", False) or not results:
        return results[:top_n]
    backend = str(config.get("backend", "flagembedding"))
    candidates = results[: int(config.get("candidate_count", 20) or 20)]
    if backend != "flagembedding":
        return results[:top_n]
    try:
        model = _flag_model(str(config.get("model", "BAAI/bge-reranker-v2-m3")))
        texts = []
        for result in candidates:
            texts.append(_candidate_text(result))
        scores = model.compute_score([[query, text] for text in texts], normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
        ranked = []
        for result, score in zip(candidates, scores):
            item = dict(result)
            item["reranker_score"] = float(score)
            authority = min(max(float(item.get("source_authority", 0.6)), 0.0), 1.0)
            item["rerank_score"] = (
                0.62 * float(score)
                + 0.32 * float(item.get("rerank_score", item.get("score", 0)))
                + 0.06 * authority
            )
            ranked.append(item)
        ranked.sort(key=lambda item: -item["rerank_score"])
        ranked.extend(results[len(candidates) :])
        return ranked[:top_n]
    except (ImportError, RuntimeError, TypeError, ValueError, OSError):
        return results[:top_n]
