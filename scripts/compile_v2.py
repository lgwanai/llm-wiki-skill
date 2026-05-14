#!/usr/bin/env python3
"""compile_v2.py — Simplified wiki compilation.

Following Karpathy's original design: LLM reads source, writes wiki pages directly.
No complex regex, no JSON parsing, minimal Python processing.

Process:
1. Read source document
2. Ask LLM to write wiki pages in markdown
3. Split output by clear separators
4. Write pages to .wiki/pages/
5. Update index.md
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r'(?:sk|pk|rk)-(?:[a-zA-Z0-9]{20,})', '[REDACTED: API key]'),
    (r'(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}', '[REDACTED: GitHub token]'),
    (r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     '[REDACTED: Private key]'),
    (r'password\s*[=:]\s*\S+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]

KEYWORD_RELATION_MAP = [
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
]


def strip_sensitive(content: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def extract_edge_type(line: str) -> str:
    for pattern, rel_type in KEYWORD_RELATION_MAP:
        if re.search(pattern, line):
            return rel_type
    return "relates_to"

CONFIG_PATH = Path(__file__).parent / "wiki_config.yaml"
WIKI_DIR = Path(__file__).parent.parent / ".wiki"
PAGES_DIR = WIKI_DIR / "pages"
ENTITIES_DIR = PAGES_DIR / "entities"
CONCEPTS_DIR = PAGES_DIR / "concepts"
INDEX_FILE = PAGES_DIR / "index.md"


def load_config():
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def call_llm(system_prompt: str, user_content: str, config: dict) -> str:
    llm = config.get("llm", {})
    api_url = llm.get("base_url", "https://api.deepseek.com").rstrip("/") + "/v1/chat/completions"

    payload = {
        "model": llm.get("model", "deepseek-v4-flash"),
        "temperature": llm.get("temperature", 0.3),
        "max_tokens": 32000,
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm.get('api_key', '')}",
    }

    resp = requests.post(api_url, json=payload, headers=headers, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    msg = data["choices"][0]["message"]
    return (msg.get("content") or "").strip()


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
        except:
            entries = []

    entries.append(entry)
    audit_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_contradictions(page_id: str, new_content: str, existing_content: str) -> list:
    config = load_config()

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
        response = call_llm(system_prompt, user_prompt, config)
        return json.loads(response)
    except:
        return []


def compile_source(source_path: str, force: bool = False) -> dict:

    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source not found: {source_path}")

    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    content = strip_sensitive(content)

    source_name = os.path.basename(source_path)
    config = load_config()

    print(f"Compiling {source_name} ({len(content)} chars)...", file=sys.stderr)

    system_prompt = """You are a wiki builder. Your job is to read a document and write wiki pages.

## Output Format
Write pages separated by exactly this marker: ===PAGE_END===

Each page must start with YAML frontmatter:
---
id: entity-slug
type: concept|model|technique|benchmark|paper|framework
name: Display Name
confidence: 0.85
source: source-name
---

Then the page content with sections:
# [Title]

## Overview
[2-4 sentences: what it is, why it matters]

## Key Details
[Important technical details]

## Relationships
- uses/extends/improves [[other-entity]] — [brief explanation]

## Source Context
> [Relevant excerpt from document]

## Quality Rules
- Extract ONLY important entities (target 10-20 pages per document)
- Merge variants: DeepSeek-V3.2, DeepSeek-V3-2 → single page deepseek-v3.2
- Use lowercase-hyphenated IDs: muon-optimizer, kv-cache
- Title Case names: "Muon Optimizer", "KV Cache"
- Substantive descriptions (not 1-line summaries)
- Include source excerpts

## Entity Types
- concept: Core architecture/mechanism
- model: AI model variants
- technique: Training methods
- benchmark: Evaluation datasets
- framework: Infrastructure
- paper: Publications"""

    user_prompt = f"""Document: {source_name}

Content:
{content}

