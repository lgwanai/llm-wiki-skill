#!/usr/bin/env python3
"""compile_v2.py — Simplified wiki compilation.
...
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from _llm_utils import call_llm, get_chunk_threshold
from config import (
    get_config,
    get_image_analysis_config,
    get_ocr_config,
    get_wiki_dir,
)

def _log_exc(msg: str = ""):
    """Log exception traceback to stderr for debugging."""
    import traceback as _tb
    if msg:
        print(f"  [WARN] {msg}: {_tb.format_exc()}", file=sys.stderr)
    else:
        print(f"  [WARN] {_tb.format_exc()}", file=sys.stderr)



SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r'(?:sk|pk|rk)-(?:[a-zA-Z0-9]{20,})', '[REDACTED: API key]'),
    (r'(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}', '[REDACTED: GitHub token]'),
    (r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     '[REDACTED: Private key]'),
    (r'password\s*[=:]\s*\S+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]

KEYWORD_RELATION_MAP = [
    # English patterns
    (r'(?i)\buses?\b\s*\[\[', 'uses'),
    (r'(?i)\bdepends?\s+on\b.*?\[\[', 'depends_on'),
    (r'(?i)\bextends?\b\s*\[\[', 'extends'),
    (r'(?i)\bimproves?\s+(?:upon|over)?\s*\[\[', 'improves_upon'),
    (r'(?i)\bcontradicts?\b\s*\[\[', 'contradicts'),
    (r'(?i)\bsupersedes?\b\s*\[\[', 'supersedes'),
    (r'(?i)\bcaused?\s+by\b.*?\[\[', 'caused_by'),
    (r'(?i)\bfixed?\s+by\b.*?\[\[', 'fixed_by'),
    (r'(?i)\breplaces?\b\s*\[\[', 'replaces'),
    (r'(?i)\brelated\s+to\b.*?\[\[', 'relates_to'),
    (r'(?i)\bpart\s+of\b.*?\[\[', 'part_of'),
    (r'(?i)\bimplemented\s+(?:by|via)\b.*?\[\[', 'implemented_by'),
    # Chinese patterns
    (r'(?:使用|采用|利用|调用|借助|依据|通过)\s*\[\[', 'uses'),
    (r'(?:依赖|取决于|依赖于)\s*\[\[', 'depends_on'),
    (r'(?:扩展|继承|基于\s*)\s*\[\[', 'extends'),
    (r'(?:改进|优化|提升|增强)\s*\[\[', 'improves_upon'),
    (r'(?:矛盾|冲突|不一致|违背)\s*\[\[', 'contradicts'),
    (r'(?:取代|替代|替换\s*掉|淘汰)\s*\[\[', 'supersedes'),
    (r'(?:导致|引起|造成|触发|引发)\s*\[\[', 'caused_by'),
    (r'(?:修复|解决|修正|纠正)\s*\[\[', 'fixed_by'),
    (r'(?:替换|更换|换成|切换)\s*\[\[', 'replaces'),
    (r'(?:关联|相关|有关|涉及|对接|协作|配合|协调)\s*\[\[', 'relates_to'),
    (r'(?:属于|组成部分|包含于|隶属于)\s*\[\[', 'part_of'),
    (r'(?:实现|实施|执行|落实|负责|承担|主持)\s*\[\[', 'implemented_by'),
]

TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".svg",  # SVG is XML text, not pixel data
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb",
    ".sh", ".bash", ".zsh", ".sql", ".toml", ".ini", ".cfg",
}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".tiff", ".tif", ".avif", ".heic", ".heif",
}
SKIP_DIR_NAMES = {".wiki", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
DEFAULT_ENTITY_TYPES = [
    "entity", "concept", "process", "rule", "role", "event",
    "model", "technique", "framework", "benchmark", "paper",
]
DEFAULT_RELATIONSHIP_TYPES = [
    "uses", "depends_on", "extends", "improves_upon", "contradicts",
    "supersedes", "caused_by", "fixed_by", "replaces", "relates_to",
    "part_of", "implemented_by",
]
CONCEPT_LIKE_TYPES = {"concept", "technique", "model", "framework", "benchmark", "paper", "pattern"}
INGEST_RULES = {
    "doc": (
        ["entity", "concept", "process", "rule", "role", "event"],
        "core concepts, named entities, processes, roles, rules, and events",
    ),
    "article": (
        ["concept", "entity", "model", "technique", "benchmark", "paper"],
        "claims, concepts, models, techniques, benchmarks, and cited work",
    ),
    "code": (
        ["entity", "concept", "framework", "tool", "file", "library", "decision"],
        "source files, libraries, tools, architectural decisions, and implementation patterns",
    ),
    "conversation": (
        ["decision", "concept", "entity", "process", "rule"],
        "decisions, findings, open questions, rules, and follow-up actions",
    ),
}

IMAGE_ANALYSIS_PROMPT = """Analyze this image for knowledge-base ingestion and retrieval.

Return clean markdown in Chinese when the image contains Chinese; otherwise use the image's main language.

## Required Sections (all images):

### 1. Image Type & Summary
- What type of image is this? (mind map / flowchart / architecture diagram / chart / table / document screenshot / photo / other)
- One-sentence summary of what this image communicates.
- Who is the likely audience? (engineers / managers / general / academic)

### 2. Content Extraction
- Preserve ALL visible text, labels, headings, legends, axes, units, numbers, tables, and annotations verbatim.

**★ Flowcharts & Process Diagrams (highest priority — default assumption for diagrams):**
Flowcharts encode logic through ARROWS — the direction IS the meaning. Missing an arrow = losing the entire logic chain.

Required output for any flowchart/process diagram:
1. **Start point**: where does the flow begin? (labeled node, or visually prominent entry)
2. **Step-by-step sequence**: number each step in execution order (Step 1 → Step 2 → ...). For each step:
   - Node text (verbatim)
   - Node shape if meaningful (rectangle=process, diamond=decision, oval=start/end, cylinder=data)
   - What arrow(s) come OUT of this node, and where they point
3. **Decision nodes** (diamonds): for EACH branch, state:
   - The condition written on the branch arrow (e.g., "Yes", "No", "> 1000", "审批通过")
   - Which node each branch leads to
   - If a branch loops back, state clearly: "↩ loops back to Step N"
4. **Parallel/concurrent flows**: if multiple paths run simultaneously, group them and state they are parallel
5. **End point(s)**: where does the flow terminate? Are there multiple end states?
6. **Logical summary**: after reconstructing all steps, write a 3-5 sentence summary of the overall logic:
   "This flowchart describes [process]. It starts at [X], then [key decision/action], and ends at [Y]. The critical path is [most important branch sequence]."

**Arrow direction conventions to watch for:**
- ↓ downward arrow: sequential next step
- → right arrow: forward progression / positive branch
- ← left arrow: loop back / return to previous step
- ↑ upward arrow: escalation / return to parent
- Diamond → two+ arrows: decision branch (ALWAYS capture both/all branches)
- Dashed arrow: optional / async / message passing
- Thick/bold arrow: main flow / primary path

- If it is a mind map: restore the full hierarchy as nested bullet lists.
- If it is an architecture diagram: identify layers, components, data flow direction, and protocols between components.
- If it is a chart: restore chart type, data series, axis labels with units, numeric values, and visible trends.
- If it is a document screenshot: extract text faithfully with section structure.
- If it contains a table: reproduce the table in markdown table format with all rows and columns.

### 3. Visual Properties
- Color scheme (dominant colors, color coding if meaningful)
- Layout style (top-down / left-to-right / radial / grid / freeform)
- Approximate element count (nodes, branches, cells, data points)
- Any visual emphasis (highlighted elements, callouts, annotations)
- Background: solid / transparent / gradient / image

### 4. Key Entities
- List named entities visible in the image (people, organizations, projects, systems, metrics, dates).
- These will be used for knowledge graph linking.

