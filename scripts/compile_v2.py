#!/usr/bin/env python3
"""compile_v2.py — Simplified wiki compilation.

Following Karpathy's original design: LLM reads source, writes wiki pages directly.
No complex regex, no JSON parsing, minimal Python processing.

Process:
1. Read source document
2. Ask LLM to write wiki pages in markdown
3. Split output by clear separators
4. Write pages to .wiki/pages/
5. Update index.md
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r'(?:sk|pk|rk)-(?:[a-zA-Z0-9]{20,})', '[REDACTED: API key]'),
    (r'(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}', '[REDACTED: GitHub token]'),
    (r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     '[REDACTED: Private key]'),
    (r'password\s*[=:]\s*\S+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]

KEYWORD_RELATION_MAP = [
    (r'(?i)\buses?\b\s*\[\[', 'uses'),
    (r'(?i)\bdepends?\s+on\b.*?\[\[', 'depends_on'),
    (r'(?i)\bextends?\b\s*\[\[', 'extends'),
    (r'(?i)\bimproves?\s+(?:upon|over)?\s*\[\[', 'improves_upon'),
    (r'(?i)\bcontradicts?\b\s*\[\[', 'contradicts'),
    (r'(?i)\bsupersedes?\b\s*\[\[', 'supersedes'),
    (r'(?i)\bcaused?\s+by\b.*?\[\[', 'caused_by'),
    (r'(?i)\bfixed?\s+by\b.*?\[\[', 'fixed_by'),
    (r'(?i)\breplaces?\b\s*\[\[', 'replaces'),
    (r'(?i)\brelated\s+to\b.*?\[\[', 'relates_to'),
    (r'(?i)\bpart\s+of\b.*?\[\[', 'part_of'),
    (r'(?i)\bimplemented\s+(?:by|via)\b.*?\[\[', 'implemented_by'),
]


def strip_sensitive(content: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def extract_edge_type(line: str) -> str:
    for pattern, rel_type in KEYWORD_RELATION_MAP:
        if re.search(pattern, line):
            return rel_type
    return "relates_to"

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
WIKI_DIR = Path(__file__).parent.parent / ".wiki"
PAGES_DIR = WIKI_DIR / "pages"
ENTITIES_DIR = PAGES_DIR / "entities"
CONCEPTS_DIR = PAGES_DIR / "concepts"
INDEX_FILE = PAGES_DIR / "index.md"


def load_config():
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def atomic_write(path: Path, content: str):
    """Atomic file write (temp + rename, safe against partial writes)."""
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def call_llm(system_prompt: str, user_content: str, config: dict) -> str:
    llm = config.get("llm", {})
    api_url = llm.get("base_url", "https://api.deepseek.com").rstrip("/") + "/v1/chat/completions"

    payload = {
        "model": llm.get("model", "deepseek-v4-flash"),
        "temperature": llm.get("temperature", 0.3),
        "max_tokens": llm.get("max_tokens", 32000),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if llm.get("provider") == "deepseek":
        payload["thinking"] = {"type": "disabled"}

    api_key = llm.get("api_key", "")
    if not api_key:
        raise RuntimeError("LLM API key not configured. Set llm.api_key in wiki_config.yaml")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return (msg.get("content") or "").strip()
    except requests.RequestException as e:
        raise RuntimeError(f"LLM API call failed: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected LLM API response structure: {e}")


def write_audit(operation: str, details: dict):
    audit_file = WIKI_DIR / "audit.json"
    audit_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **details,
    }

    entries = []
    if audit_file.exists():
        try:
            entries = json.loads(audit_file.read_text(encoding="utf-8"))
        except:
            entries = []

    entries.append(entry)
    audit_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_contradictions(page_id: str, new_content: str, existing_content: str) -> list:
    config = load_config()

    system_prompt = """You are a contradiction detector for wiki pages.
Compare existing content with new content and identify contradictions.

Output JSON array of contradictions found:
[
  {
    "existing_claim": "Old claim text",
    "new_claim": "New claim text",
    "contradiction_type": "factual|temporal|numerical|opinion",
    "severity": "high|medium|low",
    "resolution_suggestion": "Which is more likely correct and why"
  }
]

If no contradictions, output: []

Be strict - only flag actual contradictions, not additions or clarifications."""

    user_prompt = f"""Page ID: {page_id}

EXISTING CONTENT:
{existing_content[:2000]}

NEW CONTENT:
{new_content[:2000]}