Write wiki pages for the key entities/concepts in this document.
Focus on: architecture innovations, model variants, techniques, benchmarks.
Target: 10-20 high-quality pages with substantive content.
Output pages separated by ===PAGE_END==="""
    print("Calling LLM...", file=sys.stderr)
    response = call_llm(system_prompt, user_prompt, config)

    pages = response.split("===PAGE_END===")

    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)

    created_pages = []
    updated_pages = []
    contradictions_found = []

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
            import yaml
            frontmatter = yaml.safe_load(frontmatter_text)
        except:
            continue

        entity_id = frontmatter.get("id", "")
        entity_type = frontmatter.get("type", "concept")

        if not entity_id:
            continue

        target_dir = CONCEPTS_DIR if entity_type in ["concept", "technique"] else ENTITIES_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        page_path = target_dir / f"{entity_id}.md"

        if page_path.exists() and not force:
            existing_content = page_path.read_text(encoding="utf-8")
            contradictions = detect_contradictions(entity_id, page_content, existing_content)

            if contradictions:
                contradictions_found.extend(contradictions)
                page_content = existing_content + "\n\n## Contradictions Detected\n\n"
                for c in contradictions:
                    ctype = c.get('contradiction_type', 'unknown')
                    sev = c.get('severity', 'medium')
                    existing = c.get('existing_claim', 'N/A')
                    new = c.get('new_claim', 'N/A')
                    page_content += f"- **{ctype}** ({sev}): {existing} → {new}\n"
                page_path.write_text(page_content, encoding="utf-8")
                updated_pages.append({
                    "id": entity_id,
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                    "contradictions": len(contradictions),
                })
                print(f"  Updated: {entity_id}.md ({len(contradictions)} contradictions)", file=sys.stderr)
            else:
                updated_pages.append({
                    "id": entity_id,
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                })
                print(f"  Existing: {entity_id}.md (no contradictions)", file=sys.stderr)
        else:
            page_path.write_text(page_content, encoding="utf-8")
            created_pages.append({
                "id": entity_id,
                "type": entity_type,
                "name": frontmatter.get("name", entity_id),
                "path": str(page_path),
            })
            print(f"  Created: {entity_id}.md ({entity_type})", file=sys.stderr)

    all_pages = created_pages + updated_pages

    update_index(all_pages, source_name)
    update_log(source_name, len(created_pages), "compile")
    update_graph(all_pages, source_name)

    write_audit("compile", {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "contradictions": len(contradictions_found),
        "contradiction_details": contradictions_found[:10],
    })

    return {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "pages": all_pages,
        "contradictions_found": contradictions_found,
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
        edges = json.loads(edges_file.read_text(encoding="utf-8"))
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
                        if f"[[{target}" in line.lower() or f"[[{target.replace('-', ' ')}" in line.lower():
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
    edges_file.write_text(json.dumps(edges, indent=2, ensure_ascii=False), encoding="utf-8")


def update_index(pages: list, source_name: str):
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)

    grouped = {
        "concept": [],
        "technique": [],
        "model": [],
        "framework": [],
        "benchmark": [],
        "paper": [],
    }

    for p in pages:
        ptype = p.get("type", "concept")
        if ptype in grouped:
            grouped[ptype].append(p)
        else:
            grouped["concept"].append(p)

    lines = [
        "# Wiki Index",
        "",
        f"> Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
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
            for item in items:
                lines.append(f"- [[{item['id']}|{item['name']}]] — {ptype}")

    INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Updated index.md ({len(pages)} pages)", file=sys.stderr)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Simplified wiki compilation')
    parser.add_argument('source', help='Source file to compile')
    parser.add_argument('--force', action='store_true', help='Force re-compile (overwrite existing pages)')
    args = parser.parse_args()

    result = compile_source(args.source, force=args.force)

    pages_created = result.get('pages_created', 0)
    pages_updated = result.get('pages_updated', 0)
    print(f"\nCompiled {result['source']}: {pages_created} pages created, {pages_updated} pages updated")
    print("  → Updated log.md and graph/entities.json")


if __name__ == "__main__":
    main()
