"""Read native Office/PDF evidence without executing embedded content."""

from __future__ import annotations

import math
import posixpath
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "d": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_R = "{" + _NS["r"] + "}"
_CONTINUED = re.compile(
    r"(?:\s*[(（]\s*(?:continued|续表?)\s*[)）]|\s+(?:continued|续表))\s*$", re.I
)


def markdown_table(rows: list[list[str]]) -> str:
    def line(row: list[str]) -> str:
        return "| " + " | ".join(" ".join(cell.split()).replace("|", r"\|") for cell in row) + " |"

    return "\n".join([line(rows[0]), line(["---"] * len(rows[0])), *map(line, rows[1:])])


def _texts(node: ET.Element) -> str:
    return " ".join(t.text for t in node.findall(".//a:t", _NS) if t.text)


def _relations(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    parent, name = posixpath.split(part)
    try:
        root = ET.fromstring(z.read(f"{parent}/_rels/{name}.rels"))
    except KeyError:
        return {}
    return {
        rel.attrib["Id"]: (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(parent, target))
        )
        for rel in root
        if rel.get("TargetMode") != "External" and (target := rel.get("Target"))
    }


def _chart(root: ET.Element) -> list[str]:
    def points(series: ET.Element, name: str) -> dict[str, str]:
        return {
            point.attrib["idx"]: value
            for point in series.findall(f"c:{name}/*/c:pt", _NS)
            + series.findall(f"c:{name}/*/*/c:pt", _NS)
            if "idx" in point.attrib and (value := point.findtext("c:v", namespaces=_NS))
        }

    sections: list[str] = []
    for group in root.findall(".//c:plotArea/*", _NS):
        kind = group.tag.rsplit("}", 1)[-1]
        for series in group.findall("c:ser", _NS):
            categories, values = points(series, "cat"), points(series, "val")
            if not categories or not categories.keys() & values.keys():
                continue
            name = (
                series.findtext("c:tx/c:v", namespaces=_NS)
                or series.findtext("c:tx/c:strRef/c:strCache/c:pt/c:v", namespaces=_NS)
                or "Value"
            )
            pie = kind in {"pieChart", "pie3DChart", "doughnutChart"}
            # Only calculate a share for a complete, nonnegative pie series.
            total = 0.0
            if pie and categories.keys() == values.keys():
                try:
                    numbers = [float(value) for value in values.values()]
                    if all(math.isfinite(value) and value >= 0 for value in numbers):
                        total = sum(numbers)
                except ValueError:
                    pass
            rows = [["Category", name, "Share"] if total else ["Category", name]]
            for index, category in categories.items():
                if index in values:
                    value = values[index]
                    rows.append(
                        [category, value]
                        + (
                            [
                                f"{float(value) / total:.6%}".rstrip("%").rstrip("0").rstrip(".")
                                + "%"
                            ]
                            if total
                            else []
                        )
                    )
            sections.extend([f"### Chart data: {name} ({kind})", "", markdown_table(rows), ""])
    return sections


def _smartart(root: ET.Element) -> list[str]:
    labels = {
        point.get("modelId"): label
        for point in root.findall(".//d:ptLst/d:pt", _NS)
        if point.get("type", "node") == "node" and (label := _texts(point))
    }
    edges = [
        f"- {labels[src]} → {labels[dst]}"
        for edge in root.findall(".//d:cxnLst/d:cxn", _NS)
        if edge.get("type", "parOf") == "parOf"
        and (src := edge.get("srcId")) in labels
        and (dst := edge.get("destId")) in labels
    ]
    return [*labels.values(), *edges]


def _position(shape: ET.Element) -> tuple[int, int]:
    off = shape.find("p:spPr/a:xfrm/a:off", _NS)
    return (int(off.get("y", "0")), int(off.get("x", "0"))) if off is not None else (0, 0)