Avoid generic descriptions like "this is an image of a diagram" — be specific about what the image contains and how it's organized.
"""


def strip_sensitive(content: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def is_text_source(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def is_image_source(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_supported_source(path: Path) -> bool:
    return path.is_file() and (is_text_source(path) or is_image_source(path))


def iter_source_files(root: Path, max_depth: int | None = None) -> list[Path]:
    """Return supported source files under root, sorted for deterministic compiles.

    max_depth counts directory levels below root:
    - 0: only files directly under root
    - 1: include root's direct child directories
    - None: recurse through all subdirectories
    """
    files: list[Path] = []

    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        rel_parts = current_path.relative_to(root).parts
        depth = len(rel_parts)

        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIR_NAMES and not (current_path / d).is_symlink()
        )

        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []

        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                continue
            if is_supported_source(path):
                files.append(path)

    return files


def _ocr_image_with_config(image_path: Path) -> str:
    """Run the configured OCR backend on an image and return markdown text."""
    ocr_config = get_ocr_config()
    backend = ocr_config.get("backend", "mineru")

    if ocr_config.get("mode") == "api" or backend == "api":
        from ocr._ocr_api import OCRApiBackend
        return OCRApiBackend.from_config().ocr_image(str(image_path))
    if backend == "deepseek":
        from ocr._deepseek_ocr2 import DeepSeekOCR2
        return DeepSeekOCR2.from_config().ocr_image(str(image_path))
    if backend == "logics":
        from ocr._logics_parsing import LogicsParsingOCR
        return LogicsParsingOCR.from_config().ocr_image(str(image_path))
    if backend == "paddle":
        from ocr._paddle_ocr import PaddleOCRWrapper
        return PaddleOCRWrapper.from_config().ocr_image(str(image_path))
    from ocr._mineru_ocr import MinerUOCR
    return MinerUOCR.from_config().ocr_image(str(image_path))


def _copy_to_source_images(image_path: Path) -> Path:
    """Copy image to .wiki/source/images/ for persistent storage.

    Images referenced by original path will break if the file moves.
    Copying to the wiki ensures the image is always available.
    Preserves original filename; appends a short hash if collision.
    """
    SOURCE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCE_IMAGES_DIR / image_path.name
    if dest.exists():
        # Avoid collision: append short hash of original path
        import hashlib
        path_hash = hashlib.md5(str(image_path.resolve()).encode()).hexdigest()[:6]
        stem, ext = image_path.stem, image_path.suffix
        dest = SOURCE_IMAGES_DIR / f"{stem}-{path_hash}{ext}"
    import shutil
    shutil.copy2(image_path, dest)
    return dest


def analyze_image_for_compile(image_path: Path) -> str:
    """Convert an image source to markdown for wiki compilation.

    Pipeline:
    1. Copy image to .wiki/source/images/ for persistent storage
    2. Vision model analysis (if enabled) — rich description for retrieval
    3. OCR only as fallback when vision is disabled (vision already extracts text)

    For mind maps / flowcharts / diagrams: vision model restores structure.
    OCR is redundant for these — the vision model already sees and extracts all text.
    """
    image_config = get_image_analysis_config()
    analysis = ""
    ocr_text = ""

    # ── Step 1: Copy to persistent storage ──
    try:
        stored_path = _copy_to_source_images(image_path)
    except Exception as e:
        stored_path = image_path
        print(f"  WARNING: could not copy image to source/images: {e}", file=sys.stderr)

    # ── Step 2: Vision model analysis ──
    vision_enabled = bool(image_config.get("enabled"))
    if vision_enabled:
        try:
            from ocr._ocr_api import create_vision_backend
            backend = create_vision_backend(image_config, IMAGE_ANALYSIS_PROMPT)
            analysis = backend.ocr_image(str(image_path))
        except Exception as e:
            print(f"  WARNING: image analysis failed for {image_path}: {e}", file=sys.stderr)

    # ── Step 3: OCR only as fallback (vision already extracts text) ──
    # For mind maps, flowcharts, diagrams: vision model sees all text.
    # OCR is redundant and adds noise. Only run OCR when:
    #   - Vision is NOT enabled (ocr_fallback: true = default)
    #   - OR vision failed (analysis is empty)
    if not vision_enabled or not analysis:
        should_ocr = bool(image_config.get("ocr_fallback", True))
        if should_ocr:
            try:
                ocr_text = _ocr_image_with_config(image_path)
            except Exception as e:
                print(f"  WARNING: OCR fallback failed for {image_path}: {e}", file=sys.stderr)

    if not analysis and not ocr_text:
        raise RuntimeError(
            "Image compile requires image_analysis.enabled or a working OCR backend."
        )

    # ── Step 4: Build markdown output ──
    sections = [
        f"# Image Source: {image_path.name}",
        "",
        f"> **Original**: `{image_path.resolve()}`",
        f"> **Stored at**: `{stored_path.resolve()}`",
        f"> **Format**: {image_path.suffix.upper().lstrip('.')}",
        f"> **Size**: {image_path.stat().st_size // 1024} KB",
        "",
    ]

    if analysis:
        sections.extend(["## Visual Analysis", "", analysis.strip(), ""])
    if ocr_text and ocr_text.strip() != analysis.strip():
        sections.extend(["## OCR Text (fallback)", "", ocr_text.strip(), ""])

    return "\n".join(sections).strip() + "\n"


def _preprocess_svg(svg_path: Path) -> str:
    """Extract text and structure from SVG XML for LLM ingestion.

    SVG is vector XML — vision models can't process it. LLMs CAN read the XML,
    but raw SVG is noisy (path data, transforms, defs). This preprocessor extracts
    meaningful content: text elements, structural groups, metadata, and shape labels.
    """
    import xml.etree.ElementTree as ET

    try:
        # Parse SVG XML, stripping namespaces for simplicity
        raw = svg_path.read_text(encoding="utf-8")
        # Remove namespace prefixes so ElementTree can find tags
        cleaned = re.sub(r'<(\/?)(\w+):(\w+)', r'<\1\3', raw)
        cleaned = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', '', cleaned)
        root = ET.fromstring(cleaned)
    except Exception:
        # If parsing fails, return raw text — LLM can still extract info
        return raw

    ns = "{http://www.w3.org/2000/svg}"
    lines: list[str] = [
        f"# SVG Source: {svg_path.name}",
        "",
        "> **Format**: SVG (vector graphic — text extracted from XML)",
        f"> **Size**: {svg_path.stat().st_size // 1024} KB",
        "",
    ]

    # ── Metadata ──
    title = root.find(f".//{ns}title")
    desc = root.find(f".//{ns}desc")
    if title is not None and title.text:
        lines.append(f"**Title**: {title.text.strip()}")
    if desc is not None and desc.text:
        lines.append(f"**Description**: {desc.text.strip()}")
    if title is not None or desc is not None:
        lines.append("")

    # ── Extract text elements (the actual readable content) ──
    text_elements: list[str] = []
    for elem in root.iter():
        tag = elem.tag.replace(ns, "")
        if tag in ("text", "tspan") and elem.text:
            text = elem.text.strip()
            if text:
                text_elements.append(text)

    # ── Extract groups with IDs/labels (structure) ──
    groups: list[dict] = []
    for elem in root.iter():
        tag = elem.tag.replace(ns, "")
        if tag == "g":
            gid = elem.get("id", "")
            label = elem.get("aria-label", "") or elem.get("data-name", "")
            if gid or label:
                group_texts: list[str] = []
                for sub in elem.iter():
                    subtag = sub.tag.replace(ns, "")
                    if subtag in ("text", "tspan") and sub.text:
                        group_texts.append(sub.text.strip())
                groups.append({
                    "id": gid,
                    "label": label,
                    "texts": group_texts[:10],
                })

    # ── Build clean output ──
    if text_elements:
        lines.append("## Extracted Text")
        lines.append("")
        for t in text_elements[:100]:  # cap at 100 text elements
            lines.append(f"- {t}")
        lines.append("")

    if groups:
        lines.append("## Structure (Groups)")
        lines.append("")
        for g in groups[:30]:
            label = g["label"] or g["id"]
            if label:
                lines.append(f"### {label}")
                if g["texts"]:
                    for t in g["texts"][:5]:
                        lines.append(f"  - {t}")
                lines.append("")

    # ── Raw XML (truncated, for LLM reference) ──
    lines.append("## Raw SVG XML (reference)")
    lines.append("")
    lines.append("```xml")
    # Strip long path data for readability
    compact = re.sub(r'\s+d="[^"]{100,}"', ' d="[...]"', raw)
    lines.append(compact[:5000])
    lines.append("```")
    lines.append("")

    result = "\n".join(lines)
    if len(result) < 200:
        # Fallback: nothing useful extracted, return full raw
        return raw
    return result


def read_source_content(source_path: str | Path) -> tuple[str, str]:
    """Read a compile source and return (content, display_name)."""
    path = Path(source_path)
    if is_image_source(path):
        return analyze_image_for_compile(path), path.name

    # SVG: preprocess XML before sending to LLM
    if path.suffix.lower() == ".svg":
        return _preprocess_svg(path), path.name

    with open(path, encoding="utf-8") as f:
        return f.read(), path.name


def _read_agent_visible_source(source_path: Path) -> tuple[str, bool]:
    """Read source content without invoking OCR, vision, or configured LLM APIs."""
    try:
        if source_path.suffix.lower() == ".svg":
            return _preprocess_svg(source_path), True
        if is_text_source(source_path):
            size_bytes = source_path.stat().st_size
            if size_bytes > 50 * 1024 * 1024:
                return (
                    f"[File too large ({size_bytes // 1024 // 1024} MB). "
                    f"Agent should read the file directly.]",
                    False,
                )
            return source_path.read_text(encoding="utf-8"), True
        return "", False
    except (OSError, UnicodeDecodeError):
        return "", False


def infer_source_type(path: Path) -> str:
    """Return a lightweight hint only; final source type belongs to the Agent."""
    name_lower = path.name.lower()
    if "chat" in name_lower or "conversation" in name_lower:
        return "conversation"
    suffix = path.suffix.lower()
    if suffix in {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".sql"}:
        return "code"
    if suffix in {".md", ".markdown", ".rst", ".adoc", ".html", ".htm"}:
        return "article"
    return "doc"


def create_agent_compile_task(
    source_path: str,
    source_type: str = "auto",
    force: bool = False,
    dry_run: bool = False,
    depth: int | None = None,
) -> dict:
    """Create an Agent-readable compile task without calling configured models.

    The current Agent is expected to read the source when possible, classify the
    document type, and write wiki pages according to schema.md and compile rules.
    """
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    task_dir = WIKI_DIR / "agent_tasks"
    task_dir.mkdir(parents=True, exist_ok=True)

    if path.is_dir():
        try:
            sources = iter_source_files(path, max_depth=depth)
        except PermissionError as e:
            raise PermissionError(
                f"Cannot read source directory: {e}. Check directory permissions."
            ) from e
        max_entries = 500
        displayed = sources[:max_entries]
        remaining = sources[max_entries:]
        suffix = ""
        if remaining:
            suffix = f"\n\n... and {len(remaining)} more files:\n"
            suffix += "\n".join(f"- `{src}`" for src in remaining[:10])
            if len(remaining) > 10:
                suffix += f"\n- ... ({len(remaining) - 10} additional files omitted)"
        source_entries = "\n".join(f"- `{src}`" for src in displayed) + suffix or "- No supported files found"
        readable_content = ""
        readable = False  # Directory: individual file readability is unknown without per-file extraction
        source_name = path.name
        source_hint = "directory"
    else:
        content, readable = _read_agent_visible_source(path)
        readable_content = strip_sensitive(content) if readable else ""
        source_entries = f"- `{path}`"
        source_name = path.name
        source_hint = infer_source_type(path)

    selected_type = source_type if source_type != "auto" else "Agent must decide"
    schema_text = ""
    if SCHEMA_PATH.is_file():
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")[:12000]
    else:
        template_schema = Path(__file__).resolve().parent.parent / "templates" / "schema.md"
        if template_schema.is_file():
            schema_text = template_schema.read_text(encoding="utf-8")[:12000]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", source_name).strip("-") or "source"
    task_path = task_dir / f"compile-{timestamp}-{safe_name}.md"

    content_block = ""
    if path.is_file() and readable:
        preview = readable_content[:50000]
        truncated = "\n\n[TRUNCATED: Agent should read the source file directly.]" if len(readable_content) > len(preview) else ""
        content_block = f"""## Source Content Preview

```text
{preview}
```
{truncated}
"""
    elif path.is_file():
        content_block = """## Source Readability

The script did not extract text from this source without OCR/vision/model calls.
The Agent should try to inspect/read the file with available capabilities. If the
Agent cannot read it, ask the user to provide a text export or summary.
"""

    task = f"""# Agent Compile Task

This task was generated in Agent mode. Do not call the configured LLM API.

## Source

{source_entries}

- Requested type: `{selected_type}`
- Source type hint: `{source_hint}`
- Force overwrite: `{force}`
- Dry run: `{dry_run}`
- Wiki dir: `{WIKI_DIR}`

## Agent Responsibilities

1. Read the source directly if possible.
2. Decide the source type: `doc`, `article`, `code`, or `conversation`.
3. Compile knowledge according to `.wiki/schema.md` and LLM Wiki compile rules.
4. Write pages under `.wiki/pages/concepts/` or `.wiki/pages/entities/`.
5. Update `.wiki/pages/index.md`, `.wiki/graph/entities.json`, `.wiki/graph/edges.json`,
   `.wiki/log.md`, and `.wiki/audit.json`.
6. If the source cannot be read, stop and ask the user for readable content.

## Required Page Standard

- YAML frontmatter: `id`, `type`, `name`, `confidence`, `source`, `aliases`, `keywords`.
- Sections in order: Key Facts/关键事实, Overview/概述, Questions This Page Answers/可回答的问题,
  Key Details/关键细节, Relationships/关联关系, Source Context/来源上下文.
