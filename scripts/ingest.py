#!/usr/bin/env python3
"""ingest.py — Source Ingestion & Entity Extraction for llm-wiki."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

WIKI_DIR = ".wiki"
GRAPH_DIR = os.path.join(WIKI_DIR, "graph")
PAGES_DIR = os.path.join(WIKI_DIR, "pages")
AUDIT_FILE = os.path.join(WIKI_DIR, "audit", "trail.jsonl")

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
    (r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     '[REDACTED: Private key]'),
    (r'password\s*[=:]\s*[^\s"\']+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]


def _load_json(path: str) -> dict | list:
    if not os.path.exists(path):
        return {} if 'entities' in path else {'edges': []}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return {} if 'entities' in path else {'edges': []}


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


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
    """Convert any supported file to Markdown using Microsoft's MarkItDown.

    Supports: PDF, DOCX, PPTX, XLSX, HTML, EPUB, CSV, JSON, XML, ZIP, and more.
    Does NOT use built-in OCR — images are handled separately by _parse_image_with_ocr.
    """
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise RuntimeError(
            "markitdown not installed. Run: pip install markitdown"
        )

    md = MarkItDown(enable_plugins=False)
    result = md.convert(filepath)
    return result.text_content


def _parse_image_with_ocr(filepath: str, lang: str = "eng") -> str:
    """Extract text from image using Tesseract OCR.

    Requires system-level Tesseract installation:
      macOS:  brew install tesseract tesseract-lang
      Linux:  apt install tesseract-ocr tesseract-ocr-eng
    Python deps: pip install pytesseract Pillow
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "pytesseract or Pillow not installed. Run: pip install pytesseract Pillow"
        )

    try:
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip()
    except Exception as e:
        raise RuntimeError(f"OCR failed for {filepath}: {e}")


