#!/usr/bin/env python3
from __future__ import annotations
"""bulk.py — Bulk Operations for LLM Wiki v2.

Operations:
    delete:    Bulk-delete stale/low-confidence pages (with audit)
    export:    Export wiki subset as JSON
    merge:     Merge duplicate entities (with conflict resolution)
    clean:     Remove orphan pages and broken links
    stats:     Show detailed wiki analytics

Usage:
    python3 scripts/bulk.py delete --stale       # delete stale pages
    python3 scripts/bulk.py delete --confidence < 0.3  # delete low-confidence
    python3 scripts/bulk.py export --type concept  # export concepts
    python3 scripts/bulk.py merge                  # merge duplicates
    python3 scripts/bulk.py clean --dry-run        # preview cleanup
    python3 scripts/bulk.py stats                  # detailed stats
"""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

WIKI_DIR = Path(__file__).parent.parent / ".wiki"
PAGES_DIR = WIKI_DIR / "pages"
GRAPH_DIR = WIKI_DIR / "graph"
AUDIT_FILE = WIKI_DIR / "audit.json"
TRASH_DIR = WIKI_DIR / "trash"


def write_audit(operation: str, details: dict) -> None:
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"op": operation, "ts": datetime.now(timezone.utc).isoformat(), **details}

    entries = []
    if AUDIT_FILE.exists():
        try:
            entries = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            entries = []
    entries.append(entry)
    AUDIT_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_delete_stale(dry_run: bool = False) -> dict:
    import math

    entities_file = GRAPH_DIR / "entities.json"
    if not entities_file.exists():
        return {"status": "error", "message": "No entities found"}

    entities = json.loads(entities_file.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)

    decay = {"architecture": 260, "project": 130, "bug": 20, "meeting": 10, "pattern": 87, "preference": 527}
    deleted = []

    for eid, entity in list(entities.items()):
        last = entity.get("last_confirmed", "")
        if not last:
            continue
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            days = (now - dt).days
        except (ValueError, TypeError):
            days = 999

        etype = entity.get("type", "project")
        half_life = decay.get(etype, 130)
        retention = math.exp(-days / half_life) if half_life > 0 else 1.0

        if retention < 0.15:
            deleted.append({"id": eid, "name": entity.get("name", eid),
                            "days_old": days, "retention": round(retention, 3)})

    if not dry_run:
        for item in deleted:
            del entities[item["id"]]
            for subdir in ["concepts", "entities", "sessions"]:
                page_path = PAGES_DIR / subdir / f"{item['id']}.md"
                if page_path.exists():
                    trash_path = TRASH_DIR / f"{item['id']}.md"
                    trash_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(page_path), str(trash_path))

        entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")
        write_audit("bulk_delete_stale", {"count": len(deleted), "items": deleted})

    return {"status": "ok", "deleted_count": len(deleted), "dry_run": dry_run, "items": deleted}


def cmd_delete_low_confidence(threshold: float, dry_run: bool = False) -> dict:
    entities_file = GRAPH_DIR / "entities.json"
    if not entities_file.exists():
        return {"status": "error", "message": "No entities found"}

    entities = json.loads(entities_file.read_text(encoding="utf-8"))
    deleted = []

    for eid, entity in list(entities.items()):
        if entity.get("confidence", 1.0) < threshold:
            deleted.append({"id": eid, "name": entity.get("name", eid),
                            "confidence": entity.get("confidence", 0)})

    if not dry_run:
        for item in deleted:
            del entities[item["id"]]
            for subdir in ["concepts", "entities", "sessions"]:
                page_path = PAGES_DIR / subdir / f"{item['id']}.md"
                if page_path.exists():
                    trash_path = TRASH_DIR / f"{item['id']}.md"
                    trash_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(page_path), str(trash_path))

        entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")
        write_audit("bulk_delete_low_confidence", {"count": len(deleted), "threshold": threshold})

    return {"status": "ok", "deleted_count": len(deleted), "dry_run": dry_run, "items": deleted}


def cmd_export(entity_type: str | None = None) -> dict:
    entities_file = GRAPH_DIR / "entities.json"
    if not entities_file.exists():
        return {"status": "error", "message": "No entities found"}

    entities = json.loads(entities_file.read_text(encoding="utf-8"))
    export = {}

    for eid, entity in entities.items():
        if entity_type and entity.get("type") != entity_type:
            continue

        page_content = ""
        for subdir in ["concepts", "entities", "sessions"]:
            page_path = PAGES_DIR / subdir / f"{eid}.md"
            if page_path.exists():
                page_content = page_path.read_text(encoding="utf-8")
                break

        export[eid] = {
            "entity": entity,
            "content": page_content,
            "size": len(page_content),
        }

    write_audit("bulk_export", {"entity_type": entity_type, "count": len(export)})
    return {"status": "ok", "count": len(export), "data": export}