def _shape_lines(shapes: list[ET.Element]) -> list[str]:
    """Keep labels on the same ungrouped shape row together (e.g. a Gantt bar)."""
    if any(shape.find("p:spPr/a:xfrm/a:off", _NS) is None for shape in shapes):
        return [_texts(shape) for shape in shapes]
    rows: list[list[str]] = []
    y0 = -100_000
    for shape in sorted(shapes, key=_position):
        y, _ = _position(shape)
        if not rows or y - y0 > 45_000:
            rows.append([])
            y0 = y
        rows[-1].append(_texts(shape))
    return [" | ".join(row) for row in rows]


def _transform(shape: ET.Element) -> tuple[int, int, int, int, ET.Element] | None:
    xfrm = shape.find("p:spPr/a:xfrm", _NS)
    if xfrm is None or xfrm.get("rot", "0") != "0":
        return None
    off, ext = xfrm.find("a:off", _NS), xfrm.find("a:ext", _NS)
    if off is None or ext is None:
        return None
    return (
        int(off.attrib["x"]),
        int(off.attrib["y"]),
        int(ext.attrib["cx"]),
        int(ext.attrib["cy"]),
        xfrm,
    )


def _branch_labels(shapes: list[ET.Element], connectors: list[ET.Element]) -> dict[ET.Element, str]:
    """Associate short decision captions with a unique nearby straight connector."""
    output = {}
    ambiguous = set()
    for shape in shapes:
        label = _texts(shape)
        if label.casefold() not in {"yes", "no", "true", "false", "是", "否", "通过", "拒绝"}:
            continue
        geometry = _transform(shape)
        if geometry is None:
            continue
        x, y, width, height, _ = geometry
        x, y = x + width / 2, y + height / 2
        candidates = []
        for connector in connectors:
            preset = connector.find("p:spPr/a:prstGeom", _NS)
            transform = _transform(connector)
            if transform is None or preset is None or preset.get("prst") != "straightConnector1":
                continue
            cx, cy, dx, dy, xfrm = transform
            if xfrm.get("flipH") in {"1", "true"}:
                cx, dx = cx + dx, -dx
            if xfrm.get("flipV") in {"1", "true"}:
                cy, dy = cy + dy, -dy
            length_squared = dx * dx + dy * dy
            if not length_squared:
                continue
            fraction = ((x - cx) * dx + (y - cy) * dy) / length_squared
            distance = math.hypot(x - cx - fraction * dx, y - cy - fraction * dy)
            if 0.1 <= fraction <= 0.9 and distance <= 32 * 9525:
                candidates.append(connector)
        if len(candidates) == 1:
            connector = candidates[0]
            if connector in output:
                ambiguous.add(connector)
            output[connector] = label
    return {connector: label for connector, label in output.items() if connector not in ambiguous}


