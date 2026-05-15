#!/usr/bin/env python3
"""query.py — Query wiki and answer questions (Karpathy v1 + Rohit v2).

Operations:
- Search wiki pages (BM25 + graph traversal)
- Synthesize answer from relevant pages
- File back high-quality answers as new wiki pages (optional)

Usage:
    python scripts/query.py "What is DeepSeek-V4's architecture?"
    python scripts/query.py "Explain Muon optimizer" --file-back
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

WIKI_DIR = Path(__file__).parent.parent / ".wiki"
PAGES_DIR = WIKI_DIR / "pages"
CONFIG_PATH = Path(__file__).parent / "wiki_config.yaml"


def load_config():
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def call_llm(system_prompt: str, user_content: str, config: dict) -> str:
    import requests

    llm = config.get("llm", {})
    api_url = llm.get("base_url", "https://api.deepseek.com").rstrip("/") + "/v1/chat/completions"
    api_key = llm.get("api_key", "")
    if not api_key:
        raise RuntimeError("LLM API key not configured.")

    payload = {
        "model": llm.get("model", "deepseek-v4-flash"),
        "temperature": llm.get("temperature", 0.3),
        "max_tokens": 8000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if llm.get("provider") == "deepseek":
        payload["thinking"] = {"type": "disabled"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return (msg.get("content") or "").strip()
    except requests.RequestException as e:
        raise RuntimeError(f"LLM API call failed: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected LLM API response: {e}")


def search_wiki(query: str, limit: int = 5) -> list[dict]:
    results = []

    try:
        from search import bm25_search
        results = bm25_search(query, str(PAGES_DIR), limit=limit)
    except Exception:
        pass

    if not results:
        entities_file = WIKI_DIR / "graph" / "entities.json"
        if entities_file.exists():
            try:
                entities = json.loads(entities_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                entities = {}
            query_lower = query.lower()
            for eid, data in entities.items():
                if query_lower in eid.lower() or query_lower in data.get("name", "").lower():
                    page_dir = "concepts" if data.get("type") in ["concept", "technique"] else "entities"
                    page_path = PAGES_DIR / page_dir / f"{eid}.md"
                    if page_path.exists():
                        results.append({
                            "path": str(page_path),
                            "score": 0.9,
                            "id": eid,
                            "type": data.get("type"),
                        })

    return results[:limit]


def read_page_content(page_path: str) -> str:
    try:
        content = Path(page_path).read_text(encoding="utf-8")
        if content.startswith("---"):
            lines = content.split("\n")
            end = 0
            for i, line in enumerate(lines):
                if i > 0 and line.strip() == "---":
                    end = i
                    break
            if end > 0:
                content = "\n".join(lines[end + 1:])
        return content.strip()
    except:
        return ""


def synthesize_answer(query: str, pages: list[dict], config: dict, fmt: str = "markdown") -> str:
    if not pages:
        return "No relevant wiki pages found. Try adding more sources with `wiki add`."

    contexts = []
    for i, page in enumerate(pages[:5]):
        content = read_page_content(page["path"])
        if content:
            contexts.append(f"--- PAGE {i+1}: {page.get('id', 'unknown')} ---\n{content[:2000]}")

    if not contexts:
        return "Wiki pages found but content could not be read."

    format_prompts = {
        "markdown": """## Output Format
Provide a clear, concise answer with citations:

**Answer**: [Your synthesized answer]

**Sources**:
- [[page-id-1]] — relevant point

**Related**: [[related-entity-1]], [[related-entity-2]]""",

        "table": """## Output Format
Provide a comparison table comparing the key entities:

**Answer**: [Brief overview]

## Comparison Table

| Entity | Key Feature 1 | Key Feature 2 | Use Case |
|--------|--------------|--------------|----------|
| name | detail | detail | use case |

**Sources**: [[page-id-1]] — data source""",

        "timeline": """## Output Format
Provide a timeline of key events/milestones:

**Answer**: [Context for this timeline]

## Timeline