def _parse_file(filepath: str, use_ocr: bool = False) -> str:
    """Detect file type and parse to plain text.

    Dispatch logic:
    - Text files (.md, .py, .json, ...) → open().read() (fast, no deps)
    - Image files (.png, .jpg, ...) → OCR if use_ocr=True, else raise
    - Everything else (.pdf, .docx, ...) → MarkItDown
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext in TEXT_EXTENSIONS:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    if ext in IMAGE_EXTENSIONS:
        if use_ocr:
            return _parse_image_with_ocr(filepath)
        raise RuntimeError(
            f"Image file '{filepath}' requires --ocr flag for OCR processing.\n"
            f"Install: pip install pytesseract Pillow\n"
            f"System:   brew install tesseract (macOS) / apt install tesseract-ocr (Linux)"
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


def _extract_entities(text: str, source_type: str) -> list[dict]:
    """Simple heuristic entity extraction from text."""
    entities = []
    seen: set = set()

    # Extract project names (CapitalizedWord patterns, from quotes)
    for match in re.finditer(r'"([^"]+)"', text):
        name = match.group(1).strip()
        slug = _slugify(name)
        if slug and slug not in seen and len(name.split()) <= 4:
            seen.add(slug)
            entities.append({
                'id': slug, 'type': 'project', 'name': name,
                'confidence': 0.6, 'source_type': source_type,
            })

    # Extract file paths
    for match in re.finditer(r'([\w./-]+\.(?:py|js|ts|tsx|json|yaml|yml|md|toml|cfg|ini))', text):
        path = match.group(1)
        slug = _slugify(os.path.basename(path))
        if slug and slug not in seen:
            seen.add(slug)
            entities.append({
                'id': slug, 'type': 'file', 'name': path,
                'attributes': {'path': path}, 'confidence': 0.7,
            })

    # Extract library names from import-like patterns
    for match in re.finditer(r'(?:import|from|require|pip install|npm install)\s+([\w.-]+)', text):
        lib = match.group(1)
        slug = _slugify(lib)
        if slug and slug not in seen:
            seen.add(slug)
            entities.append({
                'id': slug, 'type': 'library', 'name': lib,
                'confidence': 0.5, 'source_type': source_type,
            })

    return entities


def _extract_edges(text: str, source_entity_id: str, entities: list[dict]) -> list[dict]:
    """Extract simple edges based on entity mentions near each other."""
    edges = []
    edge_id = 1

    for entity in entities:
        eid = entity['id']
        if eid == source_entity_id:
            continue
        # Check if entity is mentioned with "uses", "depends on", "contains" context
        if re.search(rf'{re.escape(entity["name"])}\s*(?:uses|depends\s*on|requires|contains)', text, re.IGNORECASE):
            rel_type = 'uses'
            if 'depends' in text.lower():
                rel_type = 'depends_on'
            elif 'contains' in text.lower():
                rel_type = 'contains'
            edges.append({
                'id': f'edge-ingest-{edge_id:04d}',
                'source': source_entity_id, 'target': eid,
                'type': rel_type, 'confidence': entity.get('confidence', 0.5),
                'sources': [source_entity_id],
                'description': f'{source_entity_id} {rel_type} {eid}',
                'created_at': _now(),
            })
            edge_id += 1

    return edges


def _embed_entities(registry: dict) -> int:
    """Generate Ollama embeddings for new/modified entities. Returns count of embeddings created."""
    try:
        from _ollama import get_embedding
    except ImportError:
        print("Warning: _ollama module not available — skipping embeddings", file=sys.stderr)
        return 0

    embeddings = _load_json(EMBEDDINGS_FILE)
    if not isinstance(embeddings, dict):
        embeddings = {}

    count = 0
    for eid, entity in registry.items():
        if eid in embeddings:
            continue
        meta = entity.get('attributes', {})
        text_parts = [
            entity.get('name', eid),
            entity.get('type', ''),
            str(meta.get('version', '')),
            str(meta.get('purpose', '')),
            str(meta.get('path', '')),
        ]
        text = ' '.join(filter(None, text_parts))
        if len(text) < 3:
            continue
        emb = get_embedding(text)
        if emb is not None:
            embeddings[eid] = emb
            count += 1

    _save_json(EMBEDDINGS_FILE, embeddings)
    return count


def ingest_source(source_path: str, source_type: str = "article", embed: bool = False, use_ocr: bool = False) -> dict:
    """Ingest a source file, extract entities and edges, update graph."""
    if source_path == '-':
        content = sys.stdin.read()
        source_name = 'stdin'
    else:
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source not found: {source_path}")
        content = _parse_file(source_path, use_ocr=use_ocr)
        source_name = os.path.basename(source_path)

    # Filter sensitive data
    filtered_content, filter_log = filter_sensitive(content)
    if filter_log:
        for item in filter_log:
            _log_audit('filter', {'source': source_name, **item})

    # Extract entities
    entities = _extract_entities(filtered_content, source_type)
    source_slug = _slugify(source_name)

    registry = _load_json(ENTITIES_FILE)
    if isinstance(registry, list):
        registry = {}
    for entity in entities:
        eid = entity['id']
        if eid in registry:
            existing = registry[eid]
            existing['confidence'] = min(1.0, existing.get('confidence', 0.5) + 0.05)
            if 'sources' in existing:
                existing.setdefault('sources', []).append(source_slug)
        else:
            registry[eid] = {
                'id': eid, 'type': entity['type'], 'name': entity['name'],
                'attributes': entity.get('attributes', {}),
                'confidence': entity['confidence'],
                'sources': [source_slug],
                'page': f"pages/entities/{eid}.md",
            }
    _save_json(ENTITIES_FILE, registry)

    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []
    new_edges = _extract_edges(filtered_content, source_slug, entities)
    all_edges.extend(new_edges)
    _save_json(EDGES_FILE, {'edges': all_edges})

    # Log audit
    _log_audit('ingest', {
        'source': source_name, 'source_type': source_type,
        'entities': [e['id'] for e in entities],
        'edges': len(new_edges),
        'filter_count': sum(item['count'] for item in filter_log),
    })

    embedded = 0
    if embed:
        embedded = _embed_entities(registry)

    return {
        'source': source_name,
        'entities_found': len(entities),
        'entities_new': sum(1 for e in entities if e['id'] not in _load_json(ENTITIES_FILE)),
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
                        help='Enable OCR for image files (.png, .jpg, etc.)')
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
                    r = ingest_source(filepath, args.source_type, embed=args.embed, use_ocr=args.ocr)
                    results.append(r)
                except Exception as e:
                    print(f"Error ingesting {filename}: {e}", file=sys.stderr)
        print(json.dumps({'batch_results': results}, indent=2, ensure_ascii=False))
        return

    source = '-' if args.stdin else args.source
    if not source:
        parser.print_help()
        sys.exit(1)

    try:
        result = ingest_source(source, args.source_type, embed=args.embed, use_ocr=args.ocr)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
