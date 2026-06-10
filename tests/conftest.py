"""Test fixtures for llm-wiki scripts."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.fixture
def wiki_dir():
    import config
    config.reset_config()
    tmp = tempfile.mkdtemp()
    wiki = Path(tmp) / ".wiki"
    wiki.mkdir()
    (wiki / "pages" / "entities").mkdir(parents=True)
    (wiki / "pages" / "concepts").mkdir(parents=True)
    (wiki / "pages" / "decisions").mkdir(parents=True)
    (wiki / "pages" / "sessions").mkdir(parents=True)
    (wiki / "pages" / "patterns").mkdir(parents=True)
    (wiki / "graph").mkdir(parents=True)
    (wiki / "memory").mkdir(parents=True)
    (wiki / "audit").mkdir(parents=True)

    os.environ["LLM_WIKI_DIR"] = str(wiki)
    orig_dir = os.getcwd()
    os.chdir(tmp)
    yield tmp
    os.chdir(orig_dir)
    del os.environ["LLM_WIKI_DIR"]
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sample_entities(wiki_dir):
    import graph

    wiki = Path(os.environ["LLM_WIKI_DIR"])

    entities = {
        "auth-service": {
            "id": "auth-service", "type": "project", "name": "Auth Service",
            "confidence": 0.9, "sources": ["test"], "page": "pages/entities/auth-service.md",
        },
        "redis-caching": {
            "id": "redis-caching", "type": "library", "name": "Redis",
            "confidence": 0.85, "sources": ["test"], "page": "pages/entities/redis-caching.md",
        },
        "sarah-chen": {
            "id": "sarah-chen", "type": "person", "name": "Sarah Chen",
            "confidence": 0.9, "sources": ["test"], "page": "pages/entities/sarah-chen.md",
        },
    }
    (wiki / "graph" / "entities.json").write_text(json.dumps(entities))

    edges = {
        "edges": [
            {"source": "auth-service", "target": "redis-caching", "type": "uses", "description": "uses Redis"},
            {"source": "sarah-chen", "target": "auth-service", "type": "relates_to", "description": "owns"},
        ]
    }
    (wiki / "graph" / "edges.json").write_text(json.dumps(edges))

    for slug, entity in entities.items():
        page = f"---\nid: {slug}\ntype: {entity['type']}\nname: {entity['name']}\n---\n\n# {entity['name']}\n\nDescription.\n\n## Relationships\n- uses [[redis-caching]]\n"
        (wiki / "pages" / "entities" / f"{slug}.md").write_text(page)

    return wiki_dir