- IDs and entity types must follow schema.md.
- Prefer high-quality compiled pages over raw chunks. This is not a RAG ingestion step.

## Schema Context

```markdown
{schema_text}
```

{content_block}
"""
    if not dry_run:
        atomic_write(task_path, task)
    return {
        "source": str(path),
        "mode": "agent",
        "agent_task": str(task_path) if not dry_run else "(dry-run — task not written)",
        "needs_agent": True,
        "readable": readable,
        "pages_created": 0,
        "pages_updated": 0,
        "dry_run": dry_run,
        "message": (
            "Agent compile task created. The current Agent should execute this task; "
            "no configured LLM was called."
        ),
    }


def extract_edge_type(line: str) -> str:
    for pattern, rel_type in KEYWORD_RELATION_MAP:
        if re.search(pattern, line):
            return rel_type
    return "relates_to"


def _parse_schema_table(section_title: str) -> list[list[str]]:
    """Parse a backtick-based markdown table from schema.md."""
    if not SCHEMA_PATH.exists():
        return []

    rows: list[list[str]] = []
    in_section = False
    for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip() == section_title:
            in_section = True
            continue
        if in_section and line.startswith("## ") and line.strip() != section_title:
            break
        if in_section and line.startswith("| `"):
            parts = [part.strip().strip("`").strip() for part in line.split("|")[1:-1]]
            if parts:
                rows.append(parts)
    return rows


def load_entity_types_from_schema() -> tuple[list[str], str, str]:
    """Load entity and relationship type prompt context from .wiki/schema.md."""
    entity_rows = _parse_schema_table("## Entity Types")
    rel_rows = _parse_schema_table("## Relationship Types")

    entity_types: list[str] = []
    entity_lines: list[str] = []
    for row in entity_rows:
        if len(row) >= 3 and row[0] and row[0] != "type":
            entity_types.append(row[0])
            entity_lines.append(f"- **{row[0]}**: {row[2]}")

    rel_types: list[str] = []
    rel_lines: list[str] = []
    for row in rel_rows:
        if row and row[0] and row[0].lower() != "type":
            rel_types.append(row[0])
            meaning = row[2] if len(row) >= 3 else f"entity A {row[0]} entity B"
            rel_lines.append(f"- **{row[0]}**: {meaning}")

    for entity_type in DEFAULT_ENTITY_TYPES:
        if entity_type not in entity_types:
            entity_types.append(entity_type)
            entity_lines.append(f"- **{entity_type}**: {entity_type} page")

    for rel_type in DEFAULT_RELATIONSHIP_TYPES:
        if rel_type not in rel_types:
            rel_lines.append(f"- **{rel_type}**: entity A {rel_type} entity B")

    return entity_types, "\n".join(entity_lines), "\n".join(rel_lines)


def load_ingest_rules_from_schema(source_type: str) -> tuple[list[str], str]:
    """Return source-type focus rules for compile prompts."""
    return INGEST_RULES.get(source_type, INGEST_RULES["doc"])

def load_config():
    return get_config()


def get_paths():
    wiki_dir = get_wiki_dir()
    return {
        "wiki_dir": wiki_dir,
        "pages_dir": wiki_dir / "pages",
        "entities_dir": wiki_dir / "pages" / "entities",
        "concepts_dir": wiki_dir / "pages" / "concepts",
        "index_file": wiki_dir / "pages" / "index.md",
        "schema_path": wiki_dir / "schema.md",
        "graph_dir": wiki_dir / "graph",
    }

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
ENTITIES_DIR = PAGES_DIR / "entities"
CONCEPTS_DIR = PAGES_DIR / "concepts"
INDEX_FILE = PAGES_DIR / "index.md"
SCHEMA_PATH = WIKI_DIR / "schema.md"
GRAPH_DIR = WIKI_DIR / "graph"
SOURCE_IMAGES_DIR = WIKI_DIR / "source" / "images"


def atomic_write(path: Path, content: str):
    """Atomic file write (temp + rename, safe against partial writes)."""
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def write_audit(operation: str, details: dict):
    audit_file = WIKI_DIR / "audit.json"
    audit_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **details,
    }

    entries = []
    if audit_file.exists():
        try:
            entries = json.loads(audit_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(entry)
    audit_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_contradictions(page_id: str, new_content: str, existing_content: str) -> list:
    system_prompt = """You are a contradiction detector for wiki pages.
Compare existing content with new content and identify contradictions.

Output JSON array of contradictions found:
[
  {
    "existing_claim": "Old claim text",
    "new_claim": "New claim text",
    "contradiction_type": "factual|temporal|numerical|opinion",
    "severity": "high|medium|low",
    "resolution_suggestion": "Which is more likely correct and why"
  }
]

If no contradictions, output: []

Be strict - only flag actual contradictions, not additions or clarifications."""

    user_prompt = f"""Page ID: {page_id}

EXISTING CONTENT:
{existing_content[:2000]}

NEW CONTENT:
{new_content[:2000]}

Find contradictions between existing and new content."""

    try:
        response = call_llm(system_prompt, user_prompt)
        return json.loads(response)
    except Exception:
        _log_exc("contradiction detection failed")
        return []


def auto_resolve_contradictions(page_id: str, contradictions: list[dict]) -> list[dict]:
    """Return conservative contradiction resolutions without overwriting claims.

    Compile should never abort because a reinforcement conflicts with an
    existing page. The safe default is to flag each contradiction for review
    and preserve both claims in the page history.
    """
    resolutions: list[dict] = []
    for contradiction in contradictions:
        suggestion = str(contradiction.get("resolution_suggestion", "")).strip()
        severity = str(contradiction.get("severity", "medium")).lower()
        confidence = 0.35 if severity == "high" else 0.5
        resolutions.append({
            "page_id": page_id,
            "winner": "manual_review",
            "confidence": confidence,
            "reasoning": suggestion or "Contradiction detected during compile; preserved for manual review.",
            "action": "flag",
        })
    return resolutions


def detect_language(text: str) -> str:
    """Detect if text is predominantly Chinese or English.

    Returns 'zh' if Chinese characters exceed threshold, 'en' otherwise.
    """
    if not text:
        return "en"
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    total = len(text)
    if total > 0 and cjk_count / total > 0.08:
        return "zh"
    return "en"
def _count_facts(page_content: str) -> tuple[int, int]:
    """Count facts and relationships in a compiled page."""
    fact_count = 0
    rel_count = 0
    
    # Count facts in Key Facts table rows: | attr | value |
    in_facts_section = False
    for line in page_content.split("\n"):
        stripped = line.strip()
        
        # Track section
        if stripped.startswith("## 关键事实") or stripped.startswith("## Key Facts"):
            in_facts_section = True
            continue
        elif stripped.startswith("## ") and in_facts_section:
            in_facts_section = False
            continue
        
        # Count fact table rows
        if in_facts_section and stripped.startswith("|") and not stripped.startswith("|---") and "|" in stripped[1:]:
            parts = [p.strip() for p in stripped.split("|")[1:-1]]
            if len(parts) >= 2 and parts[0] and parts[0] not in ("属性", "Attribute", "------"):
                fact_count += 1
        
        # Also count **key**: value facts
        if stripped.startswith("**") and "**:" in stripped:
            fact_count += 1
        
        # Count relationships
        if stripped.startswith("- ") and "[[" in stripped:
            rel_count += 1
    
    return fact_count, rel_count


def _print_dry_run_preview(source_name: str, all_pages: list, created_pages: list, updated_pages: list):
    """Print a structured preview of what would be compiled — no files written."""
    divider = "=" * 70
    print(f"\n{divider}", file=sys.stderr)
    print(f"  DRY-RUN PREVIEW: {source_name}", file=sys.stderr)
    print(f"  {len(created_pages)} new pages, {len(updated_pages)} updated, {len(all_pages)} total", file=sys.stderr)
    print(divider, file=sys.stderr)

    if not all_pages:
        print("  (no pages would be created)", file=sys.stderr)
        print(divider, file=sys.stderr)
        return

    # ── Table header ──
    header = f"  {'#':<4} {'ID':<32} {'Type':<12} {'Title':<22} {'Facts':<6} {'Rels':<5}"
    print(header, file=sys.stderr)
    print(f"  {'-'*4} {'-'*32} {'-'*12} {'-'*22} {'-'*6} {'-'*5}", file=sys.stderr)

    entity_count = 0
    concept_count = 0
    total_facts = 0
    total_relationships = 0

    for i, page in enumerate(all_pages):
        pid = page.get("id", "?")[:30]
        ptype = page.get("type", "?")[:10]
        pname = page.get("name", pid)[:20]
        facts_count = str(page.get("facts", "?"))
        rels_count = str(page.get("relationships", "?"))

        if ptype in ("concept", "technique", "model", "framework", "benchmark", "paper"):
            concept_count += 1
        else:
            entity_count += 1

        marker = " +" if page in created_pages else " ~"
        print(f"  {marker:<3} {pid:<32} {ptype:<12} {pname:<22} {facts_count:<6} {rels_count:<5}", file=sys.stderr)

    print(f"  {'-'*4} {'-'*32} {'-'*12} {'-'*22} {'-'*6} {'-'*5}", file=sys.stderr)
    print(f"  Entities: {entity_count}  |  Concepts: {concept_count}  |  Total: {len(all_pages)}", file=sys.stderr)
    print(divider, file=sys.stderr)
    print("  No files were written. Use without --dry-run to compile.", file=sys.stderr)
    print(divider, file=sys.stderr)




# ── Document chunking (model-context-aware) ────────────────────────────

def _estimate_tokens(text: str, lang: str = "en") -> int:
    """Rough token count estimate. ~4 chars/token for EN, ~2 for CJK."""
    if not text:
        return 0
    if lang == "zh":
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
        non_cjk = len(text) - cjk
        return cjk // 2 + non_cjk // 4
    return len(text) // 4


def _split_by_headings(content: str, max_tokens: int, lang: str = "en") -> list[str]:
    """Split document by ``## `` headings, keeping chunks under *max_tokens*.

    Each chunk is a self-contained section group. Headings before the first
    ``## `` form the preamble chunk.
    """
    sections = re.split(r'(\n## .+)', content)
    if not sections:
        return [content] if content else []

    # Recombine: preamble + paired (heading, body) sections
    chunks_raw: list[str] = []
    preamble = sections[0].strip()
    if preamble:
        chunks_raw.append(preamble)

    i = 1
    while i < len(sections):
        heading = sections[i]
        body = sections[i + 1] if i + 1 < len(sections) else ""
        chunks_raw.append((heading + body).strip())
        i += 2

    # Merge chunks under max_tokens
    merged: list[str] = []
    current = ""
    for chunk in chunks_raw:
        combined = current + "\n\n" + chunk if current else chunk
        if _estimate_tokens(combined, lang) <= max_tokens:
            current = combined
        else:
            if current:
                merged.append(current)
            # If single chunk still exceeds max_tokens, split further by paragraphs
            if _estimate_tokens(chunk, lang) > max_tokens:
                sub_chunks = _split_by_paragraphs(chunk, max_tokens, lang)
                merged.extend(sub_chunks)
                current = ""
            else:
                current = chunk
    if current:
        merged.append(current)

    return merged if merged else [content]


def _split_by_paragraphs(text: str, max_tokens: int, lang: str = "en") -> list[str]:
    """Fallback: split an oversized chunk by blank-line-separated paragraphs."""
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = current + "\n\n" + para if current else para
        if _estimate_tokens(candidate, lang) <= max_tokens:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks if chunks else [text]

def _compile_chunked(
    chunks: list[str],
    source_name: str,
    source_type: str,
    force: bool,
    dry_run: bool,
    lang: str,
    entity_types: list[str],
    entity_type_lines: str,
    rel_type_lines: str,
    focus_types: list[str],
    focus_desc: str,
    entity_type_str: str,
) -> dict:
    """Compile a large document in chunks, then merge with dedup."""
    all_created: list[dict] = []
    all_updated: list[dict] = []
    seen_ids: set[str] = set()

    for i, chunk in enumerate(chunks):
        chunk_name = f"{source_name} [part {i+1}/{len(chunks)}]"
        print(f"  Compiling chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...", file=sys.stderr)

        try:
            result = _compile_single_chunk(
                chunk, chunk_name, source_type, force, dry_run,
                lang, entity_types, entity_type_lines, rel_type_lines,
                focus_types, focus_desc, entity_type_str,
            )
        except Exception as e:
            print(f"  ERROR: chunk {i+1}/{len(chunks)} failed: {e}", file=sys.stderr)
            continue

        # Dedup: skip pages already seen from earlier chunks
        for page in result.get("created_pages", []):
            if page["id"] not in seen_ids:
                seen_ids.add(page["id"])
                all_created.append(page)
        for page in result.get("updated_pages", []):
            if page["id"] not in seen_ids:
                seen_ids.add(page["id"])
                all_updated.append(page)
            # else: update confidence/reinforcement for already-seen entity

    all_pages = all_created + all_updated
    if not all_pages:
        print("  WARNING: No pages extracted from any chunk!", file=sys.stderr)
        return {"source": source_name, "pages_created": 0, "pages_updated": 0, "pages": []}

    # Post-processing: write pages (unless dry_run), update index/graph
    if not dry_run:
        ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
        CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)
        for page in all_pages:
            atomic_write(Path(page["path"]), page.get("_content", ""))

        update_index(all_pages, source_name)
        update_log(source_name, len(all_created), "compile")
        update_graph(all_pages, source_name)
        write_audit("compile", {
            "source": source_name,
            "chunked": True,
            "chunks": len(chunks),
            "pages_created": len(all_created),
            "pages_updated": len(all_updated),
        })

    if dry_run:
        _print_dry_run_preview(source_name, all_pages, all_created, all_updated)

    return {
        "source": source_name,
        "pages_created": len(all_created),
        "pages_updated": len(all_updated),
        "pages": all_pages,
        "chunked": True,
        "chunks": len(chunks),
    }


def _compile_single_chunk(
    chunk_content: str,
    chunk_name: str,
    source_type: str,
    force: bool,
    dry_run: bool,
    lang: str,
    entity_types: list[str],
    entity_type_lines: str,
    rel_type_lines: str,
    focus_types: list[str],
    focus_desc: str,
    entity_type_str: str,
) -> dict:
    """Compile a single document chunk — same LLM call as compile_source but
    returns parsed pages without writing files (writing is handled by the
    chunked-compile orchestrator)."""
    import re as _re
    source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', chunk_name)[:8].lower() or "doc"

    # Build prompts (abbreviated — reuse the same structure as compile_source)
    if lang == "zh":
        system_prompt = f"""你是 Wiki 知识编译引擎。你必须用中文撰写所有内容。

