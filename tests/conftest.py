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
    """Create a temporary .wiki/ directory with sample data."""
    tmp = tempfile.mkdtemp()
    wiki = Path(tmp) / ".wiki"
    wiki.mkdir()
    (wiki / "pages" / "entities").mkdir(parents=True)
    (wiki / "pages" / "decisions").mkdir(parents=True)
    (wiki / "pages" / "sessions").mkdir(parents=True)
    (wiki / "pages" / "patterns").mkdir(parents=True)
    (wiki / "graph").mkdir(parents=True)
    (wiki / "memory").mkdir(parents=True)
    (wiki / "audit").mkdir(parents=True)

    orig_dir = os.getcwd()
    os.chdir(tmp)
    yield tmp
    os.chdir(orig_dir)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sample_entities(wiki_dir):
    """Create sample entity pages and populate entities.json."""
    import graph

    entity_data = {
        "auth-service": (
            "id: auth-service\n"
            "type: project\n"
            "name: Auth Service\n"
            "status: active\n"
            "confidence: 0.9\n"
            "sources: [session-2024-03-15, codebase-scan]\n"
            "tags: [auth, security]\n"
        ),
        "redis-caching": (
            "id: redis-caching\n"
            "type: library\n"
            "name: Redis\n"
            "version: 7.0\n"
            "confidence: 0.85\n"
            "sources: [session-2024-03-15]\n"
            "last_confirmed: 2024-04-02\n"
        ),
        "sarah-chen": (
            "id: sarah-chen\n"
            "type: person\n"
            "name: Sarah Chen\n"
            "role: backend lead\n"
            "confidence: 0.9\n"
        ),
    }

    for slug, frontmatter in entity_data.items():
        page = f"---\n{frontmatter}---\n\n# {slug}\n\nDescription.\n\n"
        page += "## Relationships\n"
        page += f"- *uses* [[" + ("redis-caching" if slug == "auth-service" else "auth-service") + "]]\n"

        filepath = Path(wiki_dir) / ".wiki" / "pages" / "entities" / f"{slug}.md"
        filepath.write_text(page)

    graph.build_entity_registry(str(Path(wiki_dir) / ".wiki" / "pages"))
    graph.build_edges(str(Path(wiki_dir) / ".wiki" / "pages"))
    return wiki_dir
