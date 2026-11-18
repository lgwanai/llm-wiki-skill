"""Calculate checkable arithmetic over one explicitly listed chart series."""

from __future__ import annotations

import re
from decimal import Decimal

try:
    from .table_extract import extract_tables
except ImportError:
    from table_extract import extract_tables


def chart_calculation_context(query: str, content: str) -> str:
    if not re.search(r"share|proportion|percent|total|sum|combined|占|总量|合计|比例", query, re.I):
        return ""
    calculations: list[str] = []
    for table in extract_tables(content):
        if len(table.headers) != 2 or not 2 <= len(table.rows) <= 30:
            continue
        headings = re.findall(r"^###\s+(.+)", content[: table.start], re.M)
        if not headings or not re.search(r"chart|labeled bars|by month", headings[-1], re.I):
            continue
        if table.headers[0].casefold() not in {"category", "month", "period"}:
            continue
        if len({row[0] for row in table.rows}) != len(table.rows) or not all(
            re.fullmatch(r"\d{1,12}(?:\.\d{1,6})?", row[1]) for row in table.rows
        ):
            continue
        values = [Decimal(row[1]) for row in table.rows]
        total = sum(values)
        if not total:
            continue
        parts = " + ".join(str(value) for value in values)
        shares = ", ".join(
            f"{row[0]}: {value / total * 100:.6f}".rstrip("0").rstrip(".") + "%"
            for row, value in zip(table.rows, values, strict=True)
        )
        calculations.append(
            f"- {headings[-1]} — sum of displayed {table.headers[1]} values: "
            f"{parts} = {total}. Each value divided by this sum: {shares}."
        )
    if not calculations:
        return ""
    return (
        "\n\n### Checked chart arithmetic (use only if the requested series and operation match)\n"
        + "\n".join(calculations[:4])
    )


_COUNT_ALL = re.compile(
    r"^(?:how many|what is the total number of)\s+(?P<metric>[a-z ]{3,70}?)\s+"
    r"(?:across|over|in)\s+all\s+(?:the\s+)?"
    r"(?P<count>\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)?\s*"
    r"(?:shown|displayed|visible)\s+(?P<unit>months|weeks|quarters|periods|categories)\s*\??$",
    re.I,
)
_COUNTS = {
    word: n
    for n, word in enumerate(
        ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), 2
    )
}


def exact_displayed_count(query: str, pages: list[dict]) -> str:
    """Answer explicit counts across all displayed categories when one chart qualifies."""
    match = _COUNT_ALL.fullmatch(query.strip())
    if not match:
        return ""
    metric = match["metric"].casefold()
    if set(metric.split()) & {"without", "excluding", "except", "only", "or", "not", "than"}:
        return ""
    metric_words = set(re.findall(r"[a-z]{3,}", metric)) - {"the", "were", "are", "was"}
    if not metric_words or metric_words & {
        "percent",
        "percentage",
        "rate",
        "ratio",
        "share",
        "average",
    }:
        return ""
    count = (match["count"] or "").casefold()
    expected = int(count) if count.isdigit() else _COUNTS.get(count)
    matching = []
    for page in pages:
        if page.get("type") != "source_evidence" or not page.get("id"):
            continue
        text = str(page.get("evidence_excerpt") or page.get("text") or "")
        chart_sections = re.split(r"^### Chart data: ", text, flags=re.M)
        # A chart may not borrow qualifier words from another series on the same slide.
        if len(chart_sections) != 2:
            continue
        caption, section = chart_sections
        chart_label = section.splitlines()[0] if section.splitlines() else ""
        if "(barChart)" not in chart_label:
            continue
        tables = extract_tables(section)
        if len(tables) != 1:
            continue
        table = tables[0]
        if len(table.headers) != 2 or table.headers[0] != "Category":
            continue
        if not 2 <= len(table.rows) <= 30 or (expected is not None and expected != len(table.rows)):
            continue
        if not (metric_words & set(re.findall(r"[a-z]{3,}", table.headers[1].casefold()))):
            continue
        chart_words = set(re.findall(r"[a-z]{3,}", (caption + chart_label).casefold()))
        unit = match["unit"].casefold()
        singular = "category" if unit == "categories" else unit[:-1]
        if not metric_words <= chart_words or not chart_words.intersection({unit, singular}):
            continue
        if len({row[0] for row in table.rows}) != len(table.rows) or not all(
            re.fullmatch(r"\d{1,12}", row[1]) for row in table.rows
        ):
            continue
        matching.append((page, table))
    if len(matching) != 1:
        return ""
    page, table = matching[0]
    values = [int(row[1]) for row in table.rows]
    terms = " + ".join(map(str, values))
    labels = ", ".join(f"{row[0]}: {row[1]}" for row in table.rows)
    return (
        f"**{sum(values):,}** across the displayed {match['unit'].casefold()}. "
        f"{labels}; {terms} = {sum(values):,}. "
        f"[{page.get('locator') or 'Source chart'}](/{page['id']}.md)"
    )