## ID 命名规则（防止同名覆盖）
文档源简称: {source_abbr}

- **实体页 ID**: `{source_abbr}-{{{{实体名}}}}` — 确保不同来源的同名实体不覆盖
- **概念页 ID**: 直接使用概念名 — 跨文档共享

## 实体 vs 概念（这是最重要的分类！）
- **实体 (entity/role/rule/process/event/tool/system/product)**:
  文档中具体出现的东西。某个特定组织、某个具体角色、某条明确规则、某个特定流程步骤。
  特征：可以指向"一个具体实例"。**必须带 {source_abbr} 前缀**。

- **概念 (concept/technique/model/framework/benchmark/paper)**:
  跨文档的抽象知识。通用思想、方法论、技术模式、评估标准。
  特征：可以在多个文档中讨论，不依附于单一来源。**不带前缀**。

**比例**: 文档中约 65% 实体, 35% 概念。绝大多数具体内容都是实体！

## 提取策略（逐段扫描，不要遗漏！）
1. **从头到尾扫描文档的每个章节**——不要只提取开头部分
2. 先找实体：组织名、人名、角色、规则条目、流程步骤、工具/系统名
3. 再找概念：本文档揭示的通用模式、方法论、技术方案
4. 对每个提取的内容问自己："这是具体实例还是通用概念？"——答案决定 ID 和存放位置

## 内容质量要求
- **关键事实表（🔴 必须输出！这是用户查询时获取精确答案的唯一来源）**:
  从文档中提取可查询的结构化事实，格式为表格。每个页面至少 3-5 条事实。
  必须包含文档中的精确数值、日期、名称。**没有关键事实表的页面会被查询系统忽略！**
- **概述**: 2-4句，说清楚"是什么 + 为什么重要 + 在本文档中的角色"
- **可回答的问题**: 列出 2-3 个该页面能精确回答的具体问题（用问句形式），帮助判断检索匹配
- **关键细节**: 提取具体事实——数字、日期、名称、判定标准、配置参数、步骤说明
- **关联关系**: 每个页面至少列出 2-4 个关联，用指定的关系关键词
- **来源上下文**: 原文摘录，便于人工核实

## 关键事实表撰写规范（★决定检索质量）
从文档原文中提取"属性 → 值"对。这些是用户查询时需要的精确答案。

正确示例:
  facts:
    审计日志保留期: 7年（亚太区企业客户）
    速率限制: 1000 req/s（Premium Partner）
    SOC 2 证据保留: 事件响应报告保留 3 年
    回滚审批人: 运维经理 + 部门总监双签
    GPU 配置建议: 7B→1×A100, 70B→4×A100

错误示例（太模糊，无法回答查询）:
  facts:
    保留期: 按规定执行
    速率: 有限制

规则:
- 每个属性必须能从文档中找到明确数值/名称/日期作为证据
- 优先提取: 数字、阈值、日期、人名、百分比、配置参数
- 如果文档提到多个值（如不同套餐），每个值单独一条
- 属性名用中文，值保留原文中的精确表述

## 关系关键词（每条关系必须用以下关键词之一开头）
关系关键词 -> 对应类型:
- 使用 [[X]] / 采用 [[X]] / 利用 [[X]] -> uses
- 依赖 [[X]] / 取决于 [[X]] -> depends_on
- 扩展 [[X]] / 基于 [[X]] -> extends
- 改进 [[X]] / 优化 [[X]] / 增强 [[X]] -> improves_upon
- 关联 [[X]] / 相关 [[X]] / 协作 [[X]] -> relates_to
- 属于 [[X]] / 组成部分 [[X]] -> part_of
- 负责 [[X]] / 实现 [[X]] / 执行 [[X]] -> implemented_by
- 导致 [[X]] / 引起 [[X]] -> caused_by
- 修复 [[X]] / 解决 [[X]] -> fixed_by
- 取代 [[X]] / 替换 [[X]] -> supersedes
- 矛盾 [[X]] / 冲突 [[X]] -> contradicts

## Output Format
用 ===PAGE_END=== 分隔每个页面。

每个页面必须包含 YAML frontmatter：
---
id: 实体ID或概念ID
type: {entity_type_str}
name: 中文名称
confidence: 0.85
source: source-name
aliases: [别名1, 别名2]
keywords: [关键词1, 关键词2]
---

然后按以下结构撰写（⚠️ 必须严格遵循此顺序！）：
# [中文标题]

## 关键事实
🔴 **必须输出！这是页面最重要的部分——用户查询时从这里获取精确答案。**
| 属性 | 值 |
|------|-----|
| 属性名1 | 精确值1 |
| 属性名2 | 精确值2 |
（至少 3-5 行，每行是一个可查询的精确事实。没有此节的页面将被视为无效！）

## 概述
[2-4 句中文描述：这是什么，为什么重要，在文档中的角色]

## 可回答的问题
- 问题1？（该页面能精确回答的具体问题）
- 问题2？
（2-3 个具体问句，帮助判断此页面是否匹配用户的查询意图）

## 关键细节
- [具体事实1：包含数字、日期或名称]
- [具体事实2]
- [具体事实3]
...

## 关联关系
- 关键词 [[目标实体]] — 关系说明
...

## 来源上下文
> [文档原文摘录，便于核实]

## 质量规则
- 🔴 **关键事实表是强制要求！没有此节的页面 = 无效页面。**
- 扫描文档的每个章节，不要遗漏后半部分内容
- 实体（entity/role/rule/process/event/tool/system/product）→ ID 带 {source_abbr} 前缀
- 概念（concept/technique/model/framework/benchmark/paper）→ ID 不带前缀
- 实体:概念比例约 65:35
- 每个页面至少 150 字实质性内容
- 每个页面至少 2-4 条关联关系
- 目标: 与本段内容匹配的适当数量页面

## 实体类型参考
{entity_type_lines}

