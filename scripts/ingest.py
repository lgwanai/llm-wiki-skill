#!/usr/bin/env python3
"""ingest.py — Source Ingestion & LLM Entity Extraction for llm-wiki."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WIKI_DIR = ".wiki"
GRAPH_DIR = os.path.join(WIKI_DIR, "graph")
PAGES_DIR = os.path.join(WIKI_DIR, "pages")
SOURCE_DIR = os.path.join(WIKI_DIR, "source")
AUDIT_FILE = os.path.join(WIKI_DIR, "audit", "trail.jsonl")
LOG_FILE = os.path.join(WIKI_DIR, "log.md")
INDEX_FILE = os.path.join(PAGES_DIR, "index.md")

ENTITIES_FILE = os.path.join(GRAPH_DIR, "entities.json")
EDGES_FILE = os.path.join(GRAPH_DIR, "edges.json")
EMBEDDINGS_FILE = os.path.join(GRAPH_DIR, "embeddings.json")

TEXT_EXTENSIONS = {
    '.md', '.txt', '.rst', '.adoc', '.org', '.tex', '.log',
    '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java',
    '.c', '.cpp', '.h', '.hpp', '.rb', '.php', '.swift', '.kt',
    '.sh', '.bash', '.zsh', '.fish',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.xml', '.svg', '.sql', '.graphql',
    '.css', '.scss', '.less', '.html', '.htm',
    '.env', '.dockerfile', '.makefile',
}

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp'}

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r'sk-[a-zA-Z0-9]{32,}', '[REDACTED: API key]'),
    (r'ghp_[a-zA-Z0-9]{36}', '[REDACTED: GitHub token]'),
    (
        r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',  # noqa: E501
        '[REDACTED: Private key]',
    ),
    (r'password\s*[=:]\s*[^\s"\']+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]


def _load_json(path: str) -> dict | list:
    if not os.path.exists(path):
        return {} if 'entities' in path else {'edges': []}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return {} if 'entities' in path else {'edges': []}


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _save_source_markdown(content: str, source_name: str, output_path: str | None = None) -> str:
    source_slug = _slugify(source_name)

    ext = os.path.splitext(source_name)[1].lower()
    if ext in IMAGE_EXTENSIONS or ext == '.pdf':
        subdir = 'documents'
    elif ext in {'.docx', '.pptx', '.xlsx', '.epub', '.html', '.htm'}:
        subdir = 'documents'
    elif ext in {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.c', '.cpp', '.rb'}:
        subdir = 'code'
    elif ext in {'.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf'}:
        subdir = 'code'
    else:
        subdir = 'misc'

    if output_path:
        target_path = output_path
    else:
        target_path = os.path.join(SOURCE_DIR, subdir, f"{source_slug}.md")

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    header = f"""---
source: {source_name}
converted_at: {_now()}
type: source
---

"""

    with open(target_path, 'w', encoding='utf-8') as f:
        f.write(header + content)

    return target_path


def convert_only(source_path: str, output_path: str | None = None, use_ocr: bool = False) -> dict:
    """Convert source to Markdown and save to .wiki/source/ without entity extraction."""
    if source_path == '-':
        content = sys.stdin.read()
        source_name = 'stdin'
    else:
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")
        content = _parse_file(source_path, use_ocr=use_ocr)
        source_name = os.path.basename(source_path)

    saved_path = _save_source_markdown(content, source_name, output_path)

    _log_audit('convert', {
        'source': source_name,
        'output': saved_path,
        'ocr': use_ocr,
    })

    return {
        'source': source_name,
        'output': saved_path,
        'content_length': len(content),
    }


def copy_source(source_path: str, output_path: str | None = None) -> dict:
    """Copy code/text file to source directory with metadata header."""
    if source_path == '-':
        content = sys.stdin.read()
        source_name = 'stdin'
    else:
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")
        with open(source_path, encoding='utf-8', errors='replace') as f:
            content = f.read()
        source_name = os.path.basename(source_path)

    saved_path = _save_source_markdown(content, source_name, output_path)

    _log_audit('copy', {
        'source': source_name,
        'output': saved_path,
    })

    return {
        'source': source_name,
        'output': saved_path,
        'content_length': len(content),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-').replace('_', '-'))


def _log_audit(op: str, details: dict) -> None:
    os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
    entry = {"op": op, **details, "ts": _now()}
    with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _parse_with_markitdown(filepath: str) -> str:
    """Convert supported formats (DOCX, PPTX, XLSX, HTML, EPUB, CSV, etc.) to Markdown."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise RuntimeError("markitdown not installed. Run: pip install markitdown")

    md = MarkItDown(enable_plugins=False)
    result = md.convert(filepath)
    return result.text_content


