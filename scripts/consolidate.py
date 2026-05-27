#!/usr/bin/env python3
from __future__ import annotations
"""consolidate.py — Memory Tier Consolidation for llm-wiki."""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import get_wiki_dir

WIKI_DIR = get_wiki_dir()
MEMORY_DIR = WIKI_DIR / "memory"

WORKING_FILE = os.path.join(MEMORY_DIR, "working.json")
EPISODIC_FILE = os.path.join(MEMORY_DIR, "episodic.json")
SEMANTIC_FILE = os.path.join(MEMORY_DIR, "semantic.json")

DECAY_S_VALUES = {
    "architecture": 260,
    "project": 130,
    "bug": 20,
    "meeting": 10,
    "pattern": 87,
    "preference": 527,
}


def _load_json(path: str) -> list:
    """Load JSON array file, return empty list on missing or corrupt file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return []


def _save_json(path: str, data) -> None:
    """Save JSON to file, creating parent dirs if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _now() -> str:
    """Return current UTC ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _days_since(iso_str: str) -> int:
    """Return days since given ISO timestamp."""
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 999


def on_memory_write(fact: dict) -> list[dict]:
    """Hook: check contradictions after writing a fact to any memory tier.

    Called automatically after promote_episodic_to_semantic writes new facts.
    Returns contradictions found.
    """
    contradictions = []
    try:
        from crystallize import check_contradictions
        result = check_contradictions([fact])
        if result:
            for c in result:
                print(f'CONTRADICTION: {c.get("entity_id", "?")} — '
                      f'confidence delta: {abs(c.get("existing_confidence", 0) - c.get("new_confidence", 0)):.2f}',
                      file=sys.stderr)
            contradictions = result
    except ImportError:
        pass
    return contradictions


def promote_working_to_episodic() -> int:
    """Group >= 5 working memory observations into episode summaries."""
    observations = _load_json(WORKING_FILE)
    if len(observations) < 5:
        return 0

    # Group by date
    groups: dict[str, list[dict]] = {}
    for obs in observations:
        ts = obs.get('timestamp', '')
        date_key = ts[:10] if ts else 'unknown'
        groups.setdefault(date_key, []).append(obs)

    promoted = 0
    episodes = _load_json(EPISODIC_FILE)
    remaining: list = []

    for date_key, group in groups.items():
        if len(group) >= 5:
            entity_ids = list({eid for obs in group for eid in obs.get('entity_ids', [])})
            episodes.append({
                'id': f'episode-{date_key}',
                'date': date_key,
                'summary': f'Consolidated {len(group)} observations from {date_key}',
                'observations': [obs.get('id', '') for obs in group],
                'entities': entity_ids,
                'decisions': [],
                'confidence': 0.5,
                'created_at': _now(),
            })
            promoted += len(group)
        else:
            remaining.extend(group)

    _save_json(WORKING_FILE, remaining)
    _save_json(EPISODIC_FILE, episodes)
    return promoted


def promote_episodic_to_semantic() -> int:
    """Cross-reference episodes, promote facts appearing in >= 2 episodes."""
    episodes = _load_json(EPISODIC_FILE)
    if len(episodes) < 2:
        return 0

    # Collect facts from episodes — match by shared entity_ids
    fact_map: dict[str, dict] = {}
    for ep in episodes:
        for eid in ep.get('entities', []):
            key = f"fact-{eid}"
            if key not in fact_map:
                fact_map[key] = {
                    'id': key,
                    'claim': f'Entity {eid} referenced in episode',
                    'entity_id': eid,
                    'confidence': 0.6,
                    'sources': [],
                    'last_confirmed': ep.get('created_at', _now()),
                    'reinforcements': 0,
                    'contradictions': [],
                    'status': 'active',
                }
            fact_map[key]['sources'].append(ep.get('id', ''))
            fact_map[key]['reinforcements'] += 1
            fact_map[key]['confidence'] = min(1.0, 0.5 + fact_map[key]['reinforcements'] * 0.1)

    # Promote facts appearing in >= 2 episodes
    semantic = _load_json(SEMANTIC_FILE)
    promoted = 0
    new_episodes: list = []

    for ep in episodes:
        entity_ids = ep.get('entities', [])
        promoted_any = False
        for eid in entity_ids:
            key = f"fact-{eid}"
            if key in fact_map and fact_map[key]['reinforcements'] >= 2:
                promoted_any = True
        if not promoted_any:
            new_episodes.append(ep)

    for fact in fact_map.values():
        if fact['reinforcements'] >= 2:
            existing_ids = {f.get('id') for f in semantic}
            if fact['id'] not in existing_ids:
                semantic.append(fact)
                promoted += 1
                on_memory_write(fact)

    _save_json(EPISODIC_FILE, new_episodes)
    _save_json(SEMANTIC_FILE, semantic)
    return promoted


def detect_procedural_patterns() -> list[dict]:
    """Cluster semantic facts to find patterns recurring >= 5 times."""
    semantic = _load_json(SEMANTIC_FILE)
    if len(semantic) < 5:
        return []

    # Simple clustering: group by entity type prefix / keywords in claim
    clusters: dict[str, list[dict]] = {}
    for fact in semantic:
        claim = fact.get('claim', '')
        words = claim.lower().split()
        for w in words[:3]:
            if len(w) > 3 and w not in ('entity', 'referenced', 'episode', 'from'):
                clusters.setdefault(w, []).append(fact)
                break

    patterns = []
    for keyword, facts in clusters.items():
        if len(facts) >= 5:
            entity_ids = [f.get('entity_id', '') for f in facts]
            patterns.append({
                'category': keyword,
                'pattern_name': f'Recurring pattern: {keyword}',
                'count': len(facts),
                'example_facts': [f.get('id', '') for f in facts[:3]],
                'entity_ids': entity_ids[:5],
            })

    return patterns


def apply_retention_decay() -> dict:
    """Apply Ebbinghaus decay to semantic facts. Archive deeply decayed ones."""
    semantic = _load_json(SEMANTIC_FILE)
    if not semantic:
        return {'decayed': 0, 'archived': 0, 'deprioritized': 0}

    archived: list = []
    active: list = []
    decayed_count = 0
    archived_count = 0
    deprioritized_count = 0

    for fact in semantic:
        entity_id = fact.get('entity_id', '')
        fact_type = fact.get('type', 'project')

        # Guess type from entity name or context
        if 'bug' in entity_id.lower() or 'fix' in entity_id.lower():
            fact_type = 'bug'
        elif 'meeting' in entity_id.lower():
            fact_type = 'meeting'
        elif 'pattern' in entity_id.lower():
            fact_type = 'pattern'
        elif 'decision' in entity_id.lower() or 'arch' in entity_id.lower():
            fact_type = 'architecture'

        s = DECAY_S_VALUES.get(fact_type, 130)
        days = _days_since(fact.get('last_confirmed', '2000-01-01'))
        retention = math.exp(-days / s) if s > 0 else 1.0

        if retention < 0.15:
            archived.append(fact)
            archived_count += 1
            continue

        if retention < 0.3:
            fact['deprioritized'] = True
            deprioritized_count += 1
        else:
            fact.pop('deprioritized', None)

        # Simulate reinforcement: if reinforcements > 0, slow decay
        if fact.get('reinforcements', 0) > 3:
            fact['last_confirmed'] = _now()
            fact['_s_value'] = min(s * 10, s * (1.05 ** fact.get('reinforcements', 0)))

        active.append(fact)
        decayed_count += 1

    existing_archived = _load_json(SEMANTIC_FILE + '.archived')
    if isinstance(existing_archived, dict):
        existing_archived = []
    _save_json(SEMANTIC_FILE, active)
    _save_json(SEMANTIC_FILE + '.archived', existing_archived + archived)
    return {'decayed': decayed_count, 'archived': archived_count, 'deprioritized': deprioritized_count}


def _main() -> None:
    parser = argparse.ArgumentParser(description='llm-wiki Memory Consolidation')
    parser.add_argument('--tiers', default='working,episodic,semantic',
                        help='Comma-separated tiers to consolidate')
    parser.add_argument('--decay-only', action='store_true',
                        help='Skip promotion, only apply retention decay')
    args = parser.parse_args()

    tiers = [t.strip() for t in args.tiers.split(',')]

    if args.decay_only:
        result = apply_retention_decay()
        print(json.dumps(result, indent=2))
        return

    results: dict = {}

    if 'working' in tiers:
        promoted = promote_working_to_episodic()
        results['working_to_episodic'] = promoted
        print(f'Promoted {promoted} observations to episodic memory.', file=sys.stderr)

    if 'episodic' in tiers:
        promoted = promote_episodic_to_semantic()
        results['episodic_to_semantic'] = promoted
        print(f'Promoted {promoted} facts to semantic memory.', file=sys.stderr)

    if 'semantic' in tiers:
        patterns = detect_procedural_patterns()
        decay_result = apply_retention_decay()
        results['patterns_detected'] = len(patterns)
        results['decay'] = decay_result
        print(f'Detected {len(patterns)} patterns. Decay: {decay_result}', file=sys.stderr)

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