## ⚠️ 注意：这是一篇长文档的一个片段（chunk）。只提取本片段中出现的内容。
## 不要编造不在原文中的事实、数字或关系。"""

        user_prompt = f"""文档片段: {chunk_name}

内容:
{chunk_content}

请逐段扫描该文档片段，提取所有重要实体和概念，撰写 Wiki 页面。所有内容必须用中文。

## 提取步骤
1. 扫描片段中的每个章节标题，确保不遗漏任何部分
2. 提取所有具名实体（组织、角色、规则、流程、工具、系统）
3. 识别跨文档通用概念（方法论、技术模式、评估框架）
4. 为每个实体/概念建立关联关系链接

## 实体 ID 规则（重要！）
- entity/role/rule/process/event/tool/system/product → ID 必须带 {source_abbr} 前缀
- concept/technique/model/framework/benchmark/paper → ID 不带前缀

## 关注点
{focus_desc}。核心概念、组织结构、流程机制、评估标准、具体规则。

## 目标
与本段内容匹配的适当数量中文页面，内容详实，每页至少 2-4 条关系。
用 ===PAGE_END=== 分隔每个页面。"""
    else:
        system_prompt = f"""You are a wiki knowledge compiler. Your job is to read a document chunk and write high-quality wiki pages.

## Entity vs Concept (CRITICAL — get this right!)
Karpathy's wiki design distinguishes two page types:
- **entity** (entity/role/rule/process/event/tool/system/product):
  Concrete instances in the document. ~65% of pages.
- **concept** (concept/technique/model/framework/benchmark/paper):
  Abstract knowledge reusable across documents. ~35% of pages.

## Extraction Strategy
1. Scan EVERY section of this chunk — don't stop after the first few sections
2. Extract all named entities (orgs, people, rules, processes, tools, systems)
3. Identify cross-cutting concepts (methods, patterns, frameworks)

## Content Quality
- **Fact Table (🔴 REQUIRED — the ONLY source of precise answers!)**: At least 3-5 facts per page. Include exact numbers, dates, names. **Pages without Key Facts are INVALID.**
- **Overview**: 2-4 sentences: what + why + role
- **Questions This Page Answers**: 2-3 specific questions this page can answer
- **Key Details**: Extract specific facts — numbers, dates, names, criteria, parameters
- **Relationships**: Minimum 2-4 per page, use exact keywords below

## Relationship Keywords
- uses [[X]] / employs [[X]] → uses
- depends on [[X]] → depends_on
- extends [[X]] / based on [[X]] → extends
- improves [[X]] / enhances [[X]] → improves_upon
- relates to [[X]] → relates_to
- part of [[X]] → part_of
- implemented by [[X]] → implemented_by
- caused by [[X]] → caused_by
- fixed by [[X]] → fixed_by
- supersedes [[X]] → supersedes
- contradicts [[X]] → contradicts

## Output Format
===PAGE_END=== separated. YAML frontmatter required.

Page structure (⚠️ MUST follow this order!):
# [Title]

## Key Facts
🔴 **REQUIRED! Most important section.**
| Attribute | Value |
|-----------|-------|
| attr1 | precise value1 |
(3-5 rows minimum)

## Overview
[2-4 sentences]

## Questions This Page Answers
- Question 1?
(2-3 specific questions)

## Key Details
- [Specific fact with numbers/dates/names]
...

## Relationships
- keyword [[target]] — explanation
...

## Source Context
> [Verbatim excerpt]

## Quality Rules
- 🔴 **Key Facts table is MANDATORY! Pages without it = INVALID.**
- Scan EVERY section
- entity/role/rule/process/event/tool/system/product → lowercase-hyphenated IDs
- concept/technique/model/framework/benchmark/paper → lowercase-hyphenated IDs
- ~65% entity, ~35% concept
- Min 150 words per page, 2-4 relationships
- Target: appropriate number for this chunk's content

## Entity Types
{entity_type_lines}

## ⚠️ This is a chunk of a larger document. Only extract content present in this chunk.
## Do NOT fabricate facts, numbers, or relationships not in the source text."""

        user_prompt = f"""Document chunk: {chunk_name}

Content:
{chunk_content}

Scan this chunk and extract all important entities and concepts into wiki pages.

## Extraction Steps
1. Scan each section heading — ensure no content is missed
2. Extract all named entities (orgs, roles, rules, processes, tools, systems)
3. Identify cross-document concepts (methods, techniques, patterns, frameworks)
4. Establish typed relationships between related entities

## Focus Areas
{focus_desc}. Architecture innovations, model variants, techniques, benchmarks, key findings.

## Target
Appropriate number of pages for this chunk with substantive content, min 2-4 relationships each.
Output pages separated by ===PAGE_END==="""

    print("    Calling LLM for chunk...", file=sys.stderr)
    response = call_llm(system_prompt, user_prompt)

    # Parse pages from response (same logic as compile_source)
    pages = response.split("===PAGE_END===")
    created_pages: list[dict] = []
    updated_pages: list[dict] = []

    concept_types = CONCEPT_LIKE_TYPES
    for page_content in pages:
        page_content = page_content.strip()
        if not page_content or not page_content.startswith("---"):
            continue

        lines = page_content.split("\n")
        frontmatter_end = 0
        for i, line in enumerate(lines):
            if i > 0 and line.strip() == "---":
                frontmatter_end = i
                break
        if frontmatter_end == 0:
            continue

        frontmatter_text = "\n".join(lines[1:frontmatter_end])
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except Exception:
            continue

        entity_id = frontmatter.get("id", "")
        entity_type = frontmatter.get("type", "concept")
        if not entity_id:
            continue

        target_dir = CONCEPTS_DIR if entity_type in concept_types else ENTITIES_DIR
        page_path = target_dir / f"{entity_id}.md"
        f_count, r_count = _count_facts(page_content)

        created_pages.append({
            "id": entity_id,
            "type": entity_type,
            "name": frontmatter.get("name", entity_id),
            "path": str(page_path),
            "facts": f_count,
            "relationships": r_count,
            "_content": page_content,
        })

    return {
        "created_pages": created_pages,
        "updated_pages": updated_pages,
    }


import hashlib as _hashlib


def _content_hash(text: str) -> str:
    """Stable hash of page body (excluding YAML frontmatter)."""
    # Strip frontmatter for comparison — metadata may change without content change
    if text.startswith("---"):
        parts = text.split("---", 2)
        body = parts[2] if len(parts) > 2 else text
    else:
        body = text
    return _hashlib.md5(body.strip().encode("utf-8")).hexdigest()


def _get_source_pages(source_name: str) -> dict[str, dict]:
    """Return all wiki pages previously created by *source_name*.

    Returns dict of {page_id: {path, content_hash, source}} by scanning
    entities/ and concepts/ directories for pages with matching source field.
    """
    result: dict[str, dict] = {}
    for scan_dir in (ENTITIES_DIR, CONCEPTS_DIR):
        if not scan_dir.exists():
            continue
        for md_file in scan_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            # Check source in frontmatter
            source_match = re.search(r'^source:\s*(.+)$', text, re.MULTILINE)
            if not source_match:
                continue
            page_source = source_match.group(1).strip()
            if page_source != source_name:
                continue
            # Check for manual protection
            is_manual = bool(re.search(r'^source:\s*manual$', text, re.MULTILINE))
            page_id = md_file.stem
            result[page_id] = {
                "path": md_file,
                "content_hash": _content_hash(text),
                "source": page_source,
                "manual": is_manual,
            }
    return result


def _prune_stale_pages(
    new_page_ids: set[str], source_name: str, dry_run: bool = False
) -> list[str]:
    """Remove pages from *source_name* that no longer appear in new compilation.

    Only removes pages whose source field matches *source_name* exactly.
    Manual pages (source: manual) are never pruned.
    Returns list of removed page IDs.
    """
    existing = _get_source_pages(source_name)
    removed: list[str] = []
    for page_id, info in existing.items():
        if page_id in new_page_ids:
            continue
        if info.get("manual"):
            continue
        if dry_run:
            print(f"  [DRY-RUN] Would prune: {info['path'].name}", file=sys.stderr)
        else:
            try:
                info["path"].unlink()
                print(f"  Pruned: {info['path'].name}", file=sys.stderr)
            except OSError as e:
                print(f"  WARNING: failed to prune {info['path'].name}: {e}", file=sys.stderr)
        removed.append(page_id)
    return removed


