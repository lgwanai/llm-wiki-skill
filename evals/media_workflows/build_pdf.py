"""Build the deterministic Harbor capacity review fixture."""

from math import cos, radians, sin
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures" / "harbor-capacity.pdf"
C = canvas.Canvas(str(OUT), pagesize=(612, 792))
C.setTitle("Harbor Capacity Review")
INK = colors.HexColor("#14253C")
BLUE = colors.HexColor("#1768A8")


def text(x: float, y: float, value: str, size: int = 11, font: str = "Helvetica") -> None:
    C.setFillColor(INK)
    C.setFont(font, size)
    C.drawString(x, y, value)


def page(number: int, title: str) -> None:
    text(54, 749, "HARBOR   /   OPERATIONS REVIEW", 10, "Helvetica-Bold")
    text(54, 715, title, 23, "Helvetica-Bold")
    text(54, 29, f"HARBOR OPERATIONS   /   {number:02d}", 8)


def table(
    x: float, y: float, widths: list[int], rows: list[list[str]], header: bool = True
) -> None:
    for index, row in enumerate(rows):
        bottom = y - (index + 1) * 23
        left = x
        for width, value in zip(widths, row, strict=True):
            C.setFillColor(colors.HexColor("#DDEFFC") if index == 0 and header else colors.white)
            C.setStrokeColor(colors.HexColor("#7193AC"))
            C.rect(left, bottom, width, 23, stroke=1, fill=1)
            text(
                left + 6,
                bottom + 7,
                value,
                10,
                "Helvetica-Bold" if index == 0 and header else "Helvetica",
            )
            left += width


def code(y: float, rows: list[str]) -> None:
    for i, row in enumerate(rows):
        text(60, y - i * 16, row, 12, "Courier")


page(1, "Worker allocation by region")
table(
    54,
    674,
    [155, 120, 110],
    [["Region", "Workers", "Cost (USD)"], ["Cedar", "12", "420"], ["Juniper", "18", "630"]],
)
text(54, 280, "Retry policy implementation", 16, "Helvetica-Bold")
code(
    132,
    [
        "def harbor_retry(status, attempt):",
        "    if status == 429:",
        "        return min(64, 2 ** attempt)",
    ],
)
C.showPage()
page(2, "Worker allocation by region (continued)")
table(54, 674, [155, 120, 110], [["Maple", "24", "840"], ["Ash", "30", "1050"]], False)
text(54, 280, "Retry policy implementation (continued)", 16, "Helvetica-Bold")
code(252, ["    if status == 503 and attempt < 3:", "        return 5", "    return None"])
C.showPage()
page(3, "Worker allocation by region (continued)")
table(54, 674, [155, 120, 110], [["Willow", "36", "1260"], ["Birch", "42", "1470"]], False)
C.showPage()
page(4, "Operational thresholds")
for x, y, title, rows in [
    (54, 630, "Latency limits", [["Queue", "Limit ms"], ["Ingest", "140"], ["Export", "300"]]),
    (327, 630, "Alert routing", [["Queue", "Owner"], ["Ingest", "Marin"], ["Export", "Parker"]]),
    (54, 445, "Retry budgets", [["Queue", "Attempts"], ["Ingest", "4"], ["Export", "2"]]),
    (327, 445, "Retention windows", [["Queue", "Days"], ["Ingest", "21"], ["Export", "7"]]),
]:
    text(x, y + 12, title, 13, "Helvetica-Bold")
    table(x, y, [112, 105], rows)
C.showPage()
page(5, "Throughput and cost allocation")
text(54, 670, "Resolved incidents by month", 14, "Helvetica-Bold")
C.setStrokeColor(INK)
C.line(86, 397, 530, 397)
for i, (name, value) in enumerate(zip(["April", "May", "June"], [30, 45, 75], strict=True)):
    x = 122 + i * 143
    C.setFillColor(BLUE)
    C.rect(x, 397, 66, value * 2.6, fill=1, stroke=0)
    text(x + 22, 408 + value * 2.6, str(value), 12)
    text(x + 14, 377, name, 11)
text(54, 320, "Cost share by team", 14, "Helvetica-Bold")
angle = 0
for name, pct, color in [
    ("Core", 56, BLUE),
    ("Edge", 28, colors.HexColor("#16A087")),
    ("QA", 16, colors.HexColor("#D98423")),
]:
    span = pct * 3.6
    C.setFillColor(color)
    C.wedge(150, 87, 330, 267, angle, span, stroke=0, fill=1)
    mid = radians(angle + span / 2)
    text(225 + cos(mid) * 123, 174 + sin(mid) * 111, f"{name} {pct}%", 11, "Helvetica-Bold")
    angle += span
C.save()