def _parse_with_ocr(filepath: str) -> str:
    """Parse images and PDFs using the remote DeepSeek-OCR API."""
    try:
        from _deepseek_ocr import DeepSeekOCR
    except ImportError:
        raise RuntimeError("_deepseek_ocr module not found in scripts/")

    ocr = DeepSeekOCR.from_config()
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return ocr._ocr_pdf_text(filepath) or ""
    return ocr.ocr_image(filepath) or ""


def _parse_file(filepath: str, use_ocr: bool = False) -> str:
    """Detect file type and parse to plain text."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext in TEXT_EXTENSIONS:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            return f.read()

    if ext in IMAGE_EXTENSIONS or ext == ".pdf":
        if use_ocr:
            return _parse_with_ocr(filepath)
        raise RuntimeError(
            f"Image/PDF file '{filepath}' requires --ocr flag."
        )

    return _parse_with_markitdown(filepath)


def filter_sensitive(content: str) -> tuple[str, list[dict]]:
    """Strip sensitive data. Returns (filtered_content, filter_log)."""
    log = []
    for pattern, replacement in SENSITIVE_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
        if matches:
            log.append({"pattern": pattern[:40], "count": len(matches)})
            content = re.sub(pattern, replacement, content, flags=re.IGNORECASE | re.DOTALL)
    return content, log


def _load_schema_dir_map() -> dict[str, str]:
    """Parse entity type → directory mapping from schema.md."""
    schema_path = Path(WIKI_DIR) / "schema.md"
    if not schema_path.exists():
        return {}
    text = schema_path.read_text(encoding="utf-8")
    dir_map = {}
    in_table = False
    for line in text.split("\n"):
        if "## Entity Types" in line:
            in_table = True
            continue
        if in_table and line.startswith("## ") and "Entity" not in line:
            break
        if in_table and line.startswith("| `"):
            parts = [p.strip("` ") for p in line.split("|")[1:-1]]
            if len(parts) >= 3:
                dir_map[parts[0]] = parts[1]
    return dir_map


ENTITY_TYPE_DIRS = _load_schema_dir_map()


def _llm_extract(text: str, source_name: str = "") -> dict:
    """Extract entities and relationships using configured LLM."""
    try:
        from _llm_extract import LLMExtractor
    except ImportError:
        raise RuntimeError("_llm_extract module not found in scripts/")

    extractor = LLMExtractor.from_config()
    print(f"  Extracting entities via {extractor.model} ...", file=sys.stderr)
    return extractor.extract(text, source_name)


def _create_entity_page(entity: dict, source_name: str, source_content: str = "") -> Path:
    """Create a rich wiki entity page in pages/entities/.

    Includes YAML frontmatter, synthesized overview from source,
    key details, and source attribution.
    """
    page_dir = Path(WIKI_DIR) / "pages" / "entities"
    page_dir.mkdir(parents=True, exist_ok=True)
    page_path = page_dir / f"{entity['id']}.md"

    etype = entity.get("type", "concept")
    ename = entity.get("name", entity["id"])
    description = entity.get("description", "")
    confidence = entity.get("confidence", 0.7)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build frontmatter
    fm_lines = [
        "---",
        f'id: {entity["id"]}',
        f'type: {etype}',
        f'name: "{ename}"',
        "status: active",
        f"confidence: {confidence}",
        f"last_confirmed: {now}",
        "sources:",
        f"  - {_slugify(source_name)}",
        "reinforcements: 0",
        "contradictions: []",
        "tags: []",
    ]
    if description:
        fm_lines.append(f'description: "{description}"')
    fm_lines.append("---")

    # Build body with rich content
    body_lines = [
        "",
        f"# {ename}",
        "",
        "## Overview",
        "",
    ]
    if description:
        body_lines.append(description)
        body_lines.append("")
    else:
        body_lines.append(f"A {etype} entity discovered in source: {source_name}.")
        body_lines.append("")

    # Extract relevant context from source if available
    if source_content:
        excerpts = _extract_relevant_excerpts(ename, source_content[:50000])
        if excerpts:
            body_lines.append("## Source Context")
            body_lines.append("")
            for excerpt in excerpts[:3]:
                body_lines.append(f"> {excerpt}")
                body_lines.append("")
    else:
        body_lines.append("## Source Context")
        body_lines.append("")
        body_lines.append(f"_Source: {source_name} — run compile to regenerate with source content_")
        body_lines.append("")

    body_lines.append("## Relationships")
    body_lines.append("")
    body_lines.append("_No relationships defined yet. Run lint or graph build to auto-detect._")
    body_lines.append("")

    body_lines.append("## History")
    body_lines.append("")
    body_lines.append(f"- **{now}**: Entity created from source `{source_name}` (confidence: {confidence})")
    body_lines.append("")

    page_path.write_text("\n".join(fm_lines + body_lines), encoding="utf-8")
    return page_path


def _extract_relevant_excerpts(entity_name: str, text: str, max_excerpts: int = 3) -> list[str]:
    """Find sentences in source text that mention the entity name."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    excerpts = []
    name_lower = entity_name.lower().replace("-", " ")
    for s in sentences:
        if name_lower in s.lower() and len(s) > 15:
            excerpts.append(s.strip()[:200])
        if len(excerpts) >= max_excerpts:
            break

    # Fallback: grab surrounding context around first mention
    if not excerpts:
        idx = text.lower().find(name_lower)
        if idx >= 0:
            start = max(0, idx - 100)
            end = min(len(text), idx + 200)
            excerpts.append(text[start:end].strip().replace("\n", " "))

    return excerpts


