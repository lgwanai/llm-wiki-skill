#!/usr/bin/env python3
from __future__ import annotations
"""_agensgraph.py — Optional AgensGraph database integration for llm-wiki.

AgensGraph is a multi-model database (graph + relational) based on PostgreSQL.
Provides:
- Cypher-like graph queries (AGE extension)
- Typed relationships with properties
- Graph traversal at scale
- ACID transactions

Enabled via config or environment variable AGENSGRAPH_URL.

Environment variables:
    AGENSGRAPH_HOST     — host (default: localhost)
    AGENSGRAPH_PORT     — port (default: 5433)
    AGENSGRAPH_USER     — user (default: wuliang)
    AGENSGRAPH_PASSWORD — password (default: lingtingt)
    AGENSGRAPH_DB       — database (default: wuliang)

Usage:
    from _agensgraph import AgensGraphStore
    store = AgensGraphStore()
    store.upsert_entity("deepseek-v4", {"type": "model", "name": "DeepSeek-V4"})
    store.create_edge("deepseek-v4", "muon-optimizer", "uses", {"weight": 1.0})
    results = store.traverse("deepseek-v4", depth=2)
"""

import json
import os
import sys

AGENSGRAPH_HOST = os.environ.get("AGENSGRAPH_HOST", "localhost")
AGENSGRAPH_PORT = int(os.environ.get("AGENSGRAPH_PORT", "5433"))
AGENSGRAPH_USER = os.environ.get("AGENSGRAPH_USER", "wuliang")
AGENSGRAPH_PASSWORD = os.environ.get("AGENSGRAPH_PASSWORD", "")
AGENSGRAPH_DB = os.environ.get("AGENSGRAPH_DB", "wuliang")


class AgensGraphStore:
    def __init__(self, host: str = AGENSGRAPH_HOST, port: int = AGENSGRAPH_PORT,
                 user: str = AGENSGRAPH_USER, password: str = AGENSGRAPH_PASSWORD,
                 db: str = AGENSGRAPH_DB):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.db = db
        self._conn = None

    def _connect(self):
        try:
            import psycopg2
            self._conn = psycopg2.connect(
                host=self.host, port=self.port, user=self.user,
                password=self.password, dbname=self.db,
            )
            self._conn.autocommit = True
            self._ensure_schema()
        except ImportError:
            print("psycopg2 not installed. Install: pip install psycopg2-binary", file=sys.stderr)
            self._conn = None
        except Exception as e:
            print(f"AgensGraph connection failed: {e}", file=sys.stderr)
            self._conn = None

    def _ensure_schema(self):
        if not self._conn:
            return
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wiki_entities (
                id TEXT PRIMARY KEY,
                entity_type TEXT,
                name TEXT,
                confidence REAL DEFAULT 0.85,
                sources JSONB DEFAULT '[]',
                created TIMESTAMP DEFAULT NOW(),
                last_confirmed TIMESTAMP DEFAULT NOW(),
                reinforcement_count INTEGER DEFAULT 1,
                metadata JSONB DEFAULT '{}'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wiki_edges (
                id SERIAL PRIMARY KEY,
                source_id TEXT REFERENCES wiki_entities(id) ON DELETE CASCADE,
                target_id TEXT REFERENCES wiki_entities(id) ON DELETE CASCADE,
                edge_type TEXT DEFAULT 'relates_to',
                weight REAL DEFAULT 1.0,
                source_file TEXT,
                metadata JSONB DEFAULT '{}',
                UNIQUE(source_id, target_id, edge_type)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_edges_source ON wiki_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON wiki_edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON wiki_edges(edge_type);
        """)

    def is_available(self) -> bool:
        if self._conn is None:
            self._connect()
        return self._conn is not None

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def upsert_entity(self, entity_id: str, data: dict) -> bool:
        if not self._conn:
            return False
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO wiki_entities (id, entity_type, name, confidence, sources, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                entity_type = EXCLUDED.entity_type,
                name = EXCLUDED.name,
                confidence = LEAST(1.0, wiki_entities.confidence + 0.05),
                sources = wiki_entities.sources || EXCLUDED.sources,
                last_confirmed = NOW(),
                reinforcement_count = wiki_entities.reinforcement_count + 1
        """, (
            entity_id,
            data.get("type", "concept"),
            data.get("name", entity_id),
            data.get("confidence", 0.85),
            json.dumps(data.get("sources", [])),
            json.dumps(data.get("metadata", {})),
        ))
        return True

    def create_edge(self, source: str, target: str, edge_type: str = "relates_to",
                    weight: float = 1.0, source_file: str = "") -> bool:
        if not self._conn:
            return False
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO wiki_edges (source_id, target_id, edge_type, weight, source_file)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_id, target_id, edge_type) DO UPDATE SET
                weight = wiki_edges.weight + 0.1,
                source_file = EXCLUDED.source_file
        """, (source, target, edge_type, weight, source_file))
        return True

    def traverse(self, entity_id: str, depth: int = 2, edge_types: list[str] | None = None) -> list[dict]:
        if not self._conn:
            return []
        cur = self._conn.cursor()
        types_filter = ""
        params = [entity_id, depth]
        if edge_types:
            types_filter = "AND e.edge_type = ANY(%s)"
            params.append(edge_types)

        cur.execute(f"""
            WITH RECURSIVE graph_walk AS (
                SELECT e.source_id, e.target_id, e.edge_type, e.weight, 1 AS level,
                       ARRAY[e.source_id, e.target_id] AS path
                FROM wiki_edges e
                WHERE e.source_id = %s
                UNION
                SELECT e.source_id, e.target_id, e.edge_type, e.weight, gw.level + 1,
                       gw.path || e.target_id
                FROM wiki_edges e
                JOIN graph_walk gw ON e.source_id = gw.target_id
                WHERE gw.level < %s {types_filter}
                AND NOT e.target_id = ANY(gw.path)
            )
            SELECT DISTINCT target_id, edge_type, weight, level FROM graph_walk
            ORDER BY level, weight DESC
        """, params)

        results = []
        for row in cur.fetchall():
            results.append({
                "entity": row[0],
                "edge_type": row[1],
                "weight": row[2],
                "depth": row[3],
            })
        return results

    def get_entity(self, entity_id: str) -> dict | None:
        if not self._conn:
            return None
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM wiki_entities WHERE id = %s", (entity_id,))
        row = cur.fetchone()
        if row:
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        return None

    def stats(self) -> dict:
        if not self._conn:
            return {"available": False}
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM wiki_entities")
        entities = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wiki_edges")
        edges = cur.fetchone()[0]
        cur.execute("SELECT edge_type, COUNT(*) FROM wiki_edges GROUP BY edge_type ORDER BY 2 DESC")
        edge_types = {row[0]: row[1] for row in cur.fetchall()}
        return {"available": True, "entities": entities, "edges": edges, "edge_types": edge_types}