def read_pptx(source: Path) -> tuple[str, list[int]]:
    """Extract slide-ordered shapes, anchored connections, tables and chart caches."""
    out = [f"# Document Source: {source.name}", "", "> Native PowerPoint evidence.", ""]
    found_text = False
    visual_followup: list[int] = []
    with zipfile.ZipFile(source) as z:
        presentation = "ppt/presentation.xml"
        relations = _relations(z, presentation)
        root = ET.fromstring(z.read(presentation))
        slides = root.findall("./p:sldIdLst/p:sldId", _NS)
        for number, slide in enumerate(slides, 1):
            part = relations[slide.attrib[_R + "id"]]
            root = ET.fromstring(z.read(part))
            shapes = [s for s in root.findall(".//p:sp", _NS) if _texts(s)]
            shape_ids = {
                shape_id.attrib["id"]: _texts(shape)
                for shape in shapes
                if (shape_id := shape.find("p:nvSpPr/p:cNvPr", _NS)) is not None
                and "id" in shape_id.attrib
            }
            out.extend([f"## Slide {number}", "", *_shape_lines(shapes), ""])
            before = len(out)
            edges = []
            unbound = False
            connectors = root.findall(".//p:cxnSp", _NS)
            tree = root.find("./p:cSld/p:spTree", _NS)
            captions = (
                _branch_labels(tree.findall("./p:sp", _NS), tree.findall("./p:cxnSp", _NS))
                if tree is not None
                else {}
            )
            for connector in connectors:
                props = connector.find("p:nvCxnSpPr/p:cNvCxnSpPr", _NS)
                if props is None:
                    unbound = True
                    continue
                start, end = props.find("a:stCxn", _NS), props.find("a:endCxn", _NS)
                src = shape_ids.get(start.get("id")) if start is not None else None
                dst = shape_ids.get(end.get("id")) if end is not None else None
                if not src or not dst:
                    unbound = True
                    continue
                line = connector.find("p:spPr/a:ln", _NS)
                head = line.find("a:headEnd", _NS) if line is not None else None
                tail = line.find("a:tailEnd", _NS) if line is not None else None
                starts = head is not None and head.get("type", "none") != "none"
                ends = tail is not None and tail.get("type", "none") != "none"
                arrow = {(True, True): "↔", (True, False): "←", (False, True): "→"}.get(
                    (starts, ends), "—"
                )
                if arrow == "←":
                    src, dst, arrow = dst, src, "→"
                label = _texts(connector) or captions.get(connector)
                edges.append(f"- {src} {arrow} {dst}" + (f" [{label}]" if label else ""))
            if edges:
                out.extend(["### Shape connections", "", *edges, ""])
            for table in root.findall(".//a:tbl", _NS):
                rows = [
                    [_texts(cell) for cell in row.findall("a:tc", _NS)]
                    for row in table.findall("a:tr", _NS)
                ]
                if rows and rows[0] and all(len(row) == len(rows[0]) for row in rows):
                    out.extend(["### Slide table", "", markdown_table(rows), ""])
            slide_rels = _relations(z, part)
            for chart in root.findall(".//c:chart", _NS):
                chart_part = slide_rels.get(chart.get(_R + "id", ""))
                chart_data = _chart(ET.fromstring(z.read(chart_part))) if chart_part else []
                out.extend(chart_data)
                unbound |= not bool(chart_data)
            for diagram in root.findall(".//d:relIds", _NS):
                data_part = slide_rels.get(diagram.get(_R + "dm", ""))
                data = _smartart(ET.fromstring(z.read(data_part))) if data_part else []
                if data:
                    out.extend(["### SmartArt structure", "", *data, ""])
                unbound |= not bool(data)
            if (
                unbound
                or root.find(".//p:pic", _NS) is not None
                or not (shapes or len(out) > before)
            ):
                visual_followup.append(number)
            found_text |= bool(shapes or len(out) > before)
    if not found_text:
        raise ValueError("PowerPoint contains no native text or structured evidence")
    return "\n".join(out).strip() + "\n", visual_followup


def merge_pptx_ocr(native: str, optical: str) -> str:
    """Retain native structure on each slide and augment it with its rendered evidence."""
    locator = re.compile(r"^##[ \t]+(?:Page|Slide)[ \t]+(\d+)\b[^\n]*$", re.M | re.I)

    def sections(content: str) -> tuple[str, dict[int, str]]:
        parts = locator.split(content)
        return parts[0], {
            int(number): body.strip() for number, body in zip(parts[1::2], parts[2::2])
        }

    native_header, native_slides = sections(native)
    optical_header, optical_slides = sections(optical)
    out = [native_header.strip(), optical_header.strip()]
    if not optical_slides:
        out.append(
            "> Optical fallback did not return page-scoped evidence; native slide content follows."
        )
    for number, body in native_slides.items():
        out.extend([f"## Slide {number}", body])
        if number in optical_slides:
            out.extend(["### Rendered slide evidence", optical_slides[number]])
    return "\n\n".join(part for part in out if part) + "\n"


