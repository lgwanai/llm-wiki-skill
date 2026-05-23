#!/usr/bin/env python3
from __future__ import annotations
"""lint.py — Wiki Quality Linter for llm-wiki."""

import argparse
import json
import math
import os
from pathlib import Path
import re
from datetime import datetime, timezone

WIKI_DIR = Path(os.environ.get("LLM_WIKI_DIR", str(Path(__file__).parent.parent / ".wiki")))
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
ENTITIES_FILE = os.path.join(GRAPH_DIR, "entities.json")
EDGES_FILE = os.path.join(GRAPH_DIR, "edges.json")


def _load_json(path: str) -> dict | list:
    path_str = str(path)
    if not os.path.exists(path_str):
        return {} if 'entities' in path_str else {'edges': []}
    try:
        with open(path_str, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {} if 'entities' in path else {'edges': []}


def _load_json_safe(path, default):
    """Load JSON, returning default for missing/corrupt files."""
    path_str = str(path)
    if not os.path.exists(path_str):
        return default
    try:
        with open(path_str, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(iso_str: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 999


def find_orphans() -> list[dict]:
    """Find entity pages with no incoming edges in the graph."""
    entities_data = _load_json(ENTITIES_FILE)
    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []

    if not isinstance(entities_data, dict):
        return []

    incoming: set = set()
    outgoing: set = set()
    for edge in all_edges:
        incoming.add(edge.get('target', ''))
        outgoing.add(edge.get('source', ''))

    orphans = []
    for eid in entities_data:
        if eid not in incoming and eid not in outgoing:
            orphans.append({
                'entity_id': eid,
                'name': entities_data[eid].get('name', eid),
                'type': entities_data[eid].get('type', 'unknown'),
            })
    return orphans


def find_stale_claims() -> list[dict]:
    """Find claims past their retention threshold based on last_confirmed."""
    entities_data = _load_json(ENTITIES_FILE)
    if not isinstance(entities_data, dict):
        return []

    decay_s = {'architecture': 260, 'project': 130, 'bug': 20, 'meeting': 10,
               'pattern': 87, 'preference': 527}

    stale = []
    for eid, entity in entities_data.items():
        last = entity.get('last_confirmed', '')
        if not last:
            continue
        days = _days_since(last)
        etype = entity.get('type', 'project')
        s = decay_s.get(etype, 130)
        retention = math.exp(-days / s) if s > 0 else 1.0
        if retention < 0.5:
            stale.append({
                'entity_id': eid,
                'name': entity.get('name', eid),
                'last_confirmed': last,
                'days_since': days,
                'retention': round(retention, 3),
                'status': 'archived' if retention < 0.15 else 'stale',
            })
    stale.sort(key=lambda x: x['retention'])
    return stale


def find_broken_links() -> list[dict]:
    """Find wikilinks pointing to nonexistent pages or entities."""
    entities_data = _load_json(ENTITIES_FILE)
    valid_ids = set(entities_data.keys()) if isinstance(entities_data, dict) else set()

    broken = []
    for subdir in ('entities', 'decisions', 'sessions', 'patterns'):
        scan_dir = os.path.join(PAGES_DIR, subdir)
        if not os.path.isdir(scan_dir):
            continue
        for filename in os.listdir(scan_dir):
            if not filename.endswith('.md'):
                continue
            filepath = os.path.join(scan_dir, filename)
            try:
                with open(filepath, encoding='utf-8') as f:
                    content = f.read()
            except OSError:
                continue
            for match in re.finditer(r'\[\[([^\]]+)\]\]', content):
                target = match.group(1)
                target_slug = target.split('|')[0].strip()
                if target_slug and target_slug not in valid_ids:
                    broken.append({
                        'file': filepath,
                        'target': target_slug,
                        'line': content[:match.start()].count('\n') + 1,
                    })
    return broken


def find_contradictions() -> list[dict]:
    """Detect contradictory claims — two entities with same name but different confidence."""
    entities_data = _load_json(ENTITIES_FILE)
    if not isinstance(entities_data, dict):
        return []

    by_name: dict[str, list] = {}
    for eid, entity in entities_data.items():
        name = entity.get('name', '').lower()
        if name:
            by_name.setdefault(name, []).append((eid, entity))

    contradictions = []
    for name, entries in by_name.items():
        if len(entries) < 2:
            continue
        confidences = [e[1].get('confidence', 0.5) for e in entries]
        if max(confidences) - min(confidences) > 0.3:
            contradictions.append({
                'name': name,
                'entities': [e[0] for e in entries],
                'confidence_range': [min(confidences), max(confidences)],
                'suggestion': 'consider merging or superseding the lower-confidence entity',
            })
    return contradictions


def rescore_content() -> list[dict]:
    """Re-score quality for all entity pages."""
    entities_data = _load_json(ENTITIES_FILE)
    if not isinstance(entities_data, dict):
        return []

    scored = []
    for eid, entity in entities_data.items():
        dimensions = {
            'structure': 0.5 if entity.get('attributes') else 0.3,
            'completeness': 0.5 if entity.get('confidence', 0) > 0.5 else 0.3,
            'source_citation': 0.5 if entity.get('sources') else 0.2,
            'consistency': 0.7,
            'freshness': 0.5,
            'readability': 0.6,
        }
        quality = sum(dimensions.values()) / len(dimensions)
        entity['quality_score'] = round(quality, 2)
        entity['quality_dimensions'] = {k: round(v, 2) for k, v in dimensions.items()}
        entity['last_scored'] = _now()
        scored.append({'entity_id': eid, 'quality_score': round(quality, 2)})

    _save_json(ENTITIES_FILE, entities_data)
    return scored


def auto_heal(issues: dict) -> list[dict]:
    """Auto-resolve fixable issues. Returns list of healed items."""
    healed = []
    entities_data = _load_json(ENTITIES_FILE)

    for orphan in issues.get('orphans', []):
        eid = orphan.get('entity_id', '')
        if eid in entities_data:
            entities_data[eid]['status'] = 'orphan'
            healed.append({'type': 'orphan_tagged', 'entity': eid})

    for stale in issues.get('stale', []):
        eid = stale.get('entity_id', '')
        if eid in entities_data and stale.get('status') == 'stale':
            entities_data[eid]['status'] = 'stale'
            healed.append({'type': 'stale_marked', 'entity': eid})

    _save_json(ENTITIES_FILE, entities_data)
    return healed


def generate_report(issues: dict, healed: list[dict]) -> str:
    """Produce a structured markdown lint report."""
    total = sum(len(v) for v in issues.values())
    healed_count = len(healed)
    needs_attention = total - healed_count

    lines = ['# Wiki Health Report', '', f'**Date:** {_now()}', '',
             '## Summary', '',
             f'- Issues found: **{total}**', f'- Auto-healed: **{healed_count}**',
             f'- Needs attention: **{needs_attention}**', '']

    if healed:
        lines.append('## Auto-Healed')
        for item in healed:
            lines.append(f'- ✅ {item["type"].replace("_", " ")}: `{item.get("entity", "")}`')
        lines.append('')

    for section_name, items in issues.items():
        if not items:
            continue
        remaining = [i for i in items if not any(
            h.get('entity') == i.get('entity_id', '') for h in healed)]
        if not remaining:
            continue
        lines.append(f'## {section_name.replace("_", " ").title()} ({len(remaining)})')
        for item in remaining[:10]:
            name = item.get('name', item.get('entity_id', item.get('file', '')))
            extra = ''
            if 'retention' in item:
                extra = f' (retention: {item["retention"]})'
            if 'target' in item:
                extra = f' → `{item["target"]}`'
            lines.append(f'- 🔴 **{name}**{extra}')
        if len(remaining) > 10:
            lines.append(f'- ... and {len(remaining) - 10} more')
        lines.append('')

    return '\n'.join(lines)


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Quality Linter')
    parser.add_argument('--auto-heal', action='store_true', help='Auto-resolve fixable issues')
    parser.add_argument('--report-file', help='Write report to file instead of stdout')
    args = parser.parse_args()

    issues = {
        'orphans': find_orphans(),
        'stale': find_stale_claims(),
        'broken_links': find_broken_links(),
        'contradictions': find_contradictions(),
    }
    rescore_content()

    healed = auto_heal(issues) if args.auto_heal else []

    report = generate_report(issues, healed)

    if args.report_file:
        with open(args.report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f'Report written to {args.report_file}')
    else:
        print(report)


if __name__ == "__main__":
    _main()
