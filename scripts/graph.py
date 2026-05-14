#!/usr/bin/env python3
"""graph.py — Knowledge Graph Builder & Querier for llm-wiki."""

import argparse
import json
import os
import re
import sys
from collections import deque
from datetime import datetime, timezone

WIKI_DIR = ".wiki"
GRAPH_DIR = os.path.join(WIKI_DIR, "graph")
ENTITIES_FILE = os.path.join(GRAPH_DIR, "entities.json")
EDGES_FILE = os.path.join(GRAPH_DIR, "edges.json")


def _parse_yaml_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter between --- delimiters. Simple parser — no pyyaml needed."""
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).split('\n'):
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, _, value = line.partition(':')
        key, value = key.strip(), value.strip()
        if value.startswith('[') and value.endswith(']'):
            value = [v.strip().strip('"\'') for v in value[1:-1].split(',') if v.strip()]
        elif value.lower() in ('true', 'false'):
            value = value.lower() == 'true'
        elif value.replace('.', '', 1).isdigit():
            value = float(value) if '.' in value else int(value)
        else:
            value = value.strip('"\'')
        result[key] = value
    return result


def _load_json(path: str) -> dict | list:
    """Load JSON file, return empty dict/list on missing file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return {}


def _save_json(path: str, data) -> None:
    """Save JSON to file, creating parent dirs if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _slugify(name: str) -> str:
    """Create a URL-safe slug from a name."""
    return re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-').replace('_', '-'))


def build_entity_registry(pages_dir: str) -> dict:
    """Scan wiki pages, extract YAML frontmatter, build entities.json."""
    entities_dir = os.path.join(pages_dir, "entities")
    registry = {}

    if not os.path.isdir(entities_dir):
        return registry

    for filename in os.listdir(entities_dir):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(entities_dir, filename)
        try:
            with open(filepath, encoding='utf-8') as f:
                content = f.read()
        except OSError:
            continue

        fm = _parse_yaml_frontmatter(content)
        entity_id = fm.get('id') or filename.replace('.md', '')
        registry[entity_id] = {
            'id': entity_id,
            'type': fm.get('type', 'unknown'),
            'name': fm.get('name', entity_id),
            'attributes': {k: v for k, v in fm.items() if k not in ('id', 'type', 'name')},
            'confidence': fm.get('confidence', 0.5),
            'page': f"pages/entities/{filename}",
        }

    _save_json(ENTITIES_FILE, registry)
    return registry


def build_edges(pages_dir: str) -> list[dict]:
    """Scan wiki pages for relationship declarations, build edges.json."""
    edges = []
    edge_id_counter = 1

    for subdir in ('entities', 'decisions', 'sessions'):
        scan_dir = os.path.join(pages_dir, subdir)
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

            fm = _parse_yaml_frontmatter(content)
            source_id = fm.get('id') or filename.replace('.md', '')

            # Match relationship lines like: "- *uses* [[target-entity]] — description"
            rel_section = re.search(r'##\s+Relationships\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
            if rel_section:
                for line in rel_section.group(1).split('\n'):
                    match = re.match(
                        r'-\s*\*?(\w+)\*?\s+\[\[([^\]]+)\]\]\s*(?:—\s*(.*))?', line.strip()
                    )
                    if match:
                        rel_type, target_id, description = match.groups()
                        edges.append({
                            'id': f'edge-{edge_id_counter:04d}',
                            'source': source_id,
                            'target': target_id,
                            'type': rel_type,
                            'confidence': fm.get('confidence', 0.5),
                            'sources': [source_id],
                            'description': (description or '').strip(),
                            'created_at': datetime.now(timezone.utc).isoformat(),
                        })
                        edge_id_counter += 1

    _save_json(EDGES_FILE, {'edges': edges})
    return edges


def traverse(entity_id: str, depth: int = 2, edge_types: list[str] | None = None) -> dict:
    """BFS walk from an entity, filtering by edge type and depth."""
    entities_data = _load_json(ENTITIES_FILE)
    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []

    subgraph: dict = {}
    visited: set = {entity_id}
    queue = deque([(entity_id, 0)])

    while queue:
        current, current_depth = queue.popleft()
        if current_depth > depth:
            continue

        if current in entities_data:
            subgraph[current] = {'entity': entities_data[current], 'edges': []}

        for edge in all_edges:
            if edge['source'] != current:
                continue
            if edge_types and edge['type'] not in edge_types:
                continue
            target = edge['target']
            subgraph.setdefault(current, {'entity': entities_data.get(current, {}), 'edges': []})
            subgraph[current]['edges'].append(edge)

            if target not in visited and current_depth < depth:
                visited.add(target)
                queue.append((target, current_depth + 1))

    return subgraph


def find_path(source: str, target: str) -> list[dict] | None:
    """BFS shortest typed path between two entities."""
    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []

    adj: dict[str, list[dict]] = {}
    for edge in all_edges:
        adj.setdefault(edge['source'], []).append(edge)

    queue = deque([(source, [])])
    visited = {source}

    while queue:
        current, path = queue.popleft()
        if current == target:
            return path
        for edge in adj.get(current, []):
            if edge['target'] not in visited:
                visited.add(edge['target'])
                queue.append((edge['target'], path + [edge]))

    return None


def impact_analysis(entity_id: str) -> dict:
    """Find everything downstream — entities that depend ON this entity."""
    edges_data = _load_json(EDGES_FILE)
    entities_data = _load_json(ENTITIES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []

    # Build reverse adjacency (target → sources)
    rev_adj: dict[str, list[dict]] = {}
    for edge in all_edges:
        rev_adj.setdefault(edge['target'], []).append(edge)

    affected: list = []
    paths: list = []
    visited = {entity_id}
    queue = deque([(entity_id, [])])

    while queue:
        current, path = queue.popleft()
        for edge in rev_adj.get(current, []):
            if edge['type'] not in ('uses', 'depends_on'):
                continue
            if edge['source'] not in visited:
                visited.add(edge['source'])
                new_path = path + [edge]
                affected.append(entities_data.get(edge['source'], {'id': edge['source']}))
                paths.append([e['id'] for e in new_path])
                queue.append((edge['source'], new_path))

    return {'affected_entities': affected, 'paths': paths}


def graph_stats() -> dict:
    """Compute graph statistics."""
    entities_data = _load_json(ENTITIES_FILE)
    edges_data = _load_json(EDGES_FILE)
    all_edges = edges_data.get('edges', []) if isinstance(edges_data, dict) else []

    entity_count = len(entities_data) if isinstance(entities_data, dict) else 0
    edge_count = len(all_edges)

    edge_type_counts: dict[str, int] = {}
    for edge in all_edges:
        t = edge.get('type', 'unknown')
        edge_type_counts[t] = edge_type_counts.get(t, 0) + 1

    incoming: set = set()
    outgoing: set = set()
    for edge in all_edges:
        incoming.add(edge.get('target', ''))
        outgoing.add(edge.get('source', ''))
    all_node_ids = set(entities_data.keys()) if isinstance(entities_data, dict) else set()
    orphan_count = len(all_node_ids - incoming - outgoing)

    avg_edges = edge_count / entity_count if entity_count > 0 else 0

    return {
        'entity_count': entity_count,
        'edge_count': edge_count,
        'edge_types': edge_type_counts,
        'avg_edges_per_entity': round(avg_edges, 2),
        'orphan_count': orphan_count,
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Knowledge Graph Manager')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('build', help='Rebuild graph from wiki pages')

    q = sub.add_parser('query', help='Show entity and its neighborhood')
    q.add_argument('entity', help='Entity ID')

    t = sub.add_parser('traverse', help='Walk graph with depth and type filter')
    t.add_argument('entity', help='Start entity ID')
    t.add_argument('--depth', type=int, default=2, help='Max traversal depth')
    t.add_argument('--type', dest='edge_types', help='Comma-separated edge types')

    p = sub.add_parser('path', help='Find shortest path between entities')
    p.add_argument('source', help='Source entity ID')
    p.add_argument('target', help='Target entity ID')

    i = sub.add_parser('impact', help='Impact analysis for an entity')
    i.add_argument('entity', help='Entity ID to analyze')

    sub.add_parser('stats', help='Graph statistics')

    args = parser.parse_args()

    if args.command == 'build':
        pages_dir = os.path.join(WIKI_DIR, "pages")
        entities = build_entity_registry(pages_dir)
        edges = build_edges(pages_dir)
        print(json.dumps({'entities': len(entities), 'edges': len(edges)}, indent=2))

    elif args.command == 'query':
        result = traverse(args.entity, depth=1)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == 'traverse':
        edge_types = args.edge_types.split(',') if args.edge_types else None
        result = traverse(args.entity, depth=args.depth, edge_types=edge_types)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == 'path':
        result = find_path(args.source, args.target)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"No path found between '{args.source}' and '{args.target}'")

    elif args.command == 'impact':
        result = impact_analysis(args.entity)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == 'stats':
        print(json.dumps(graph_stats(), indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