def _monospace_code(lines: list[list[dict[str, Any]]]) -> list[str]:
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for spans in lines:
        if len(spans) != 1 or not spans[0]["flags"] & 8:
            if current:
                blocks.append(current)
                current = []
            continue
        span = spans[0]
        if current and not 0 < span["origin"][1] - current[-1]["origin"][1] <= 2.2 * span["size"]:
            blocks.append(current)
            current = []
        current.append(span)
    if current:
        blocks.append(current)
    rendered = []
    for block in blocks:
        if len(block) < 2 or not any(re.search(r"[=():{};]|\breturn\b", s["text"]) for s in block):
            continue
        x0 = min(span["origin"][0] for span in block)
        code = []
        for span in block:
            length = len(span["text"])
            advance = (span["bbox"][2] - span["bbox"][0]) / max(1, length)
            indent = round((span["origin"][0] - x0) / advance) if advance else 0
            code.append(" " * max(0, min(80, indent)) + span["text"].rstrip())
        # An indented fragment from a following page remains a fragment.
        fence = "`" * max(
            3, 1 + max((len(m) for s in code for m in re.findall(r"`+", s)), default=0)
        )
        rendered.append("\n".join([fence, *code, fence]))
    return rendered


def _bar_labels(lines: list[list[dict[str, Any]]], paths: list[dict[str, Any]]) -> list[list[str]]:
    """Recover only explicitly labeled vertical bars with an unambiguous shared baseline."""
    groups: dict[tuple, list] = defaultdict(list)
    for path in paths:
        if path["type"] != "f" or not all(item[0] == "re" for item in path["items"]):
            continue
        for _, rect, _ in path["items"]:
            if rect.width >= 12 and rect.height >= 2:
                groups[(round(rect.y1), round(rect.width), path["fill"])].append(rect)
    spans = [line[0] for line in lines if len(line) == 1]
    candidates = []
    for bars in groups.values():
        bars.sort(key=lambda r: r.x0)
        if (
            len(bars) < 3
            or len({round(r.height) for r in bars}) < 2
            or any(a.x1 >= b.x0 for a, b in zip(bars, bars[1:]))
        ):
            continue
        rows = []
        for rect in bars:
            near = [s for s in spans if rect.x0 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= rect.x1]
            values = [
                s["text"]
                for s in near
                if 0 <= rect.y0 - s["origin"][1] <= 24
                and re.fullmatch(r"[+-]?\d[\d,.]*%?", s["text"].strip())
            ]
            labels = [s["text"] for s in near if 0 < s["origin"][1] - rect.y1 <= 32]
            if len(values) != 1 or len(labels) != 1 or labels[0] in values:
                break
            rows.append([labels[0], values[0]])
        if len(rows) == len(bars) and len({row[0] for row in rows}) == len(rows):
            candidates.append(rows)
    # Multiple competing series need a legend/vision to disambiguate.
    return candidates[0] if len(candidates) == 1 else []


def _pdf_coverage_gap(
    page: Any, text: str, paths: list[dict[str, Any]], table_bounds: list[Any]
) -> str:
    """Flag content whose visible meaning is not represented in the native text."""
    import fitz

    area = max(1, page.rect.get_area())
    images = page.get_image_info()
    image_area = sum((fitz.Rect(image["bbox"]) & page.rect).get_area() for image in images)
    visible = re.sub(r"\s+", "", text)
    native_chars = sum(character.isalnum() for character in visible)
    if image_area >= 0.65 * area and native_chars < 24:
        return "scanned page lacks a usable native text layer"
    if image_area >= 0.08 * area:
        return "significant raster content needs visual interpretation"

    if not text and not images and not paths:
        return ""  # A genuinely blank page is still represented.
    if native_chars < 24:
        return "native text is sparse or absent"
    if len(re.findall(r"\ufffd|\(cid:\d+\)|[\ue000-\uf8ff]", visible)) >= max(
        2, len(visible) * 0.03
    ):
        return "native text contains unreadable glyphs"

    # Ignore table rules and full-page decoration. Spatially distributed paths
    # outside known tables can encode diagrams even with a dense text layer.
    graphic = fitz.Rect()
    segments = 0
    for path in paths:
        bounds = path["rect"] & page.rect
        if bounds.get_area() >= 0.85 * area or any(
            (table + (-2, -2, 2, 2)).contains(bounds) for table in table_bounds
        ):
            continue
        if max(bounds.width, bounds.height) < 12:
            continue
        graphic |= bounds
        segments += len(path["items"])
    if segments >= 3 and graphic.get_area() >= 0.025 * area:
        return "vector layout may contain relationships or chart values"
    return ""


