#!/usr/bin/env python3
"""Generate benchmark comparison chart: llm-wiki vs Industry Baselines.

Uses the latest RAGAS results from evals/ragas_eval/results_final_v3.json
to produce a grouped bar chart saved to docs/benchmark_chart.png.
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── Load latest results ──
results_path = Path(__file__).parent.parent / "evals" / "ragas_eval" / "results_final_v3.json"
with open(results_path) as f:
    data = json.load(f)

overall = data["aggregate"]["overall"]
by_domain = data["aggregate"]["by_domain"]
baselines = data["baselines"]

# ── Data ──
metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]
labels = ["Faithfulness", "Answer\nRelevance", "Context\nPrecision", "Context\nRecall", "Answer\nCorrectness"]

systems = {
    "Naive RAG": baselines["Naive RAG (chunk + embed + LLM)"],
    "RAG + Reranker": baselines["RAG + Reranker"],
    "RAGFlow (est.)": baselines["RAGFlow (estimated)"],
    "GraphRAG": baselines["GraphRAG (Microsoft)"],
    "llm-wiki": {m: overall[m] for m in metrics},
}

colors = ["#B0BEC5", "#90A4AE", "#78909C", "#546E7A", "#1A73E8"]
n_systems = len(systems)
n_metrics = len(metrics)
x = np.arange(n_metrics)
width = 0.15

fig, ax = plt.subplots(figsize=(14, 7))

for i, (name, scores) in enumerate(systems.items()):
    vals = [scores.get(m, 0) for m in metrics]
    bars = ax.bar(x + (i - n_systems/2 + 0.5) * width, vals, width,
                  label=name, color=colors[i], edgecolor="white", linewidth=0.5,
                  zorder=3 if name == "llm-wiki" else 2)

# ── Style ──
ax.set_ylabel("Score (0-1)", fontsize=12, fontweight="bold")
ax.set_title("RAGAS Black-Box Evaluation: llm-wiki vs Industry Baselines",
             fontsize=15, fontweight="bold", pad=20)
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=10)
ax.set_ylim(0, 1.05)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.2f'))
ax.grid(axis="y", alpha=0.3, zorder=0)
ax.legend(loc="upper right", framealpha=0.9, fontsize=9)

# Add value labels on llm-wiki bars
for i, (name, scores) in enumerate(systems.items()):
    vals = [scores.get(m, 0) for m in metrics]
    for j, v in enumerate(vals):
        if name == "llm-wiki":
            ax.text(x[j] + (i - n_systems/2 + 0.5) * width, v + 0.02,
                    f"{v:.2f}", ha="center", va="bottom", fontsize=8,
                    fontweight="bold", color="#1A73E8")

# ── Annotation ──
ax.annotate(
    "Full pipeline: compile_v2 → embed → search → synthesize\n"
    f"19 test cases · 3 domains (tech/business/chinese) · {data['wiki_setup_time_sec']:.0f}s setup",
    xy=(0.5, -0.16), xycoords="axes fraction",
    ha="center", fontsize=9, color="#666",
)

plt.tight_layout()
out = Path(__file__).parent.parent / "docs" / "benchmark_chart.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(str(out), dpi=150, bbox_inches="tight", facecolor="white")
print(f"✓ Chart saved → {out}")
