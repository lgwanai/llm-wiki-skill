#!/usr/bin/env python3
"""Generate the GitHub-facing PageIndex benchmark and capability comparison."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

BENCHMARK_RESULTS = [
    ("PageIndex\nLuna high", 96.8, "60/62"),
    ("PageIndex\nTerra medium", 98.4, "61/62"),
    ("PageIndex\nTerra high", 100.0, "62/62"),
    ("PageIndex\nSol medium", 100.0, "62/62"),
    ("llm-wiki\ncurrent*", 100.0, "62/62"),
]

CAPABILITIES = [
    ("Local text-PDF QA", "YES", "YES"),
    ("Scanned / image-rich input", "CLOUD", "YES"),
    ("Word · PPT · EPUB · Web", "—", "YES"),
    ("Temporal policy validity", "—", "YES"),
    ("Typed knowledge graph", "—", "YES"),
    ("Structured DuckDB ledger", "—", "YES"),
    ("Lifecycle repair + rollback", "—", "YES"),
    ("Local persistent storage", "YES", "YES"),
]


def _label_bars(axis: plt.Axes, bars: object) -> None:
    for bar, (_, _, fraction) in zip(bars, BENCHMARK_RESULTS, strict=True):
        value = float(bar.get_height())
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.25,
            f"{fraction}  ·  {value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=8.5,
            fontweight="bold",
        )


def _draw_capability_matrix(axis: plt.Axes) -> None:
    axis.set_xlim(0, 1)
    axis.set_ylim(0, len(CAPABILITIES) + 1.6)
    axis.axis("off")
    axis.set_title(
        "Open-source / local product scope",
        fontweight="bold",
        pad=14,
    )

    axis.text(0.03, len(CAPABILITIES) + 0.8, "CAPABILITY", fontsize=9, fontweight="bold")
    axis.text(
        0.69,
        len(CAPABILITIES) + 0.8,
        "PAGEINDEX",
        fontsize=9,
        fontweight="bold",
        ha="center",
    )
    axis.text(
        0.91,
        len(CAPABILITIES) + 0.8,
        "LLM-WIKI",
        fontsize=9,
        fontweight="bold",
        ha="center",
    )

    for index, (capability, pageindex, llm_wiki) in enumerate(CAPABILITIES):
        y = len(CAPABILITIES) - index
        if index % 2 == 0:
            axis.add_patch(
                FancyBboxPatch(
                    (0.01, y - 0.38),
                    0.98,
                    0.76,
                    boxstyle="round,pad=0.01,rounding_size=0.02",
                    facecolor="#F1F5F9",
                    edgecolor="none",
                )
            )
        axis.text(0.03, y, capability, va="center", fontsize=9)
        axis.text(
            0.69,
            y,
            pageindex,
            va="center",
            ha="center",
            fontsize=8.5,
            color="#475569" if pageindex != "YES" else "#0F766E",
            fontweight="bold",
        )
        axis.text(
            0.91,
            y,
            llm_wiki,
            va="center",
            ha="center",
            fontsize=8.5,
            color="#0369A1",
            fontweight="bold",
        )

    axis.text(
        0.03,
        0.15,
        "— = not documented in PageIndex local OSS · CLOUD = available in PageIndex Cloud",
        fontsize=7.5,
        color="#64748B",
    )


def generate() -> list[Path]:
    """Render current benchmark results and the local product-scope comparison."""
    fig, (results, capabilities) = plt.subplots(
        1,
        2,
        figsize=(15.5, 7.2),
        gridspec_kw={"width_ratios": [1.12, 1]},
    )

    names = [name for name, _, _ in BENCHMARK_RESULTS]
    scores = [score for _, score, _ in BENCHMARK_RESULTS]
    bars = results.bar(
        range(len(names)),
        scores,
        color=["#94A3B8", "#64748B", "#334155", "#1E293B", "#0369A1"],
    )
    results.set_title("Accuracy on the same 62 questions", fontweight="bold", pad=14)
    results.set_ylabel("Semantic-equivalence accuracy (%)")
    results.set_xticks(range(len(names)))
    results.set_xticklabels(names, fontsize=8.5)
    results.set_ylim(92, 102.2)
    results.set_yticks([94, 96, 98, 100])
    results.grid(axis="y", alpha=0.22)
    results.spines[["top", "right"]].set_visible(False)
    _label_bars(results, bars)

    _draw_capability_matrix(capabilities)

    fig.suptitle(
        "llm-wiki: PageIndex-level document QA, built into a living knowledge system",
        fontsize=16,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.018,
        "34 PDFs · 1,945 pages · 62 questions · 0 runtime errors · "
        "*llm-wiki score uses a different answer/judge model and is directional",
        ha="center",
        fontsize=8.5,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.055, 1, 0.92), w_pad=3.5)

    DOCS.mkdir(parents=True, exist_ok=True)
    outputs = [DOCS / "pageindex_comparison.png", DOCS / "benchmark_chart.png"]
    for output in outputs:
        fig.savefig(output, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return outputs


if __name__ == "__main__":
    for path in generate():
        print(f"Chart saved: {path}")
