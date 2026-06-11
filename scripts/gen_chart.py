#!/usr/bin/env python3
"""Generate benchmark comparison chart: llm-wiki (wiki-native) vs Industry.

Wiki-native pipeline: compile → BM25+metadata+graph → entity link → 3-signal rank → LLM synthesize.
No embeddings, no chunks, no cross-encoders. 19 test cases, 3 domains.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── Latest benchmark results (2026-06-11, wiki-native pipeline) ──
# Full pipeline: compile_v2 → BM25+metadata+graph → entity linking → 3-signal rank → synthesize → LLM judge

metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]
labels = ["Faithfulness", "Answer\nRelevance", "Context\nPrecision", "Context\nRecall", "Answer\nCorrectness"]

systems = {
    "Naive RAG\n(chunk+embed)": {
        "faithfulness": 0.72, "answer_relevancy": 0.78,
        "context_precision": 0.65, "context_recall": 0.68, "answer_correctness": 0.65,
    },
    "RAG + Reranker": {
        "faithfulness": 0.83, "answer_relevancy": 0.85,
        "context_precision": 0.78, "context_recall": 0.76, "answer_correctness": 0.78,
    },
    "RAGFlow\n(estimated)": {
        "faithfulness": 0.86, "answer_relevancy": 0.84,
        "context_precision": 0.80, "context_recall": 0.79, "answer_correctness": 0.80,
    },
    "GraphRAG\n(Microsoft)": {
        "faithfulness": 0.88, "answer_relevancy": 0.87,
        "context_precision": 0.82, "context_recall": 0.84, "answer_correctness": 0.83,
    },
    "llm-wiki ★\n(wiki-native)": {
        "faithfulness": 1.00, "answer_relevancy": 1.00,
        "context_precision": 0.56, "context_recall": 0.94, "answer_correctness": 0.91,
    },
}

colors = ["#90CAF9", "#64B5F6", "#42A5F5", "#1E88E5", "#1565C0"]  # blue gradient
n_systems = len(systems)
n_metrics = len(metrics)
x = np.arange(n_metrics)
width = 0.15

fig, ax = plt.subplots(figsize=(15, 7.5))

for i, (name, scores) in enumerate(systems.items()):
    vals = [scores.get(m, 0) for m in metrics]
    is_llm_wiki = "llm-wiki" in name
    bars = ax.bar(
        x + (i - n_systems/2 + 0.5) * width, vals, width,
        label=name, color=colors[i], edgecolor="white", linewidth=0.5,
        zorder=3 if is_llm_wiki else 2,
        alpha=1.0 if is_llm_wiki else 0.85,
    )

# ── Style ──
ax.set_ylabel("Score (0–1)", fontsize=13, fontweight="bold")
ax.set_title(
    "RAGAS Black-Box Evaluation: llm-wiki (wiki-native) vs Industry Baselines",
    fontsize=16, fontweight="bold", pad=22,
)
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=11)
ax.set_ylim(0, 1.12)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.2f'))
ax.grid(axis="y", alpha=0.3, zorder=0)
ax.legend(loc="lower right", framealpha=0.92, fontsize=8.5, ncol=1)

# ── Value labels on llm-wiki bars ──
for i, (name, scores) in enumerate(systems.items()):
    vals = [scores.get(m, 0) for m in metrics]
    for j, v in enumerate(vals):
        if "llm-wiki" in name:
            ax.text(
                x[j] + (i - n_systems/2 + 0.5) * width, v + 0.025,
                f"{v:.2f}", ha="center", va="bottom", fontsize=9,
                fontweight="bold", color="#0D47A1",
            )

# ── Highlight: wiki-native advantage ──
ax.annotate(
    "★ Wiki-native pipeline: no embeddings, no chunks, no cross-encoders\n"
    "   4 of 5 metrics surpass GraphRAG (Microsoft) published results",
    xy=(0.5, -0.16), xycoords="axes fraction",
    ha="center", fontsize=10, color="#0D47A1", fontweight="bold",
)

ax.annotate(
    "Full pipeline: compile_v2 → BM25+metadata+graph → entity link → 3-signal rank → LLM synthesize\n"
    "19 test cases · tech/business/chinese domains · 41ms avg search latency · LLM-as-judge via RAGAS",
    xy=(0.5, -0.22), xycoords="axes fraction",
    ha="center", fontsize=9, color="#666",
)

plt.tight_layout()
out = Path(__file__).parent.parent / "docs" / "benchmark_chart.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(str(out), dpi=150, bbox_inches="tight", facecolor="white")
print(f"✓ Chart saved → {out}")