def pdf_sections(
    source: Path, *, coverage_gaps: dict[int, str] | None = None
) -> list[tuple[int, str]]:
    """Native PDF text plus page-local layout evidence; never invent visual values."""
    import fitz

    output = []
    previous: tuple[str, tuple[float, ...], list[str], int] | None = None
    with fitz.open(source) as doc:
        for page in doc:
            text_page = page.get_textpage()
            text = page.get_text("text", sort=True, textpage=text_page).strip()
            lines = [
                line["spans"]
                for block in page.get_text("dict", textpage=text_page)["blocks"]
                for line in block.get("lines", [])
                if line.get("spans")
            ]
            paths = page.get_drawings()
            supplements = []
            table_bounds = []
            if paths and hasattr(page, "find_tables"):
                # Reuse the drawing scan; require an actual ruled grid and at least two rows.
                try:
                    tables = page.find_tables(paths=paths, strategy="lines_strict").tables
                except TypeError:
                    tables = page.find_tables(strategy="lines_strict").tables
                next_previous = None
                for index, table in enumerate(tables):
                    rows = [[cell or "" for cell in row] for row in table.extract()]
                    if (
                        len(rows) < 2
                        or len(rows[0]) < 2
                        or any(sum(bool(cell.strip()) for cell in row) < 2 for row in rows)
                    ):
                        continue
                    table_bounds.append(fitz.Rect(table.bbox))
                    x0, y0, x1, _ = table.bbox
                    captions = [
                        s
                        for line in lines
                        for s in line
                        if x0 - 6 <= s["bbox"][0] < x1
                        and 0 <= y0 - s["bbox"][3] <= 72
                        and s["text"].strip()
                    ]
                    caption = (
                        min(captions, key=lambda s: y0 - s["bbox"][3])["text"].strip()
                        if captions
                        else ""
                    )
                    title = _CONTINUED.sub("", caption).casefold()
                    boundaries = (
                        *(round(cell[0], 1) for cell in table.rows[0].cells if cell),
                        round(x1, 1),
                    )
                    can_continue = (
                        index == 0
                        and bool(title)
                        and bool(_CONTINUED.search(caption))
                        and previous is not None
                        and title == previous[0]
                        and len(boundaries) == len(previous[1])
                        and len(rows[0]) == len(previous[2])
                        and all(abs(a - b) <= 2 for a, b in zip(boundaries, previous[1]))
                    )
                    if can_continue and previous:
                        header, header_page = previous[2:]
                        if rows[0] != header:
                            rows.insert(0, header)
                        caption += f" (column headings from page {header_page})"
                    else:
                        header, header_page = rows[0], page.number + 1
                        if _CONTINUED.search(caption):
                            # Unknown continuation: retain every row, without assigning its first
                            # data row the semantics of a header.
                            rows.insert(0, [f"Column {i+1}" for i in range(len(header))])
                    if index == 0 and title and (can_continue or not _CONTINUED.search(caption)):
                        next_previous = (title, boundaries, header, header_page)
                    supplements.extend(
                        [f"### PDF table: {caption or index + 1}", markdown_table(rows)]
                    )
                previous = next_previous
            else:
                previous = None
            code = _monospace_code(lines)
            if code:
                supplements.extend(["### Code on this page", *code])
            if bars := _bar_labels(lines, paths):
                supplements.extend(
                    ["### Labeled bars", markdown_table([["Category", "Value"], *bars])]
                )
            body = "\n\n".join([text, *supplements]).strip()
            number = page.number + 1
            if coverage_gaps is not None:
                gap = _pdf_coverage_gap(page, text, paths, table_bounds)
                if gap:
                    coverage_gaps[number] = gap
            output.append((number, body))
    return output