| Date/Version | Event | Significance |
|-------------|-------|-------------|
| 2024-01 | Event | Description |

**Sources**: [[page-id-1]] — supporting evidence""",

        "slides": """## Output Format
Create a Marp slide deck presentation. Use Marp syntax:

---
marp: true
theme: default
---

# [Title]

## Slide 1: Overview
- Key point 1
- Key point 2

---

## Slide 2: Details
...

**Sources**: [[page-id-1]]""",

        "json": """## Output Format
Output ONLY valid JSON (no markdown, no explanation):

{
  "answer": "Synthesized answer",
  "sources": [{"id": "page-id", "relevance": "why relevant"}],
  "related": ["related-1", "related-2"],
  "confidence": 0.85
}""",
    }

    system_prompt = f"""You are a wiki query engine. Answer questions based on the provided wiki pages.

{format_prompts.get(fmt, format_prompts["markdown"])}

## Rules
- Synthesize information from multiple pages
- Always cite sources with wikilinks
- Note contradictions if found
- Suggest related topics to explore"""

    user_prompt = f"""Query: {query}

Wiki Pages:
{chr(10).join(contexts)}

Answer the query based on these wiki pages."""

    return call_llm(system_prompt, user_prompt, config)


def file_answer_back(query: str, answer: str, sources: list[dict]) -> str:
    concepts_dir = PAGES_DIR / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    slug = query.lower().replace(" ", "-").replace("?", "")[:50]
    slug = "".join(c for c in slug if c.isalnum() or c == "-")

    page_path = concepts_dir / f"{slug}.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    frontmatter = f"""---
id: {slug}
type: concept
name: "{query[:50]}"
confidence: 0.80
source: query-generated
created: {now}
---

"""

    content = frontmatter + f"# {query[:50]}\n\n"
    content += f"**Generated from query**: {query}\n\n"
    content += answer.replace("**Answer**:", "## Answer\n\n").replace("**Sources**:", "\n## Sources\n\n").replace("**Related**:", "\n## Related\n\n")

    page_path.write_text(content, encoding="utf-8")

    graph_dir = WIKI_DIR / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    entities_file = graph_dir / "entities.json"

    entities = {}
    if entities_file.exists():
        entities = json.loads(entities_file.read_text(encoding="utf-8"))

    entities[slug] = {
        "id": slug,
        "type": "concept",
        "name": query[:50],
        "sources": ["query-generated"],
        "confidence": 0.80,
        "created": now,
    }

    entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")

    return str(page_path)


def query_wiki(query: str, file_back: bool = False, fmt: str = "markdown") -> dict:
    config = load_config()

    pages = search_wiki(query)
    answer = synthesize_answer(query, pages, config, fmt=fmt)

    result = {
        "query": query,
        "format": fmt,
        "answer": answer,
        "pages_searched": len(pages),
        "sources": [p.get("id", "unknown") for p in pages],
    }

    if file_back and pages:
        filed_path = file_answer_back(query, answer, pages)
        result["filed"] = filed_path

    return result


def main():
    parser = argparse.ArgumentParser(description="Query wiki and answer questions")
    parser.add_argument("query", help="Question to answer")
    parser.add_argument("--file-back", action="store_true", help="File answer back to wiki")
    parser.add_argument("--format", choices=["markdown", "table", "timeline", "slides", "json", "graph"],
                        default="markdown", help="Output format (default: markdown)")
    args = parser.parse_args()

    if args.format == "graph":
        import subprocess
        import sys as _sys
        code, out = subprocess.run(
            [_sys.executable, str(Path(__file__).parent / "graph.py"), "show"],
            capture_output=True, text=True
        )
        print(out if code == 0 else f"Graph error: {out}")
        return

    result = query_wiki(args.query, file_back=args.file_back, fmt=args.format)
    print(result["answer"])

    if args.file_back and result.get("filed"):
        print(f"\n---\nFiled to: {result['filed']}", file=sys.stderr)


if __name__ == "__main__":
    main()
