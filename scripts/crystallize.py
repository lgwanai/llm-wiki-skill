#!/usr/bin/env python3
"""
crystallize.py — Session → Digest Pipeline

Distills a completed working session into structured knowledge:
1. Review conversation for insights
2. Create session digest from template
3. Extract standalone facts for working memory
4. Update knowledge graph with new entities/edges
5. Check for contradictions with existing knowledge

Usage:
    python crystallize.py --session-file <path> --topic <topic>
"""

import json
import os
from typing import Optional

WIKI_DIR = ".wiki"
PAGES_DIR = os.path.join(WIKI_DIR, "pages")
MEMORY_DIR = os.path.join(WIKI_DIR, "memory")


def create_digest(session_file: str, topic: str, date: str) -> str:
    """Create a session digest page from template."""
    # TODO: Parse session content, extract findings/entities/decisions
    # TODO: Render using templates/session-digest.md
    pass


def extract_facts(digest_content: str) -> list[dict]:
    """Extract standalone facts from digest for working memory."""
    # TODO: Identify single claims about single entities
    pass


def update_graph(entities: list[dict], edges: list[dict]):
    """Update entities.json and edges.json with session discoveries."""
    # TODO: Merge with existing graph, update confidence scores
    pass


def check_contradictions(facts: list[dict]) -> list[dict]:
    """Compare new facts against existing knowledge for contradictions."""
    # TODO: Load existing claims, compare with new facts
    pass


if __name__ == "__main__":
    print("crystallize.py — Session Crystallization")
    print("This is a skeleton. Requires LLM integration for content analysis.")