def compile_source(source_path: str, source_type: str = "doc", force: bool = False, dry_run: bool = False) -> dict:

    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source not found: {source_path}")

    source_file = Path(source_path)
    if source_file.is_dir():
        return compile_path(source_path, source_type=source_type, force=force)

    content, source_name = read_source_content(source_file)

    content = strip_sensitive(content)

    lang = detect_language(content)
    entity_types, entity_type_lines, rel_type_lines = load_entity_types_from_schema()
    focus_types, focus_desc = load_ingest_rules_from_schema(source_type)
    entity_type_str = "|".join(entity_types)

    print(f"Compiling {source_name} ({len(content)} chars, {lang}, {source_type})...", file=sys.stderr)
    print(f"  Focus: {', '.join(focus_types)} — {focus_desc}", file=sys.stderr)

    # ── Large document chunking (model-context-aware) ──
    chunk_threshold = get_chunk_threshold()
    est_tokens = _estimate_tokens(content, lang)
    if est_tokens > chunk_threshold:
        chunks = _split_by_headings(content, chunk_threshold, lang)
        if len(chunks) > 1:
            max_ctx = get_chunk_threshold()  # will return model max without override
            print(
                f"  Document exceeds model context threshold "
                f"({est_tokens} > {chunk_threshold} tokens), "
                f"splitting into {len(chunks)} chunks...",
                file=sys.stderr,
            )
            return _compile_chunked(
                chunks, source_name, source_type, force, dry_run,
                lang, entity_types, entity_type_lines, rel_type_lines,
                focus_types, focus_desc, entity_type_str,
            )

    if lang == "zh":
        # Derive a short source abbreviation for ID prefix
        import re as _re
        source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', source_name)[:8].lower() or "doc"
        system_prompt = f"""你是 Wiki 知识编译引擎。你必须用中文撰写所有内容。

## ID 命名规则（防止同名覆盖）
文档源简称: {source_abbr}

- **实体页 ID**: `{source_abbr}-{{实体名}}` — 确保不同来源的同名实体不覆盖
  例: `{source_abbr}-专家评审组`, `{source_abbr}-评分标准`
- **概念页 ID**: 直接使用概念名 — 跨文档共享
  例: `专家评审组机制`, `AI赋能理念`

## 实体 vs 概念（这是最重要的分类！）
- **实体 (entity/role/rule/process/event/tool/system/product)**:
  文档中具体出现的东西。某个特定组织、某个具体角色、某条明确规则、某个特定流程步骤。
  特征：可以指向"一个具体实例"。**必须带 {source_abbr} 前缀**。
  例: "XX公司的评审委员会"是 entity，"XX项目2025年预算"是 entity

- **概念 (concept/technique/model/framework/benchmark/paper)**:
  跨文档的抽象知识。通用思想、方法论、技术模式、评估标准。
  特征：可以在多个文档中讨论，不依附于单一来源。**不带前缀**。
  例: "MoE架构"是 concept，"数字化转型方法论"是 concept

**比例**: 文档中约 65% 实体, 35% 概念。绝大多数具体内容都是实体！

## 提取策略（逐段扫描，不要遗漏！）
1. **从头到尾扫描文档的每个章节**——不要只提取开头部分
2. 先找实体：组织名、人名、角色、规则条目、流程步骤、工具/系统名
3. 再找概念：本文档揭示的通用模式、方法论、技术方案
4. 对每个提取的内容问自己："这是具体实例还是通用概念？"——答案决定 ID 和存放位置

## 内容质量要求
- **关键事实表（🔴 必须输出！这是用户查询时获取精确答案的唯一来源）**: 
  从文档中提取可查询的结构化事实，格式为表格。每个页面至少 3-5 条事实。
  必须包含文档中的精确数值、日期、名称。**没有关键事实表的页面会被查询系统忽略！**
- **概述**: 2-4句，说清楚"是什么 + 为什么重要 + 在本文档中的角色"
- **可回答的问题**: 列出 2-3 个该页面能精确回答的具体问题（用问句形式），帮助判断检索匹配
- **关键细节**: 提取具体事实——数字、日期、名称、判定标准、配置参数、步骤说明
- **关联关系**: 每个页面至少列出 2-4 个关联，用指定的关系关键词
- **来源上下文**: 原文摘录，便于人工核实

## 关键事实表撰写规范（★决定检索质量）
从文档原文中提取"属性 → 值"对。这些是用户查询时需要的精确答案。

正确示例:
  facts:
    审计日志保留期: 7年（亚太区企业客户）
    速率限制: 1000 req/s（Premium Partner）
    SOC 2 证据保留: 事件响应报告保留 3 年
    回滚审批人: 运维经理 + 部门总监双签
    GPU 配置建议: 7B→1×A100, 70B→4×A100

错误示例（太模糊，无法回答查询）:
  facts:
    保留期: 按规定执行
    速率: 有限制

规则:
- 每个属性必须能从文档中找到明确数值/名称/日期作为证据
- 优先提取: 数字、阈值、日期、人名、百分比、配置参数
- 如果文档提到多个值（如不同套餐），每个值单独一条
- 属性名用中文，值保留原文中的精确表述

## 关系关键词（每条关系必须用以下关键词之一开头）
关系关键词 -> 对应类型:
- 使用 [[X]] / 采用 [[X]] / 利用 [[X]] -> uses
- 依赖 [[X]] / 取决于 [[X]] -> depends_on
- 扩展 [[X]] / 基于 [[X]] -> extends
- 改进 [[X]] / 优化 [[X]] / 增强 [[X]] -> improves_upon
- 关联 [[X]] / 相关 [[X]] / 协作 [[X]] -> relates_to
- 属于 [[X]] / 组成部分 [[X]] -> part_of
- 负责 [[X]] / 实现 [[X]] / 执行 [[X]] -> implemented_by
- 导致 [[X]] / 引起 [[X]] -> caused_by
- 修复 [[X]] / 解决 [[X]] -> fixed_by
- 取代 [[X]] / 替换 [[X]] -> supersedes
- 矛盾 [[X]] / 冲突 [[X]] -> contradicts

## Output Format
用 ===PAGE_END=== 分隔每个页面。

每个页面必须包含 YAML frontmatter：
---
id: 实体ID或概念ID
type: {entity_type_str}
name: 中文名称
confidence: 0.85
source: source-name
aliases: [别名1, 别名2]
keywords: [关键词1, 关键词2]
---

然后按以下结构撰写（⚠️ 必须严格遵循此顺序！）：
# [中文标题]

## 关键事实
🔴 **必须输出！这是页面最重要的部分——用户查询时从这里获取精确答案。**
| 属性 | 值 |
|------|-----|
| 属性名1 | 精确值1 |
| 属性名2 | 精确值2 |
（至少 3-5 行，每行是一个可查询的精确事实。没有此节的页面将被视为无效！）

## 概述
[2-4 句中文描述：这是什么，为什么重要，在文档中的角色]

## 可回答的问题
- 问题1？（该页面能精确回答的具体问题）
- 问题2？
（2-3 个具体问句，帮助判断此页面是否匹配用户的查询意图）

## 关键细节
- [具体事实1：包含数字、日期或名称]
- [具体事实2]
- [具体事实3]
...

## 关联关系
- 关键词 [[目标实体]] — 关系说明
...

## 来源上下文
> [文档原文摘录，便于核实]

## 质量规则
- 🔴 **关键事实表是强制要求！没有此节的页面 = 无效页面。**
- 扫描文档的每个章节，不要遗漏后半部分内容
- 实体（entity/role/rule/process/event/tool/system/product）→ ID 带 {source_abbr} 前缀
- 概念（concept/technique/model/framework/benchmark/paper）→ ID 不带前缀
- 实体:概念比例约 65:35
- 每个页面至少 150 字实质性内容
- 每个页面至少 2-4 条关联关系
- 目标: 10-25 个高质量页面

## 实体类型参考
{entity_type_lines}"""
    else:
        system_prompt = f"""You are a wiki knowledge compiler. Your job is to read a document and write high-quality wiki pages.

## Entity vs Concept (CRITICAL — get this right!)
Karpathy's wiki design distinguishes two page types:
- **entity** (entity/role/rule/process/event/tool/system/product):
  Concrete instances in the document. A specific organization, person, rule, or process step.
  Think: "Can I point to this as one specific instance?" → entity. ~65% of pages.
- **concept** (concept/technique/model/framework/benchmark/paper):
  Abstract knowledge reusable across documents. Methodologies, patterns, evaluation criteria.
  Think: "Could this be discussed in multiple independent documents?" → concept. ~35% of pages.

**Default bias**: If unsure, prefer entity. Most document content is concrete, not abstract.

## Extraction Strategy (scan exhaustively!)
1. Scan EVERY section of the document — don't stop after the first few sections
2. First pass: extract all named entities (orgs, people, rules, processes, tools, systems)
3. Second pass: identify cross-cutting concepts (methods, patterns, frameworks)
4. For each extraction, ask: "Specific instance or general idea?" — this determines ID and placement

## Content Quality
- **Fact Table (🔴 REQUIRED — the ONLY source of precise answers for user queries!)**: 
  Extract structured queryable facts as a markdown table. At least 3-5 facts per page.
  Include exact numbers, dates, names from the source. **Pages without a Key Facts table will be ignored by the query system!**
- **Overview**: 2-4 substantive sentences: what it is + why it matters + role in this document
- **Questions This Page Answers**: List 2-3 specific questions this page can answer precisely (as interrogative sentences), helping match user queries
- **Key Details**: Extract specific facts — numbers, dates, names, criteria, parameters, steps
- **Relationships**: Minimum 2-4 per page, using the exact keywords below
- **Source Context**: Include verbatim excerpts for human verification

## Fact Table Guidelines (★ determines retrieval quality)
Extract "attribute → value" pairs from the document. These are the precise answers users will search for.

Good examples:
  facts:
    audit log retention: 7 years (APAC enterprise)
    rate limit: 1000 req/s (Premium tier)
    SOC 2 evidence retention: 3 years for incident reports
    model params: 671B total, 37B active per token
    GPU requirement: 8×A100 80GB for FP16 inference

Bad examples (too vague, can't answer queries):
  facts:
    retention: per policy
    limit: varies

Rules:
- Every attribute must have an explicit number/date/name from the document
- Prioritize: numbers, thresholds, dates, names, percentages, config params
- If the document mentions multiple values (e.g., different tiers), each gets its own fact
- For Chinese documents, use Chinese attribute names

## Relationship Keywords (every relationship MUST start with one of these)
- uses [[X]] / employs [[X]] → uses
- depends on [[X]] / requires [[X]] → depends_on
- extends [[X]] / based on [[X]] → extends
- improves [[X]] / enhances [[X]] → improves_upon
- relates to [[X]] / associated with [[X]] → relates_to
- part of [[X]] / component of [[X]] → part_of
- implemented by [[X]] / executed by [[X]] → implemented_by
- caused by [[X]] / triggered by [[X]] → caused_by
- fixed by [[X]] / resolved by [[X]] → fixed_by
- supersedes [[X]] / replaces [[X]] → supersedes
- contradicts [[X]] / conflicts with [[X]] → contradicts

## Output Format
Write pages separated by exactly this marker: ===PAGE_END===

Each page must start with YAML frontmatter:
---
id: entity-slug
type: {entity_type_str}
name: Display Name
confidence: 0.85
source: source-name
aliases: [alias1, alias2]
keywords: [keyword1, keyword2]
---

Then the page content (⚠️ MUST follow this exact order!):
# [Title]

## Key Facts
🔴 **REQUIRED! This is the most important section — users get precise answers from here.**
| Attribute | Value |
|-----------|-------|
| attribute1 | precise value1 |
| attribute2 | precise value2 |
(at least 3-5 rows, each a queryable precise fact. Pages without this section are INVALID!)

## Overview
[2-4 sentences: what it is, why it matters, role in this document]

## Questions This Page Answers
- Question 1? (a specific question this page can answer precisely)
- Question 2?
(2-3 specific interrogative sentences)

## Key Details
- [Specific fact 1: include numbers, dates, or names]
- [Specific fact 2]
- [Specific fact 3]
...

## Relationships
- keyword [[target-entity]] — explanation of the relationship
...

## Source Context
> [Verbatim excerpt from the document]

## Quality Rules
- 🔴 **Key Facts table is MANDATORY! Pages without it = INVALID.**
- Scan EVERY section — don't miss content in later parts of the document
- entity/role/rule/process/event/tool/system/product → lowercase-hyphenated IDs
- concept/technique/model/framework/benchmark/paper → lowercase-hyphenated IDs
- ~65% entity, ~35% concept ratio
- Minimum 150 words of substantive content per page
- At least 2-4 typed relationships per page
- Merge obvious variants: "DeepSeek-V3.2" and "DeepSeek-V3-2" → single page "deepseek-v3.2"
- Title Case names: "Muon Optimizer", "KV Cache"
- Target: 10-25 high-quality pages

## Entity Types
{entity_type_lines}"""

    if lang == "zh":
        user_prompt = f"""文档: {source_name}

内容:
{content}

请逐段扫描该文档，提取所有重要实体和概念，撰写 Wiki 页面。所有内容必须用中文。

## 提取步骤
1. 扫描每个章节标题，确保不遗漏任何部分
2. 提取所有具名实体（组织、角色、规则、流程、工具、系统）
3. 识别跨文档通用概念（方法论、技术模式、评估框架）
4. 为每个实体/概念建立关联关系链接

## 实体 ID 规则（重要！）
- entity/role/rule/process/event/tool/system/product → ID 必须带 {source_abbr} 前缀
- concept/technique/model/framework/benchmark/paper → ID 不带前缀

## 关注点
{focus_desc}。核心概念、组织结构、流程机制、评估标准、具体规则。

## 目标
10-25 个高质量中文页面，内容详实且相互关联，每个至少 2-4 条关系。
用 ===PAGE_END=== 分隔每个页面。"""
    else:
        user_prompt = f"""Document: {source_name}

Content:
{content}

Scan this document section by section and extract all important entities and concepts into wiki pages.

## Extraction Steps
1. Scan each section heading — ensure no content is missed
2. Extract all named entities (orgs, roles, rules, processes, tools, systems)
3. Identify cross-document concepts (methods, techniques, patterns, frameworks)
4. Establish typed relationships between every pair of related entities

## Focus Areas
{focus_desc}. Architecture innovations, model variants, techniques, benchmarks, key findings.

## Target
10-25 high-quality pages with substantive content, minimum 2-4 relationships each.
Output pages separated by ===PAGE_END==="""
    print("Calling LLM...", file=sys.stderr)
    response = call_llm(system_prompt, user_prompt)

    pages = response.split("===PAGE_END===")

    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)

    created_pages = []
    updated_pages = []
    contradictions_found = []

    # Derive source abbreviation for entity ID prefix
    import re as _re
    src_stem = Path(source_name).stem
    source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', src_stem)[:8].lower() or "doc"
    concept_types = CONCEPT_LIKE_TYPES
    # Track which entity IDs need concept pages (base name → list of instance IDs)
    concept_groups: dict[str, list[dict]] = {}
    _skipped: list[int] = [0]  # mutable counter for unchanged pages
    existing_source_pages = _get_source_pages(source_name)  # for incremental hash comparison

    for page_content in pages:
        page_content = page_content.strip()
        if not page_content or not page_content.startswith("---"):
            continue

        lines = page_content.split("\n")
        frontmatter_end = 0
        for i, line in enumerate(lines):
            if i > 0 and line.strip() == "---":
                frontmatter_end = i
                break

        if frontmatter_end == 0:
            continue

        frontmatter_text = "\n".join(lines[1:frontmatter_end])
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except Exception as e:
            print(f"  WARNING: YAML parse failed — {e}", file=sys.stderr)
            continue

        entity_id = frontmatter.get("id", "")
        entity_type = frontmatter.get("type", "concept")

        if not entity_id:
            continue

        # Determine target directory
        target_dir = CONCEPTS_DIR if entity_type in concept_types else ENTITIES_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        page_path = target_dir / f"{entity_id}.md"

        # ── 同名异实保护：如果已存在同名实体页（非 concept 类型），自动加前缀 ──
        # 即使 force 模式也检测——force 只允许覆盖同源页面，不能覆盖跨源实体
        if entity_type not in concept_types and page_path.exists():
            existing_content = page_path.read_text(encoding="utf-8")
            existing_source = ""
            for line in existing_content.split("\n"):
                if line.startswith("source:"):
                    existing_source = line.replace("source:", "").strip()
                    break
            # If existing page is from a DIFFERENT source, prefix the new one
            if existing_source and existing_source != source_name:
                prefixed_id = f"{source_abbr}-{entity_id}"
                page_path = ENTITIES_DIR / f"{prefixed_id}.md"
                frontmatter["id"] = prefixed_id
                page_lines = page_content.split("\n")
                fm_start = page_lines.index("---")
                fm_end = page_lines.index("---", fm_start + 1)
                new_fm = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip()
                page_content = "---\n" + new_fm + "\n---\n" + "\n".join(page_lines[fm_end + 1:])

                # Register for concept aggregation
                base_name = entity_id
                if base_name not in concept_groups:
                    concept_groups[base_name] = []
                concept_groups[base_name].append({"id": prefixed_id, "type": entity_type, "name": frontmatter.get("name", entity_id)})
                print(f"  Conflict → prefixed: {prefixed_id}.md", file=sys.stderr)

        if page_path.exists() and not force:
            existing_content = page_path.read_text(encoding="utf-8")
            contradictions = detect_contradictions(entity_id, page_content, existing_content)

            if contradictions:
                contradictions_found.extend(contradictions)
                resolutions = auto_resolve_contradictions(entity_id, contradictions)

                page_content = existing_content + "\n\n## Contradictions Detected\n\n"
                for c in contradictions:
                    ctype = c.get('contradiction_type', 'unknown')
                    sev = c.get('severity', 'medium')
                    existing = c.get('existing_claim', 'N/A')
                    new = c.get('new_claim', 'N/A')
                    page_content += f"- **{ctype}** ({sev}): {existing} → {new}\n"

                if resolutions:
                    page_content += "\n## Resolution\n\n"
                    for i, r in enumerate(resolutions):
                        winner = r.get("winner", "unknown")
                        conf = r.get("confidence", 0.5)
                        reasoning = r.get("reasoning", "")
                        action = r.get("action", "flag")
                        page_content += f"- **Resolved #{i+1}**: {winner} claim accepted ({action}) — confidence {conf:.0%}\n"
                        page_content += f"  - Reasoning: {reasoning}\n"
                        if action == "supersede":
                            page_content += "  - [SUPERSEDED] Old claim marked as superseded.\n"

                if not dry_run:
                    # Incremental: skip if content unchanged
                    new_hash = _content_hash(page_content)
                    old_hash = existing_source_pages.get(frontmatter.get("id", entity_id), {}).get("content_hash", "")
                    if new_hash == old_hash:
                        _skipped[0] += 1
                        print(f"  Unchanged: {Path(page_path).name}", file=sys.stderr)
                        continue
                    atomic_write(page_path, page_content)
                f_count, r_count = _count_facts(page_content)
                updated_pages.append({
                    "id": frontmatter.get("id", entity_id),
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                    "contradictions": len(contradictions),
                    "resolutions": len(resolutions),
                    "facts": f_count,
                    "relationships": r_count,
                })
                print(f"  Updated: {Path(page_path).name} ({len(contradictions)} contradictions, {len(resolutions)} resolved)", file=sys.stderr)
            else:
                if not dry_run:
                    # Incremental: skip if content unchanged
                    new_hash = _content_hash(page_content)
                    old_hash = existing_source_pages.get(frontmatter.get("id", entity_id), {}).get("content_hash", "")
                    if new_hash == old_hash:
                        _skipped[0] += 1
                        print(f"  Unchanged: {Path(page_path).name}", file=sys.stderr)
                        continue
                    atomic_write(page_path, page_content)
                f_count, r_count = _count_facts(page_content)
                updated_pages.append({
                    "id": frontmatter.get("id", entity_id),
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                    "facts": f_count,
                    "relationships": r_count,
                })
                print(f"  Updated: {Path(page_path).name} (reinforced)", file=sys.stderr)
        else:
            if not dry_run:
                atomic_write(page_path, page_content)
            f_count, r_count = _count_facts(page_content)
            created_pages.append({
                "id": frontmatter.get("id", entity_id),
                "type": entity_type,
                "name": frontmatter.get("name", entity_id),
                "path": str(page_path),
                "facts": f_count,
                "relationships": r_count,
            })
            print(f"  Created: {Path(page_path).name} ({entity_type})", file=sys.stderr)

    all_pages = created_pages + updated_pages
    if not all_pages:
        print("  WARNING: No pages parsed from LLM response! Raw output (500 chars):",
              file=sys.stderr)
        print(f"    {response[:500]}", file=sys.stderr)
        return {"source": source_name, "pages_created": 0, "pages_updated": 0, "pages": []}

    # ── Incremental: track unchanged pages ──
    new_page_ids: set[str] = {p["id"] for p in all_pages}
    skipped_pages = _skipped[0]
    pruned_pages: list[str] = []

    if dry_run:
        # ── Dry-run preview ──
        _print_dry_run_preview(source_name, all_pages, created_pages, updated_pages)
        return {
            "source": source_name,
            "pages_created": len(created_pages),
            "pages_updated": len(updated_pages),
            "pages_skipped": skipped_pages,
            "pages": all_pages,
            "dry_run": True,
        }

    # ── 概念聚合：为每个实体组创建/更新概念页（同名异实保护） ──
    for base_name, instances in concept_groups.items():
        concept_path = CONCEPTS_DIR / f"{base_name}.md"
        instance_links = "\n".join(
            f"- [[{inst['id']}]] — {inst.get('name', inst['id'])}（来源: {source_name}）"
            for inst in instances
        )
        # Also find existing non-prefixed entities with the same base name
        existing_entity = ENTITIES_DIR / f"{base_name}.md"
        if existing_entity.exists():
            existing_source = ""
            for line in existing_entity.read_text(encoding="utf-8").split("\n"):
                if line.startswith("source:"):
                    existing_source = line.replace("source:", "").strip()
                    break
            existing_link = f"- [[{base_name}]] — {base_name}（来源: {existing_source}）"
            if existing_link not in instance_links:
                instance_links = existing_link + "\n" + instance_links

        if concept_path.exists():
            existing = concept_path.read_text(encoding="utf-8")
            new_links = [li for li in instance_links.split("\n") if li not in existing]
            if new_links:
                # Append new instances
                updated_content = existing.rstrip() + "\n\n## 新增实例\n\n" + "\n".join(new_links) + "\n"
                if not dry_run:
                    atomic_write(concept_path, updated_content)
                print(f"  Concept updated: {base_name}.md (+{len(new_links)} instances)", file=sys.stderr)
        else:
            # Use LLM to synthesize a concept page from entity instances
            entity_summaries = []
            for inst in instances:
                ep_path = ENTITIES_DIR / f"{inst['id']}.md"
                if ep_path.exists():
                    ep_content = ep_path.read_text(encoding="utf-8")
                    overview_lines = []
                    capture = False
                    for line in ep_content.split("\n"):
                        if line.startswith("## 概述") or line.startswith("## Overview"):
                            capture = True
                            continue
                        if capture and line.startswith("## "):
                            break
                        if capture and line.strip():
                            overview_lines.append(line.strip())
                    entity_summaries.append(f"### {inst['name']}\n{' '.join(overview_lines[:3])}")

            synthesis_prompt = f"""综合以下实体实例，生成一个跨文档概念页。

概念: {base_name}
实例列表:
{instance_links}

实例详情:
{chr(10).join(entity_summaries[:3])}

输出（YAML frontmatter + 中文内容）：
---
id: {base_name}
type: concept
name: {base_name}
confidence: 0.85
source: 跨文档聚合
---

# {base_name}

## 概述
[综合所有实例，提炼通用模式和核心特征，2-4句中文]

## 已知实例
{instance_links}

## 关键特征
[从各实例提炼的共同点和差异性，3-5条中文]

直接输出，不要额外说明。"""
            try:
                concept_content = call_llm(
                    "你是 Wiki 知识聚合助手，综合多个来源的同类实体，生成概念页。",
                    synthesis_prompt,
                )
                if not dry_run:
                    atomic_write(concept_path, concept_content.strip())
                print(f"  Concept created: {base_name}.md ({len(instances)} instances)", file=sys.stderr)
            except Exception:
                _log_exc(f"concept synthesis failed for {base_name}")
                fallback = f"""---
id: {base_name}
type: concept
name: {base_name}
confidence: 0.80
source: 跨文档聚合
---

# {base_name}

## 概述
跨文档概念，聚合自 {source_name}。

## 已知实例
{instance_links}
"""
                if not dry_run:
                    atomic_write(concept_path, fallback)
                print(f"  Concept created (fallback): {base_name}.md", file=sys.stderr)

    # ── Prune stale pages (from this source but not in new compilation) ──
    pruned_pages = _prune_stale_pages(new_page_ids, source_name, dry_run=False)

    update_index(all_pages, source_name)
    update_log(source_name, len(created_pages), "compile")
    update_graph(all_pages, source_name)

    write_audit("compile", {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "pages_skipped": skipped_pages,
        "pages_pruned": len(pruned_pages),
        "contradictions": len(contradictions_found),
        "contradiction_details": contradictions_found[:10],
    })

    if skipped_pages > 0:
        print(f"  ⏭ Skipped: {skipped_pages} pages unchanged", file=sys.stderr)
    if pruned_pages:
        print(f"  🗑 Pruned: {len(pruned_pages)} stale pages", file=sys.stderr)

    return {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "pages_skipped": skipped_pages,
        "pages_pruned": len(pruned_pages),
        "pages": all_pages,
        "contradictions_found": contradictions_found,
    }