Find contradictions between existing and new content."""

    try:
        response = call_llm(system_prompt, user_prompt, config)
        return json.loads(response)
    except Exception:
        return []


def detect_language(text: str) -> str:
    """Detect if text is predominantly Chinese or English.

    Returns 'zh' if Chinese characters exceed threshold, 'en' otherwise.
    """
    if not text:
        return "en"
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    total = len(text)
    if total > 0 and cjk_count / total > 0.08:
        return "zh"
    return "en"


def compile_source(source_path: str, force: bool = False) -> dict:

    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source not found: {source_path}")

    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    content = strip_sensitive(content)

    source_name = os.path.basename(source_path)
    config = load_config()

    lang = detect_language(content)

    print(f"Compiling {source_name} ({len(content)} chars, {lang})...", file=sys.stderr)

    if lang == "zh":
        system_prompt = """你是 Wiki 构建助手。你必须用中文撰写所有内容。

## 实体 vs 概念（最重要！）
Karpathy 的 Wiki 设计区分两类页面：
- **entity（实体）**：具体的、可指认的事物。如组织架构、评审组、某个人、某个奖项。
- **concept（概念）**：抽象的、通用的思想。如"AI for Value 理念"、"数字化转 型战略"。

一个文档中通常 60% 是 entity，40% 是 concept。不要把一切归类为 concept。

## 关键要求
- id 和 name 都用中文（如 id: 评审标准, name: 评审标准）
- 所有标题用中文：概述、关键细节、关联关系、来源上下文
- 所有描述用中文撰写
- 文件名即为 id，所以 id 必须用中文

## Output Format
用 ===PAGE_END=== 分隔每个页面。

每个页面必须包含 YAML frontmatter：
---
id: 中文ID
type: entity|concept|process|rule|role|event
name: 中文名称
confidence: 0.85
source: source-name
---

然后按以下中文结构撰写内容：
# [中文标题]

## 概述
[2-4 句中文描述：这是什么，为什么重要]

## 关键细节
[具体细节，中文描述]

## 关联关系
- 使用/扩展/改进 [[其他实体]] — [中文简要说明]

## 来源上下文
> [文档中文原文摘录]

## 质量规则
- 每个文档提取 10-20 个重要页面
- 正确分类：具体事物→entity/role/event，抽象思想→concept，步骤→process，标准→rule
- entity 和 concept 的比例应大致为 6:4
- 描述要详实（不能只有一句话）
- 包含原文摘录

## 实体类型
- entity: 具体实体 — 组织、团队、部门、项目、产品（如"信息技术委员会"、"大赛筹备组"）
- concept: 核心概念/理念 — 抽象思想、价值观、战略方向（如"AI for Value 理念"）
- process: 流程/机制 — 步骤、阶段、工作流、审批链（如"报名流程"、"评审流程"）
- rule: 规则/标准 — 评审标准、参赛要求、合规条款（如"评审标准"、"作品要求"）
- role: 角色/职责 — 岗位分工、责任范围（如"专家评审组"的职责描述）
- event: 事件/活动 — 比赛、会议、里程碑、时间节点（如"路演答辩"、"颁奖典礼"）"""
    else:
        system_prompt = """You are a wiki builder. Your job is to read a document and write wiki pages.

## Entity vs Concept (MOST IMPORTANT!)
Karpathy's wiki design distinguishes two page types:
- **entity**: Concrete, nameable things. Organizations, people, projects, products.
- **concept**: Abstract ideas. Philosophies, mechanisms, strategies.

A document typically has ~60% entities and ~40% concepts. Don't default everything to concept.

## Output Format
Write pages separated by exactly this marker: ===PAGE_END===

Each page must start with YAML frontmatter:
---
id: entity-slug
type: entity|concept|process|rule|role|event|model|technique|framework|benchmark|paper
name: Display Name
confidence: 0.85
source: source-name
---

Then the page content with sections:
# [Title]

## Overview
[2-4 sentences: what it is, why it matters]

## Key Details
[Important details]

## Relationships
- uses/extends/improves [[other-entity]] — [brief explanation]

## Source Context
> [Relevant excerpt from document]

## Quality Rules
- Extract ONLY important entities (target 10-20 pages per document)
- Classify correctly: concrete things→entity, abstract ideas→concept
- ~60% entity, ~40% concept
- Merge variants: DeepSeek-V3.2, DeepSeek-V3-2 → single page deepseek-v3.2
- Use lowercase-hyphenated IDs: muon-optimizer, kv-cache
- Title Case names: "Muon Optimizer", "KV Cache"
- Substantive descriptions (not 1-line summaries)
- Include source excerpts

