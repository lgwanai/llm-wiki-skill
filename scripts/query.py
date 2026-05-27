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
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import get_config, get_wiki_dir, get_llm_config, get_api_url, get_query_config

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"


def load_config():
    return get_config()


def call_llm(system_prompt: str, user_content: str, config: dict) -> str:
    import requests

    llm_config = get_llm_config()
    provider = llm_config.get("provider", "deepseek")
    
    if provider == "ollama":
        api_url = f"{llm_config['base_url'].rstrip('/')}/api/chat"
        payload = {
            "model": llm_config.get("model", "llama3.2"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {
                "temperature": llm_config.get("temperature", 0.3),
                "num_ctx": llm_config.get("num_ctx", 32768),
            }
        }
        headers = {"Content-Type": "application/json"}
    elif provider == "custom":
        api_url = get_api_url()
        payload = {
            "model": llm_config.get("model", ""),
            "temperature": llm_config.get("temperature", 0.3),
            "max_tokens": 8000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.get('api_key', '')}",
        }
    else:
        api_url = get_api_url()
        api_key = llm_config.get("api_key", "")
        if not api_key:
            raise RuntimeError("LLM API key not configured.")
        
        payload = {
            "model": llm_config.get("model", "deepseek-v4-flash"),
            "temperature": llm_config.get("temperature", 0.3),
            "max_tokens": 8000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        
        if provider == "ollama":
            return (data.get("message", {}).get("content", "") or "").strip()
        else:
            msg = data["choices"][0]["message"]
            return (msg.get("content") or "").strip()
    except requests.RequestException as e:
        raise RuntimeError(f"LLM API call failed: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected LLM API response: {e}")


def search_wiki(query: str, limit: int = 5) -> list[dict]:
    """Hybrid search: BM25 + Vector + Graph + entities.json fallback, fused by RRF."""
    all_streams: list[list[dict]] = []

    # 1. BM25 keyword search (now supports Chinese via jieba)
    try:
        from search import bm25_search
        bm25_results = bm25_search(query, str(PAGES_DIR), limit=limit * 2)
        if bm25_results:
            all_streams.append(bm25_results)
    except Exception:
        pass

    # 2. Vector semantic search (via Ollama)
    try:
        from search import vector_search
        vector_results = vector_search(query, str(PAGES_DIR), limit=limit)
        if vector_results:
            all_streams.append(vector_results)
    except Exception:
        pass

    # 3. Graph entity search
    try:
        from search import graph_search
        graph_results = graph_search(query, str(WIKI_DIR / "graph"), limit=limit)
        if graph_results:
            # Convert graph results to BM25-compatible format
            converted = []
            for g in graph_results:
                eid = g.get("entity_id", "")
                page_dir = "concepts" if g.get("type") in ("concept", "technique", "model") else "entities"
                page_path = PAGES_DIR / page_dir / f"{eid}.md"
                if page_path.exists():
                    converted.append({
                        "file": eid,
                        "path": str(page_path),
                        "score": g.get("confidence", 0.5),
                        "stream": "graph",
                    })
            if converted:
                all_streams.append(converted)
    except Exception:
        pass

    # 3. Fuse results with RRF if multiple streams
    if len(all_streams) >= 2:
        try:
            from search import reciprocal_rank_fusion
            fused = reciprocal_rank_fusion(all_streams)
            results = []
            seen = set()
            for f in fused[:limit]:
                path = f.get("path", "")
                if path and path not in seen:
                    seen.add(path)
                    eid = f.get("file") or f.get("entity_id", "")
                    results.append({
                        "path": path,
                        "score": f.get("rrf_score", 0),
                        "id": eid,
                        "type": _infer_type(eid),
                    })
            if results:
                return results
        except Exception:
            pass
    elif all_streams:
        # Single stream — convert directly
        results = []
        seen = set()
        for r in all_streams[0]:
            path = r.get("path", "")
            if path and path not in seen:
                seen.add(path)
                eid = r.get("file", "")
                results.append({
                    "path": path,
                    "score": r.get("score", 0),
                    "id": eid,
                    "type": _infer_type(eid),
                })
        if results:
            return results[:limit]

    # 4. Entity name fallback (substring match against entities.json)
    entities = _get_entities()
    results = []
    seen = set()
    if entities:
        query_lower = query.lower()
        for eid, data in entities.items():
            if eid in seen:
                continue
            name = data.get("name", "")
            if query_lower in eid.lower() or query_lower in name.lower() or any(
                qt in name for qt in query_lower.split() if len(qt) >= 2
            ):
                etype = data.get("type", "")
                page_dir = "concepts" if etype in ("concept", "technique", "model", "framework", "benchmark", "paper") else "entities"
                page_path = PAGES_DIR / page_dir / f"{eid}.md"
                if page_path.exists():
                    seen.add(eid)
                    results.append({
                        "path": str(page_path),
                        "score": 0.80,
                        "id": eid,
                        "type": etype,
                    })

    return results[:limit]


_entities_cache: Optional[dict] = None


def _get_entities() -> dict:
    global _entities_cache
    if _entities_cache is None:
        entities_file = WIKI_DIR / "graph" / "entities.json"
        if entities_file.exists():
            try:
                _entities_cache = json.loads(entities_file.read_text(encoding="utf-8"))
                if not isinstance(_entities_cache, dict):
                    _entities_cache = {}
            except (json.JSONDecodeError, OSError):
                _entities_cache = {}
        else:
            _entities_cache = {}
    return _entities_cache


def _infer_type(eid: str) -> str:
    """Infer entity type from ID or entities.json."""
    entities = _get_entities()
    if eid in entities:
        return entities[eid].get("type", "concept")
    return "concept"


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
    except (OSError, UnicodeDecodeError, PermissionError):
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


def query_wiki(query: str, file_back: bool = False, fmt: str = "markdown",
               synthesis: bool = True) -> dict:
    config = load_config()
    query_cfg = get_query_config()
    
    if not synthesis:
        pass
    elif "llm_synthesis" in query_cfg:
        synthesis = query_cfg.get("llm_synthesis", True)

    pages = search_wiki(query)

    if pages and not synthesis:
        # Fast path: return raw search results without LLM call
        lines = [f"## 搜索结果: {query}\n"]
        for i, p in enumerate(pages[:10], 1):
            snippet = _read_snippet(p["path"], query)
            lines.append(f"{i}. **[[{p['id']}]]** ({p['type']}) — score: {p['score']:.2f}")
            if snippet:
                lines.append(f"   > {snippet}")
            lines.append("")
        return {
            "query": query,
            "format": "fast",
            "answer": "\n".join(lines),
            "pages_searched": len(pages),
            "sources": [p.get("id", "unknown") for p in pages],
        }

    answer = synthesize_answer(query, pages, config, fmt=fmt) if pages else "No relevant wiki pages found."

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


def _read_snippet(path: str, query: str, max_len: int = 120) -> str:
    """Extract a relevant snippet from a page, surrounding the query terms."""
    try:
        content = Path(path).read_text(encoding="utf-8")
        # Strip frontmatter
        content = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
        query_terms = [t for t in query.split() if len(t) >= 2]
        for term in query_terms:
            idx = content.lower().find(term.lower())
            if idx >= 0:
                start = max(0, idx - 40)
                end = min(len(content), idx + len(term) + max_len)
                snippet = content[start:end].replace("\n", " ").strip()
                return ("..." if start > 0 else "") + snippet + ("..." if end < len(content) else "")
        # Fallback: first non-empty line
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                return line[:max_len] + "..."
    except Exception:
        pass
    return ""


def main():
    parser = argparse.ArgumentParser(description="Query wiki and answer questions")
    parser.add_argument("query", help="Question to answer")
    parser.add_argument("--file-back", action="store_true", help="File answer back to wiki")
    parser.add_argument("--format", choices=["markdown", "table", "timeline", "slides", "json", "graph"],
                        default="markdown", help="Output format (default: markdown)")
    parser.add_argument("--no-synthesis", action="store_true",
                        help="Skip LLM synthesis — return raw search results (fast)")
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

    result = query_wiki(args.query, file_back=args.file_back, fmt=args.format,
                        synthesis=not args.no_synthesis)
    print(result["answer"])

    if args.file_back and result.get("filed"):
        print(f"\n---\nFiled to: {result['filed']}", file=sys.stderr)


if __name__ == "__main__":
    main()