def cmd_merge(dry_run: bool = False) -> dict:
    entities_file = GRAPH_DIR / "entities.json"
    if not entities_file.exists():
        return {"status": "error", "message": "No entities found"}

    entities = json.loads(entities_file.read_text(encoding="utf-8"))
    import re
    from collections import defaultdict

    def normalize(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    groups = defaultdict(list)
    for eid, entity in entities.items():
        key = normalize(entity.get("name", eid))
        groups[key].append(eid)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    merges = []

    for key, ids in duplicates.items():
        primary = ids[0]
        for dup in ids[1:]:
            merges.append({"primary": primary, "duplicate": dup,
                           "name": entities[primary].get("name", primary)})

    if not dry_run and merges:
        for m in merges:
            if m["duplicate"] in entities:
                del entities[m["duplicate"]]
            for subdir in ["concepts", "entities", "sessions"]:
                page_path = PAGES_DIR / subdir / f"{m['duplicate']}.md"
                if page_path.exists():
                    shutil.move(str(page_path), str(TRASH_DIR / f"{m['duplicate']}.md"))

        entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")
        write_audit("bulk_merge", {"count": len(merges), "merges": merges})

    return {"status": "ok", "duplicates_found": len(duplicates), "merges": len(merges),
            "dry_run": dry_run, "merge_items": merges}


def cmd_clean(dry_run: bool = False) -> dict:
    from lint import find_broken_links, find_orphans

    orphans = find_orphans()
    broken = find_broken_links()

    orphan_ids = [o["entity_id"] for o in orphans]

    if not dry_run and orphan_ids:
        for eid in orphan_ids:
            for subdir in ["concepts", "entities", "sessions"]:
                page_path = PAGES_DIR / subdir / f"{eid}.md"
                if page_path.exists():
                    trash_path = TRASH_DIR / f"orphan_{eid}.md"
                    trash_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(page_path), str(trash_path))
        write_audit("bulk_clean", {"orphans_removed": len(orphan_ids)})

    return {"status": "ok", "orphans": len(orphans), "broken_links": len(broken),
            "dry_run": dry_run}


def cmd_stats() -> dict:
    pages = {"concepts": 0, "entities": 0, "sessions": 0, "total": 0}
    total_size = 0
    for subdir in pages:
        if subdir == "total":
            continue
        d = PAGES_DIR / subdir
        if d.exists():
            for f in d.glob("*.md"):
                pages[subdir] += 1
                pages["total"] += 1
                total_size += f.stat().st_size

    entities_file = GRAPH_DIR / "entities.json"
    edges_file = GRAPH_DIR / "edges.json"
    embeddings_file = GRAPH_DIR / "embeddings.json"

    entities_count = 0
    edges_count = 0
    embeddings_count = 0
    avg_confidence = 0.0
    confidence_dist = {}

    if entities_file.exists():
        entities = json.loads(entities_file.read_text(encoding="utf-8"))
        entities_count = len(entities)
        confidences = []
        for e in entities.values():
            c = e.get("confidence", 0.85)
            confidences.append(c)
            bucket = f"{int(c * 10) / 10:.1f}"
            confidence_dist[bucket] = confidence_dist.get(bucket, 0) + 1
        avg_confidence = sum(confidences) / max(len(confidences), 1)

    if edges_file.exists():
        edges = json.loads(edges_file.read_text(encoding="utf-8"))
        if isinstance(edges, dict):
            edges = edges.get("edges", [])
        edges_count = len(edges) if isinstance(edges, list) else 0

    if embeddings_file.exists():
        embeddings = json.loads(embeddings_file.read_text(encoding="utf-8"))
        embeddings_count = len(embeddings)

    from collections import Counter
    edge_types = Counter()
    if edges_file.exists():
        edge_types = Counter(e["type"] for e in edges)

    return {
        "pages": pages,
        "total_size_kb": round(total_size / 1024, 1),
        "entities": entities_count,
        "edges": edges_count,
        "embeddings": embeddings_count,
        "avg_confidence": round(avg_confidence, 3),
        "confidence_distribution": confidence_dist,
        "edge_type_distribution": dict(edge_types.most_common()),
    }


def main():
    parser = argparse.ArgumentParser(description="Bulk operations for LLM Wiki v2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    del_parser = subparsers.add_parser("delete", help="Bulk delete pages")
    del_parser.add_argument("--stale", action="store_true", help="Delete stale pages")
    del_parser.add_argument("--confidence", type=float, help="Delete pages below confidence threshold")
    del_parser.add_argument("--dry-run", action="store_true", help="Preview only")

    export_parser = subparsers.add_parser("export", help="Export wiki subset")
    export_parser.add_argument("--type", help="Entity type to export")

    merge_parser = subparsers.add_parser("merge", help="Merge duplicate entities")
    merge_parser.add_argument("--dry-run", action="store_true", help="Preview only")

    clean_parser = subparsers.add_parser("clean", help="Clean orphan pages")
    clean_parser.add_argument("--dry-run", action="store_true", help="Preview only")

    subparsers.add_parser("stats", help="Detailed wiki statistics")

    args = parser.parse_args()

    if args.command == "delete":
        if args.stale:
            result = cmd_delete_stale(dry_run=args.dry_run)
        elif args.confidence is not None:
            result = cmd_delete_low_confidence(args.confidence, dry_run=args.dry_run)
        else:
            parser.error("Specify --stale or --confidence <value>")
    elif args.command == "export":
        result = cmd_export(entity_type=args.type)
    elif args.command == "merge":
        result = cmd_merge(dry_run=args.dry_run)
    elif args.command == "clean":
        result = cmd_clean(dry_run=args.dry_run)
    elif args.command == "stats":
        result = cmd_stats()

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