## Entity Types
- entity: Concrete things — people, orgs, teams, projects, products
- concept: Abstract ideas — philosophies, mechanisms, strategies
- process: Workflows — stages, procedures, pipelines
- rule: Standards — criteria, requirements, compliance
- role: Responsibilities — job functions, duty scopes
- event: Activities — meetings, milestones, ceremonies
- model: AI model variants (tech docs)
- technique: Technical methods (tech docs)
- framework: Infrastructure/platforms (tech docs)
- benchmark: Evaluation datasets (tech docs)
- paper: Publications (tech docs)"""

    if lang == "zh":
        user_prompt = f"""文档: {source_name}

内容:
{content}

请用中文提取该文档中的关键实体和概念，撰写 Wiki 页面。所有内容（标题、描述、关系说明）必须用中文。

关注点：核心概念、组织结构、流程机制、评估标准、参赛要求。
目标：10-20 个高质量中文页面，内容详实且相互关联。
用 ===PAGE_END=== 分隔每个页面。"""
    else:
        user_prompt = f"""Document: {source_name}

Content:
{content}

Write wiki pages for the key entities/concepts in this document.
Focus on: architecture innovations, model variants, techniques, benchmarks.
Target: 10-20 high-quality pages with substantive content.
Output pages separated by ===PAGE_END==="""
    print("Calling LLM...", file=sys.stderr)
    response = call_llm(system_prompt, user_prompt, config)

    pages = response.split("===PAGE_END===")

    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)

    created_pages = []
    updated_pages = []
    contradictions_found = []

    for page_content in pages:
        page_content = page_content.strip()
        if not page_content or not page_content.startswith("---"):
            continue

        lines = page_content.split("\n")
        frontmatter_end = 0
        for i, line in enumerate(lines):
            if i > 0 and line.strip() == "---":
                frontmatter_end = i
                break

        if frontmatter_end == 0:
            continue

        frontmatter_text = "\n".join(lines[1:frontmatter_end])
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except Exception as e:
            print(f"  WARNING: YAML parse failed — {e}", file=sys.stderr)
            continue

        entity_id = frontmatter.get("id", "")
        entity_type = frontmatter.get("type", "concept")

        if not entity_id:
            continue

        # Route to directories: concepts/ for abstract ideas, entities/ for concrete things
        concept_types = {"concept", "technique", "model", "framework", "benchmark", "paper"}
        target_dir = CONCEPTS_DIR if entity_type in concept_types else ENTITIES_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        page_path = target_dir / f"{entity_id}.md"

        if page_path.exists() and not force:
            existing_content = page_path.read_text(encoding="utf-8")
            contradictions = detect_contradictions(entity_id, page_content, existing_content)

            if contradictions:
                contradictions_found.extend(contradictions)
                page_content = existing_content + "\n\n## Contradictions Detected\n\n"
                for c in contradictions:
                    ctype = c.get('contradiction_type', 'unknown')
                    sev = c.get('severity', 'medium')
                    existing = c.get('existing_claim', 'N/A')
                    new = c.get('new_claim', 'N/A')
                    page_content += f"- **{ctype}** ({sev}): {existing} → {new}\n"
                atomic_write(page_path, page_content)
                updated_pages.append({
                    "id": entity_id,
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                    "contradictions": len(contradictions),
                })
                print(f"  Updated: {entity_id}.md ({len(contradictions)} contradictions)", file=sys.stderr)
            else:
                atomic_write(page_path, page_content)
                updated_pages.append({
                    "id": entity_id,
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                })
                print(f"  Updated: {entity_id}.md (reinforced)", file=sys.stderr)
        else:
            atomic_write(page_path, page_content)
            created_pages.append({
                "id": entity_id,
                "type": entity_type,
                "name": frontmatter.get("name", entity_id),
                "path": str(page_path),
            })
            print(f"  Created: {entity_id}.md ({entity_type})", file=sys.stderr)

    all_pages = created_pages + updated_pages
    if not all_pages:
        print(f"  WARNING: No pages parsed from LLM response! Raw output (500 chars):",
              file=sys.stderr)
        print(f"    {response[:500]}", file=sys.stderr)
        return {"source": source_name, "pages_created": 0, "pages_updated": 0, "pages": []}

    update_index(all_pages, source_name)
    update_log(source_name, len(created_pages), "compile")
    update_graph(all_pages, source_name)

    write_audit("compile", {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "contradictions": len(contradictions_found),
        "contradiction_details": contradictions_found[:10],
    })

    return {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "pages": all_pages,
        "contradictions_found": contradictions_found,
    }


def update_log(source_name: str, pages_count: int, operation: str = "compile"):
    """Update log.md with new operation."""
    log_file = WIKI_DIR / "log.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entry = f"\n## [{now}] {operation} | {source_name}\n- Pages created: {pages_count}\n"

    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
    else:
        content = "# Wiki Log\n\nChronological record of all wiki operations.\n"

    content += entry
    log_file.write_text(content, encoding="utf-8")


def update_graph(pages: list, source_name: str):
    graph_dir = WIKI_DIR / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    entities_file = graph_dir / "entities.json"
    edges_file = graph_dir / "edges.json"

    if entities_file.exists():
        entities = json.loads(entities_file.read_text(encoding="utf-8"))
    else:
        entities = {}

    if edges_file.exists():
        edges_data = json.loads(edges_file.read_text(encoding="utf-8"))
        edges = edges_data.get("edges", edges_data) if isinstance(edges_data, dict) else edges_data
    else:
        edges = []

    now = datetime.now(timezone.utc).isoformat()

    for page in pages:
        eid = page["id"]
        if eid not in entities:
            entities[eid] = {
                "id": eid,
                "type": page["type"],
                "name": page["name"],
                "sources": [source_name],
                "confidence": 0.85,
                "created": now,
                "last_confirmed": now,
                "reinforcement_count": 1,
            }
        else:
            if source_name not in entities[eid]["sources"]:
                entities[eid]["sources"].append(source_name)

            entities[eid]["reinforcement_count"] = entities[eid].get("reinforcement_count", 1) + 1
            entities[eid]["confidence"] = min(1.0, 0.85 + 0.05 * entities[eid]["reinforcement_count"])
            entities[eid]["last_confirmed"] = now

    for page in pages:
        page_path = Path(page.get("path", ""))
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            wikilinks = re.findall(r'\[\[([^\]|]+)', content)

            for target in wikilinks:
                target = target.strip().lower().replace(" ", "-")
                if target and target != page["id"]:
                    line_context = ""
                    normalized_content = content.lower().replace('-', ' ')
                    for line in content.split("\n"):
                        line_lower = line.lower()
                        line_normalized = line_lower.replace('-', ' ')
                        if (f"[[{target}" in line_normalized or
                            f"[[{target.replace('-', ' ')}" in line_normalized):
                            line_context = line
                            break

                    edge_type = extract_edge_type(line_context) if line_context else "relates_to"

                    edge = {
                        "source": page["id"],
                        "target": target,
                        "type": edge_type,
                        "weight": 1.0,
                        "source_file": source_name,
                    }

                    existing = [e for e in edges if e["source"] == page["id"] and e["target"] == target]
                    if not existing:
                        edges.append(edge)

    entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")
    edges_file.write_text(json.dumps({"edges": edges}, indent=2, ensure_ascii=False), encoding="utf-8")


def update_index(pages: list, source_name: str):
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)

    grouped = {
        "concept": {},
        "technique": {},
        "model": {},
        "framework": {},
        "benchmark": {},
        "paper": {},
    }

    # Merge existing index entries
    if INDEX_FILE.exists():
        for line in INDEX_FILE.read_text(encoding="utf-8").split("\n"):
            match = re.match(r'- \[\[([^\]|]+)(?:\|[^\]]+)?\]\] — (.+)', line)
            if match:
                eid, ptype = match.group(1), match.group(2)
                if ptype in grouped:
                    grouped[ptype][eid] = True

    for p in pages:
        ptype = p.get("type", "concept")
        if ptype in grouped:
            grouped[ptype][p.get("id", "")] = True

    lines = [
        "# Wiki Index",
        "",
        f"> Last compiled: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
        f"> Source: {source_name}",
        "",
    ]

    type_labels = {
        "concept": "Concepts",
        "technique": "Techniques",
        "model": "Models",
        "framework": "Frameworks",
        "benchmark": "Benchmarks",
        "paper": "Papers",
    }

    for ptype, label in type_labels.items():
        items = grouped[ptype]
        if items:
            lines.extend(["", f"## {label}", ""])
            for eid in sorted(items):
                name = eid.replace("-", " ").title()
                lines.append(f"- [[{eid}|{name}]] — {ptype}")

    atomic_write(INDEX_FILE, "\n".join(lines))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Simplified wiki compilation')
    parser.add_argument('source', help='Source file to compile')
    parser.add_argument('--force', action='store_true', help='Force re-compile (overwrite existing pages)')
    args = parser.parse_args()

    result = compile_source(args.source, force=args.force)

    pages_created = result.get('pages_created', 0)
    pages_updated = result.get('pages_updated', 0)
    print(f"\nCompiled {result['source']}: {pages_created} pages created, {pages_updated} pages updated")
    print("  → Updated log.md and graph/entities.json")


if __name__ == "__main__":
    main()