def _generate_concept_pages(entities: list[dict], source_text: str, source_name: str) -> int:
    """Use LLM to generate rich markdown concept pages for concept-type entities."""
    concept_entities = [(e["id"], e["name"]) for e in entities if e.get("type") == "concept"]
    if not concept_entities:
        return 0

    try:
        from _llm_extract import LLMExtractor
        extractor = LLMExtractor.from_config()
    except ImportError:
        return 0

    concepts_dir = Path(PAGES_DIR) / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    prompt = """You are a technical writer. Write a detailed wiki page for each concept based on the source document.
For each, provide sections: ## Overview, ## How it works, ## Why it matters, ## Key relationships
Format each as: ### [slug]: [name]
[content with ## subheadings]

Source document:
"""
    # Use first 60K chars for context
    context = source_text[:60000]
    concept_list = "\n".join(f"{cid}: {cname}" for cid, cname in concept_entities)
    full_prompt = prompt + context + "\n\nConcepts to document:\n" + concept_list

    response = extractor._call(
        "You are a technical wiki writer. Write clear, detailed pages. Use ## for sections.",
        full_prompt,
    )

    sections = re.split(r"###\s+", response)
    count = 0
    for sec in sections[1:]:
        parts = sec.strip().split("\n", 1)
        if len(parts) < 2:
            continue
        header = parts[0].strip()
        content = parts[1].strip()
        if ":" in header:
            slug, name = header.split(":", 1)
            slug = slug.strip()
            name = name.strip()
        else:
            continue

        fm = f"""---
id: {slug}
type: concept
name: "{name}"
status: active
confidence: 0.85
sources:
  - .wiki/source/{_slugify(source_name)}
---

# {name}

{content}
"""
        (concepts_dir / f"{slug}.md").write_text(fm, encoding="utf-8")
        count += 1

    print(f"  Generated {count} concept pages in concepts/", file=sys.stderr)
    return count