def _get_compile_workers() -> int:
    """Get max concurrent compile workers from config, env, or safe default.

    Resolution: CLI --jobs > env LLM_WIKI_COMPILE_WORKERS > config > default 1.
    Caps at 4 to avoid API rate limits unless explicitly overridden.
    """
    import os as _os
    env_val = _os.environ.get("LLM_WIKI_COMPILE_WORKERS", "").strip()
    if env_val:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass

    try:
        from config import get_config
        cfg = get_config()
        compile_cfg = cfg.get("compile", {}) if isinstance(cfg, dict) else {}
        cfg_workers = compile_cfg.get("max_workers", 1)
        if cfg_workers and int(cfg_workers) > 1:
            return min(int(cfg_workers), 8)  # config can go up to 8
    except Exception:
        pass

    return 1  # safe default: serial


def compile_path(
    source_path: str,
    source_type: str = "doc",
    force: bool = False,
    depth: int | None = None,
    dry_run: bool = False,
    mode: str = "llm",
) -> dict:
    """Compile a single source file or every supported file under a directory."""
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if (mode or "").lower() == "agent":
        return create_agent_compile_task(
            source_path,
            source_type=source_type,
            force=force,
            dry_run=dry_run,
            depth=depth,
        )

    if source_type == "auto":
        source_type = infer_source_type(path)

    if path.is_file():
        return compile_source(str(path), source_type=source_type, force=force, dry_run=dry_run)

    if depth is not None and depth < 0:
        raise ValueError("--depth must be >= 0")

    sources = iter_source_files(path, max_depth=depth)
    if not sources:
        return {
            "source": str(path),
            "directory": True,
            "files_found": 0,
            "compiled": [],
            "failed": [],
            "pages_created": 0,
            "pages_updated": 0,
        }

    compiled = []
    failed = []
    pages_created = 0
    pages_updated = 0

    # ── Concurrent workers (default 1 = serial, configurable) ──
    workers = _get_compile_workers()

    if workers > 1 and len(sources) > 1:
        print(
            f"Compiling directory {path} ({len(sources)} files, {workers} workers)...",
            file=sys.stderr,
        )
        print(
            "  WARNING: concurrent workers may cause data loss in index/graph/audit. "
            "Use --jobs 1 for safe compilation.",
            file=sys.stderr,
        )
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    compile_source, str(s), source_type=source_type,
                    force=force, dry_run=dry_run,
                ): s for s in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    result = future.result()
                    compiled.append(result)
                    pages_created += result.get("pages_created", 0)
                    pages_updated += result.get("pages_updated", 0)
                    name = Path(source).name
                    print(
                        f"  ✓ {name}: {result.get('pages_created', 0)} created, "
                        f"{result.get('pages_updated', 0)} updated",
                        file=sys.stderr,
                    )
                except Exception as e:
                    failed.append({"source": str(source), "error": str(e)})
                    print(f"  ✗ {Path(source).name}: {e}", file=sys.stderr)
                    traceback.print_exc()
    else:
        print(f"Compiling directory {path} ({len(sources)} files)...", file=sys.stderr)
        for source in sources:
            try:
                result = compile_source(str(source), source_type=source_type, force=force, dry_run=dry_run)
                compiled.append(result)
                pages_created += result.get("pages_created", 0)
                pages_updated += result.get("pages_updated", 0)
            except Exception as e:
                failed.append({"source": str(source), "error": str(e)})
                print(f"  ERROR: failed to compile {source}: {e}", file=sys.stderr)
                traceback.print_exc()

    return {
        "source": str(path),
        "directory": True,
        "files_found": len(sources),
        "compiled": compiled,
        "failed": failed,
        "pages_created": pages_created,
        "pages_updated": pages_updated,
        "workers": workers if workers > 1 else 1,
    }


