"""Optional retrieval rerankers with graceful fallback."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


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
            try:
                text = Path(result.get("path", "")).read_text(encoding="utf-8")[:6000]
            except OSError:
                text = str(result.get("text", ""))
            texts.append(text)
        scores = model.compute_score([[query, text] for text in texts], normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
        ranked = []
        for result, score in zip(candidates, scores):
            item = dict(result)
            item["reranker_score"] = float(score)
            item["rerank_score"] = 0.65 * float(score) + 0.35 * float(
                item.get("rerank_score", item.get("score", 0))
            )
            ranked.append(item)
        ranked.sort(key=lambda item: -item["rerank_score"])
        ranked.extend(results[len(candidates) :])
        return ranked[:top_n]
    except (ImportError, RuntimeError, TypeError, ValueError, OSError):
        return results[:top_n]