def _update_log(op: str, source_name: str, entity_count: int, edge_count: int) -> None:
    """Append an entry to log.md (chronological append-only)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [{today}] {op} | {source_name}\n"
    entry += f"- Entities extracted: {entity_count}\n"
    entry += f"- Edges created: {edge_count}\n\n"

    mode = "a" if os.path.exists(LOG_FILE) else "w"
    with open(LOG_FILE, mode, encoding="utf-8") as f:
        if mode == "w":
            f.write("# Wiki Log\n\nChronological record of all wiki operations.\n")
        f.write(entry)


def _extract_summary(content: str, max_len: int = 120) -> str:
    """Extract a one-line summary from markdown content (first non-heading, non-empty line after frontmatter)."""
    # Strip YAML frontmatter
    body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL).strip()
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            summary = line[:max_len]
            return summary + "..." if len(line) > max_len else summary
    return ""


def _load_page_fm(page_path: Path) -> dict:
    """Extract YAML frontmatter from a markdown page."""
    try:
        content = page_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"\'')
    return fm


def _embed_entities(registry: dict) -> int:
    """Generate vector embeddings for entity names/descriptions via Ollama.

    Embeddings are saved to graph/embeddings.json for vector search.
    Returns number of new embeddings generated.
    """
    embeddings_path = Path(GRAPH_DIR) / "embeddings.json"
    try:
        from _ollama import get_embedding
    except ImportError:
        print("  Warning: _ollama module not found, skipping embeddings", file=sys.stderr)
        return 0

    try:
        if embeddings_path.exists():
            embeddings_data = json.loads(embeddings_path.read_text(encoding="utf-8"))
        else:
            embeddings_data = {}
    except (json.JSONDecodeError, OSError):
        embeddings_data = {}

    if not isinstance(embeddings_data, dict):
        embeddings_data = {}

    count = 0
    for eid, entity in registry.items():
        if eid in embeddings_data:
            continue
        name = entity.get("name", eid)
        desc = entity.get("description", "")
        text = f"{name}: {desc}" if desc else name
        emb = get_embedding(text)
        if emb:
            embeddings_data[eid] = emb
            count += 1

    if count > 0:
        embeddings_path.parent.mkdir(parents=True, exist_ok=True)
        embeddings_path.write_text(
            json.dumps(embeddings_data, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"  Generated {count} new embeddings", file=sys.stderr)
    return count


def _rebuild_index() -> None:
    """Rebuild index.md — catalog of all wiki pages with one-line summaries."""
    pages_dir = Path(PAGES_DIR)
    concepts_dir = pages_dir / "concepts"
    entities_dir = pages_dir / "entities"
    sessions_dir = pages_dir / "sessions"
    decisions_dir = pages_dir / "decisions"
    patterns_dir = pages_dir / "patterns"

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Wiki Index",
        "",
        f"> Auto-generated at {now_utc}. Updated on every ingest or compile.",
        "",
    ]

    # --- Concepts ---
    if concepts_dir.exists():
        lines.append("## Concepts")
        lines.append("")
        for f in sorted(concepts_dir.glob("*.md")):
            name = f.stem.replace("-", " ").title()
            fm = _load_page_fm(f)
            summary = fm.get("description", _extract_summary(f.read_text(encoding="utf-8")))
            line = f"- [[{f.stem}|{name}]]"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        lines.append("")

    # --- Entities ---
    if entities_dir.exists():
        lines.append("## Entities")
        lines.append("")
        for f in sorted(entities_dir.glob("*.md")):
            name = f.stem.replace("-", " ").title()
            fm = _load_page_fm(f)
            summary = fm.get("description", _extract_summary(f.read_text(encoding="utf-8")))
            line = f"- [[{f.stem}|{name}]]"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        lines.append("")

    # --- Sessions ---
    if sessions_dir.exists():
        lines.append("## Sessions")
        lines.append("")
        for f in sorted(sessions_dir.glob("*.md")):
            fm = _load_page_fm(f)
            topic = fm.get("topic", f.stem.replace("-", " ").title())
            date = fm.get("date", "")
            line = f"- [[{f.stem}|{topic}]]"
            if date:
                line += f" — {date}"
            lines.append(line)
        lines.append("")

    # --- Decisions ---
    if decisions_dir.exists():
        lines.append("## Decisions")
        lines.append("")
        for f in sorted(decisions_dir.glob("*.md")):
            name = f.stem.replace("-", " ").title()
            fm = _load_page_fm(f)
            summary = fm.get("title", _extract_summary(f.read_text(encoding="utf-8")))
            line = f"- [[{f.stem}|{name}]]"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        lines.append("")

    # --- Patterns ---
    if patterns_dir.exists():
        lines.append("## Patterns")
        lines.append("")
        for f in sorted(patterns_dir.glob("*.md")):
            name = f.stem.replace("-", " ").title()
            fm = _load_page_fm(f)
            summary = fm.get("category", _extract_summary(f.read_text(encoding="utf-8")))
            line = f"- [[{f.stem}|{name}]]"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        lines.append("")

    # --- Sources ---
    lines.append("## Sources")
    lines.append("")
    sources_dir = Path(SOURCE_DIR)
    if sources_dir.exists():
        for f in sorted(sources_dir.rglob("*.md")):
            rel = f.relative_to(Path(WIKI_DIR))
            fm = _load_page_fm(f)
            src_type = fm.get("type", "source")
            src_name = fm.get("source", f.stem)
            line = f"- [{src_name}]({rel}) — type: {src_type}"
            lines.append(line)
    lines.append("")

    Path(INDEX_FILE).write_text("\n".join(lines), encoding="utf-8")


def ingest_source(
    source_path: str,
    source_type: str = "article",
    embed: bool = False,
    use_ocr: bool = False,
) -> dict:
    """Ingest a source file: parse, LLM-extract entities, build graph, create pages."""
    if source_path == '-':
        content = sys.stdin.read()
        source_name = 'stdin'
    else:
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")
        content = _parse_file(source_path, use_ocr=use_ocr)
        source_name = os.path.basename(source_path)

    filtered_content, filter_log = filter_sensitive(content)
    if filter_log:
        for item in filter_log:
            _log_audit('filter', {'source': source_name, **item})

    extraction = _llm_extract(filtered_content, source_name)
    entities = extraction.get("entities", [])
    relationships = extraction.get("relationships", [])
    main_entity = extraction.get("main_entity", "")

    print(f"  LLM extracted: {len(entities)} entities, {len(relationships)} relationships",
          file=sys.stderr)

    registry = _load_json(ENTITIES_FILE)
    if isinstance(registry, list):
        registry = {}
    new_count = 0

    for entity in entities:
        eid = entity["id"]
        entity_page = f"pages/entities/{eid}.md"

        if eid in registry:
            existing = registry[eid]
            existing['confidence'] = min(1.0, existing.get('confidence', 0.5) + 0.05)
            existing.setdefault('sources', []).append(_slugify(source_name))
        else:
            registry[eid] = {
                'id': eid,
                'type': entity['type'],
                'name': entity['name'],
                'description': entity.get('description', ''),
                'confidence': entity.get('confidence', 0.7),
                'sources': [_slugify(source_name)],
                'page': entity_page,
            }
            new_count += 1
            _create_entity_page(entity, source_name, filtered_content)

    _save_json(ENTITIES_FILE, registry)
    print(f"  Saved {new_count} new entities to graph", file=sys.stderr)

    _generate_concept_pages(entities, filtered_content, source_name)

    # Update edges
    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []
    new_edges = []

    for rel in relationships:
        source = rel.get("source", "")
        target = rel.get("target", "")
        if source not in registry or target not in registry:
            continue
        new_edges.append({
            'source': source,
            'target': target,
            'type': rel.get('type', 'related_to'),
            'confidence': 0.8,
            'description': rel.get('description', f'{source} {rel.get("type", "related_to")} {target}'),
        })

    all_edges.extend(new_edges)
    _save_json(EDGES_FILE, {'edges': all_edges})
    print(f"  Added {len(new_edges)} edges to graph", file=sys.stderr)

    _log_audit('ingest', {
        'source': source_name,
        'source_type': source_type,
        'entities': [e['id'] for e in entities],
        'edges': len(new_edges),
        'main_entity': main_entity,
        'filter_count': sum(item['count'] for item in filter_log),
    })

    embedded = 0
    if embed:
        embedded = _embed_entities(registry)

    _update_log("ingest", source_name, new_count, len(new_edges))
    _rebuild_index()
    print(
        "  Updated log.md and index.md", file=sys.stderr
    )

    return {
        'source': source_name,
        'main_entity': main_entity,
        'entities_found': len(entities),
        'entities_new': new_count,
        'edges_created': len(new_edges),
        'filtered_items': sum(item['count'] for item in filter_log),
        'embeddings_created': embedded,
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Source Ingestion')
    parser.add_argument('source', nargs='?', help='Source file path (use - for stdin)')
    parser.add_argument('--type', dest='source_type', default='article',
                        choices=['article', 'code', 'conversation', 'doc'],
                        help='Source type')
    parser.add_argument('--stdin', action='store_true', help='Read from stdin')
    parser.add_argument('--batch', help='Process all files in a directory')
    parser.add_argument('--embed', action='store_true',
                        help='Generate Ollama vector embeddings for new entities')
    parser.add_argument('--ocr', action='store_true',
                        help='Enable OCR for image/PDF files via remote DeepSeek-OCR API')
    parser.add_argument('--convert-only', action='store_true',
                        help='Only convert to Markdown, save to .wiki/source/')
    parser.add_argument('--copy', action='store_true',
                        help='Copy text file to .wiki/source/ with metadata header')
    parser.add_argument('--output', '-o',
                        help='Output file path (default: auto-detect)')
    args = parser.parse_args()

    if args.batch:
        if not os.path.isdir(args.batch):
            print(f"Error: not a directory: {args.batch}", file=sys.stderr)
            sys.exit(1)
        results = []
        for filename in sorted(os.listdir(args.batch)):
            filepath = os.path.join(args.batch, filename)
            if os.path.isfile(filepath):
                try:
                    if args.convert_only:
                        r = convert_only(filepath, use_ocr=args.ocr)
                    elif args.copy:
                        r = copy_source(filepath)
                    else:
                        r = ingest_source(
                            filepath, args.source_type,
                            embed=args.embed, use_ocr=args.ocr,
                        )
                    results.append(r)
                except Exception as e:
                    print(f"Error processing {filename}: {e}", file=sys.stderr)
        print(json.dumps({'batch_results': results}, indent=2, ensure_ascii=False))
        return

    source = '-' if args.stdin else args.source
    if not source:
        parser.print_help()
        sys.exit(1)

    try:
        if args.convert_only:
            result = convert_only(source, output_path=args.output, use_ocr=args.ocr)
        elif args.copy:
            result = copy_source(source, output_path=args.output)
        else:
            result = ingest_source(source, args.source_type, embed=args.embed, use_ocr=args.ocr)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