def update_log(source_name: str, pages_count: int, operation: str = "compile"):
    """Update log.md with new operation."""
    log_file = WIKI_DIR / "log.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entry = f"\n## [{now}] {operation} | {source_name}\n- Pages created: {pages_count}\n"

    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
    else:
        content = "# Wiki Log\n\nChronological record of all wiki operations.\n"

    content += entry
    log_file.write_text(content, encoding="utf-8")


def update_graph(pages: list, source_name: str):
    graph_dir = WIKI_DIR / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    entities_file = graph_dir / "entities.json"
    edges_file = graph_dir / "edges.json"

    if entities_file.exists():
        entities = json.loads(entities_file.read_text(encoding="utf-8"))
    else:
        entities = {}

    if edges_file.exists():
        edges_data = json.loads(edges_file.read_text(encoding="utf-8"))
        edges = edges_data.get("edges", edges_data) if isinstance(edges_data, dict) else edges_data
    else:
        edges = []

    now = datetime.now(timezone.utc).isoformat()

    for page in pages:
        eid = page["id"]
        if eid not in entities:
            entities[eid] = {
                "id": eid,
                "type": page["type"],
                "name": page["name"],
                "sources": [source_name],
                "confidence": 0.85,
                "created": now,
                "last_confirmed": now,
                "reinforcement_count": 1,
            }
        else:
            if source_name not in entities[eid]["sources"]:
                entities[eid]["sources"].append(source_name)

            entities[eid]["reinforcement_count"] = entities[eid].get("reinforcement_count", 1) + 1
            entities[eid]["confidence"] = min(1.0, 0.85 + 0.05 * entities[eid]["reinforcement_count"])
            entities[eid]["last_confirmed"] = now

    for page in pages:
        page_path = Path(page.get("path", ""))
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            wikilinks = re.findall(r'\[\[([^\]|]+)', content)

            for target in wikilinks:
                target = target.strip().lower().replace(" ", "-")
                if target and target != page["id"]:
                    line_context = ""
                    for line in content.split("\n"):
                        line_lower = line.lower()
                        line_normalized = line_lower.replace('-', ' ')
                        if (f"[[{target}" in line_normalized or
                            f"[[{target.replace('-', ' ')}" in line_normalized):
                            line_context = line
                            break

                    edge_type = extract_edge_type(line_context) if line_context else "relates_to"

                    edge = {
                        "source": page["id"],
                        "target": target,
                        "type": edge_type,
                        "weight": 1.0,
                        "source_file": source_name,
                    }

                    existing = [e for e in edges if e["source"] == page["id"] and e["target"] == target]
                    if not existing:
                        edges.append(edge)

    entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")
    edges_file.write_text(json.dumps({"edges": edges}, indent=2, ensure_ascii=False), encoding="utf-8")


def update_index(pages: list, source_name: str):
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)

    grouped = {
        "concept": {},
        "technique": {},
        "model": {},
        "framework": {},
        "benchmark": {},
        "paper": {},
    }

    # Merge existing index entries
    if INDEX_FILE.exists():
        for line in INDEX_FILE.read_text(encoding="utf-8").split("\n"):
            match = re.match(r'- \[\[([^\]|]+)(?:\|[^\]]+)?\]\] — (.+)', line)
            if match:
                eid, ptype = match.group(1), match.group(2)
                if ptype in grouped:
                    grouped[ptype][eid] = True

    for p in pages:
        ptype = p.get("type", "concept")
        if ptype in grouped:
            grouped[ptype][p.get("id", "")] = True

    lines = [
        "# Wiki Index",
        "",
        f"> Last compiled: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
        f"> Source: {source_name}",
        "",
    ]

    type_labels = {
        "concept": "Concepts",
        "technique": "Techniques",
        "model": "Models",
        "framework": "Frameworks",
        "benchmark": "Benchmarks",
        "paper": "Papers",
    }

    for ptype, label in type_labels.items():
        items = grouped[ptype]
        if items:
            lines.extend(["", f"## {label}", ""])
            for eid in sorted(items):
                name = eid.replace("-", " ").title()
                lines.append(f"- [[{eid}|{name}]] — {ptype}")

    atomic_write(INDEX_FILE, "\n".join(lines))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Wiki compilation')
    parser.add_argument('source', help='Source file or directory to compile')
    parser.add_argument('--type', dest='source_type', default='doc',
                        choices=['auto', 'doc', 'article', 'code', 'conversation'],
                        help='Source type; "auto" infers from file extension (Agent mode recommended)')
    parser.add_argument('--mode', choices=['agent', 'llm'], default=None,
                        help='Compile mode; defaults to configured mode or agent')
    parser.add_argument('--force', action='store_true', help='Force re-compile (overwrite existing pages)')
    parser.add_argument('--dry-run', action='store_true', help='Preview LLM output without writing any files')
    parser.add_argument('--depth', type=int, default=None,
                        help='Directory recursion depth: 0 = direct files only, omit = all subdirectories')
    parser.add_argument('-j', '--jobs', type=int, default=None,
                        help='Max concurrent LLM calls (default: 1, cap: 4)')
    args = parser.parse_args()

    if args.jobs is not None:
        import os as _os
        _os.environ["LLM_WIKI_COMPILE_WORKERS"] = str(max(1, args.jobs))
    config_mode = get_config().get("compile", {}).get("mode", "agent")
    mode = args.mode or config_mode or "agent"
    result = compile_path(
        args.source,
        source_type=args.source_type,
        force=args.force,
        depth=args.depth,
        dry_run=args.dry_run,
        mode=mode,
    )

    pages_created = result.get('pages_created', 0)
    pages_updated = result.get('pages_updated', 0)
    if result.get("mode") == "agent":
        print(f"\nAgent compile task created for {result['source']}")
        print(f"  → {result['agent_task']}")
        print("  → No configured LLM was called. The Agent should execute this task.")
        if not result.get("readable", True):
            print("  → Source text was not extracted; Agent must inspect it or ask for readable content.")
        return
    if result.get("directory"):
        failed = len(result.get("failed", []))
        prefix = "[Dry-run] " if args.dry_run else ""
        print(
            f"\n{prefix}Compiled {result['source']}: {len(result.get('compiled', []))}/"
            f"{result.get('files_found', 0)} files, {pages_created} pages created, "
            f"{pages_updated} pages updated, {failed} failed"
        )
    else:
        if result.get("dry_run"):
            print(f"\n[Dry-run] {result['source']}: {pages_created} pages would be created, {pages_updated} pages would be updated")
        else:
            print(f"\nCompiled {result['source']}: {pages_created} pages created, {pages_updated} pages updated")
    if not result.get("dry_run"):
        print("  → Updated log.md and graph/entities.json")


if __name__ == "__main__":
    main()
