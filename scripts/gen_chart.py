#!/usr/bin/env python3
"""Generate the PageIndex benchmark comparison used by project documentation."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

PAGEINDEX_REPRESENTATIVE = [
    ("PageIndex\nLuna none", 85.5),
    ("PageIndex\nLuna medium", 91.9),
    ("PageIndex\nLuna high", 96.8),
    ("PageIndex\nTerra medium", 98.4),
    ("PageIndex\nTerra high", 100.0),
    ("PageIndex\nSol medium", 100.0),
]

LLM_WIKI_PROGRESS = [
    ("Compiled wiki\nbaseline", 61.3),
    ("Lossless source\nevidence", 74.2),
    ("Retrieval and\ncontext tuning", 88.7),
    ("Deterministic\nevidence", 100.0),
]


def _label_bars(axis: plt.Axes, bars: object) -> None:
    for bar in bars:
        value = float(bar.get_height())
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )


def generate() -> list[Path]:
    """Render representative PageIndex accuracy and llm-wiki progress."""
    fig, (comparison, progress) = plt.subplots(1, 2, figsize=(15, 7.2))

    comparison_names = [name for name, _ in PAGEINDEX_REPRESENTATIVE]
    comparison_scores = [score for _, score in PAGEINDEX_REPRESENTATIVE]
    comparison_bars = comparison.bar(
        range(len(comparison_names)),
        comparison_scores,
        color=["#94A3B8", "#78909C", "#607D8B", "#4F83A8", "#2563A6", "#174A7E"],
    )
    comparison.set_title("PageIndex published results", fontweight="bold")
    comparison.set_ylabel("Semantic-equivalence accuracy (%)")
    comparison.set_xticks(range(len(comparison_names)))
    comparison.set_xticklabels(comparison_names, fontsize=8)
    comparison.set_ylim(55, 106)
    comparison.grid(axis="y", alpha=0.22)
    _label_bars(comparison, comparison_bars)

    progress_names = [name for name, _ in LLM_WIKI_PROGRESS]
    progress_scores = [score for _, score in LLM_WIKI_PROGRESS]
    progress_bars = progress.bar(
        range(len(progress_names)),
        progress_scores,
        color=["#D97706", "#F59E0B", "#38BDF8", "#0369A1"],
    )
    progress.plot(
        range(len(progress_scores)),
        progress_scores,
        color="#0C4A6E",
        marker="o",
        linewidth=2,
    )
    progress.set_title("llm-wiki improvement on the same 62 questions", fontweight="bold")
    progress.set_xticks(range(len(progress_names)))
    progress.set_xticklabels(progress_names, fontsize=8)
    progress.set_ylim(55, 106)
    progress.grid(axis="y", alpha=0.22)
    _label_bars(progress, progress_bars)

    fig.suptitle(
        "PageIndex OSS Benchmark: 34 PDFs · 1,945 pages · 62 questions",
        fontsize=16,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.015,
        "Same corpus and semantic-equivalence rubric. llm-wiki uses a configured "
        "judge, so its score is directional rather than leaderboard-comparable.",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))

    DOCS.mkdir(parents=True, exist_ok=True)
    outputs = [DOCS / "pageindex_comparison.png", DOCS / "benchmark_chart.png"]
    for output in outputs:
        fig.savefig(output, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return outputs


if __name__ == "__main__":
    for path in generate():
        print(f"Chart saved: {path}")
