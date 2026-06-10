#!/usr/bin/env python3
"""compile_v2.py — Simplified wiki compilation.
...
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    get_config,
    get_wiki_dir,
    get_llm_config,
    get_api_url,
    get_image_analysis_config,
    get_ocr_config,
)

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r'(?:sk|pk|rk)-(?:[a-zA-Z0-9]{20,})', '[REDACTED: API key]'),
    (r'(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}', '[REDACTED: GitHub token]'),
    (r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     '[REDACTED: Private key]'),
    (r'password\s*[=:]\s*\S+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]

KEYWORD_RELATION_MAP = [
    # English patterns
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
    # Chinese patterns
    (r'(?:使用|采用|利用|调用|借助|依据|通过)\s*\[\[', 'uses'),
    (r'(?:依赖|取决于|依赖于)\s*\[\[', 'depends_on'),
    (r'(?:扩展|继承|基于\s*)\s*\[\[', 'extends'),
    (r'(?:改进|优化|提升|增强)\s*\[\[', 'improves_upon'),
    (r'(?:矛盾|冲突|不一致|违背)\s*\[\[', 'contradicts'),
    (r'(?:取代|替代|替换\s*掉|淘汰)\s*\[\[', 'supersedes'),
    (r'(?:导致|引起|造成|触发|引发)\s*\[\[', 'caused_by'),
    (r'(?:修复|解决|修正|纠正)\s*\[\[', 'fixed_by'),
    (r'(?:替换|更换|换成|切换)\s*\[\[', 'replaces'),
    (r'(?:关联|相关|有关|涉及|对接|协作|配合|协调)\s*\[\[', 'relates_to'),
    (r'(?:属于|组成部分|包含于|隶属于)\s*\[\[', 'part_of'),
    (r'(?:实现|实施|执行|落实|负责|承担|主持)\s*\[\[', 'implemented_by'),
]

TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".html", ".htm", ".xml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb",
    ".sh", ".bash", ".zsh", ".sql", ".toml", ".ini", ".cfg",
}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".tiff", ".tif", ".avif", ".heic", ".heif", ".svg",
}
SKIP_DIR_NAMES = {".wiki", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
DEFAULT_ENTITY_TYPES = [
    "entity", "concept", "process", "rule", "role", "event",
    "model", "technique", "framework", "benchmark", "paper",
]
DEFAULT_RELATIONSHIP_TYPES = [
    "uses", "depends_on", "extends", "improves_upon", "contradicts",
    "supersedes", "caused_by", "fixed_by", "replaces", "relates_to",
    "part_of", "implemented_by",
]
CONCEPT_LIKE_TYPES = {"concept", "technique", "model", "framework", "benchmark", "paper", "pattern"}
INGEST_RULES = {
    "doc": (
        ["entity", "concept", "process", "rule", "role", "event"],
        "core concepts, named entities, processes, roles, rules, and events",
    ),
    "article": (
        ["concept", "entity", "model", "technique", "benchmark", "paper"],
        "claims, concepts, models, techniques, benchmarks, and cited work",
    ),
    "code": (
        ["entity", "concept", "framework", "tool", "file", "library", "decision"],
        "source files, libraries, tools, architectural decisions, and implementation patterns",
    ),
    "conversation": (
        ["decision", "concept", "entity", "process", "rule"],
        "decisions, findings, open questions, rules, and follow-up actions",
    ),
}

IMAGE_ANALYSIS_PROMPT = """Analyze this image for knowledge-base ingestion.

Return clean markdown in Chinese when the image contains Chinese; otherwise use the image's main language.

Required:
- Identify what the image is and what it contains.
- Preserve visible text, labels, headings, legends, axes, units, numbers, tables, and annotations.
- If it is a mind map, restore the hierarchy as nested bullet lists.
- If it is a flowchart or process diagram, restore steps, branches, dependencies, and direction.
- If it is a chart, restore chart type, series, axis meanings, numeric values, and trends.
- If it is a document screenshot, extract the text faithfully and keep section structure.
- Avoid generic visual descriptions when structured information is visible.
"""


def strip_sensitive(content: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def is_text_source(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def is_image_source(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_supported_source(path: Path) -> bool:
    return path.is_file() and (is_text_source(path) or is_image_source(path))


def iter_source_files(root: Path, max_depth: int | None = None) -> list[Path]:
    """Return supported source files under root, sorted for deterministic compiles.

    max_depth counts directory levels below root:
    - 0: only files directly under root
    - 1: include root's direct child directories
    - None: recurse through all subdirectories
    """
    files: list[Path] = []

    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        rel_parts = current_path.relative_to(root).parts
        depth = len(rel_parts)

        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIR_NAMES and not (current_path / d).is_symlink()
        )

        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []

        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                continue
            if is_supported_source(path):
                files.append(path)

    return files


def _ocr_image_with_config(image_path: Path) -> str:
    """Run the configured OCR backend on an image and return markdown text."""
    ocr_config = get_ocr_config()
    backend = ocr_config.get("backend", "mineru")

    if ocr_config.get("mode") == "api" or backend == "api":
        from ocr._ocr_api import OCRApiBackend
        return OCRApiBackend.from_config().ocr_image(str(image_path))
    if backend == "deepseek":
        from ocr._deepseek_ocr2 import DeepSeekOCR2
        return DeepSeekOCR2.from_config().ocr_image(str(image_path))
    if backend == "logics":
        from ocr._logics_parsing import LogicsParsingOCR
        return LogicsParsingOCR.from_config().ocr_image(str(image_path))
    if backend == "paddle":
        from ocr._paddle_ocr import PaddleOCRWrapper
        return PaddleOCRWrapper.from_config().ocr_image(str(image_path))
    from ocr._mineru_ocr import MinerUOCR
    return MinerUOCR.from_config().ocr_image(str(image_path))


def analyze_image_for_compile(image_path: Path) -> str:
    """Convert an image source to markdown for wiki compilation."""
    image_config = get_image_analysis_config()
    analysis = ""
    ocr_text = ""

    if image_config.get("enabled"):
        try:
            from ocr._ocr_api import create_vision_backend
            backend = create_vision_backend(image_config, IMAGE_ANALYSIS_PROMPT)
            analysis = backend.ocr_image(str(image_path))
        except Exception as e:
            print(f"  WARNING: image analysis failed for {image_path}: {e}", file=sys.stderr)

    should_ocr = bool(image_config.get("ocr_fallback", True))
    if should_ocr:
        min_chars = int(image_config.get("ocr_min_chars", 800) or 0)
        # Run OCR after visual analysis when the image likely contains dense text,
        # or when no enhanced analysis model is configured/available.
        if not analysis or len(analysis) >= min_chars:
            try:
                ocr_text = _ocr_image_with_config(image_path)
            except Exception as e:
                print(f"  WARNING: OCR fallback failed for {image_path}: {e}", file=sys.stderr)

    if not analysis and not ocr_text:
        raise RuntimeError(
            "Image compile requires image_analysis.enabled or a working OCR backend."
        )

    sections = [
        f"# Image Source: {image_path.name}",
        "",
        f"> Source image: {image_path.resolve()}",
        "",
    ]

    if analysis:
        sections.extend(["## Visual Analysis", "", analysis.strip(), ""])
    if ocr_text and ocr_text.strip() != analysis.strip():
        sections.extend(["## OCR Text", "", ocr_text.strip(), ""])

    return "\n".join(sections).strip() + "\n"


def read_source_content(source_path: str | Path) -> tuple[str, str]:
    """Read a compile source and return (content, display_name)."""
    path = Path(source_path)
    if is_image_source(path):
        return analyze_image_for_compile(path), path.name

    with open(path, encoding="utf-8") as f:
        return f.read(), path.name


def extract_edge_type(line: str) -> str:
    for pattern, rel_type in KEYWORD_RELATION_MAP:
        if re.search(pattern, line):
            return rel_type
    return "relates_to"


def _parse_schema_table(section_title: str) -> list[list[str]]:
    """Parse a backtick-based markdown table from schema.md."""
    if not SCHEMA_PATH.exists():
        return []

    rows: list[list[str]] = []
    in_section = False
    for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip() == section_title:
            in_section = True
            continue
        if in_section and line.startswith("## ") and line.strip() != section_title:
            break
        if in_section and line.startswith("| `"):
            parts = [part.strip().strip("`").strip() for part in line.split("|")[1:-1]]
            if parts:
                rows.append(parts)
    return rows


def load_entity_types_from_schema() -> tuple[list[str], str, str]:
    """Load entity and relationship type prompt context from .wiki/schema.md."""
    entity_rows = _parse_schema_table("## Entity Types")
    rel_rows = _parse_schema_table("## Relationship Types")

    entity_types: list[str] = []
    entity_lines: list[str] = []
    for row in entity_rows:
        if len(row) >= 3 and row[0] and row[0] != "type":
            entity_types.append(row[0])
            entity_lines.append(f"- **{row[0]}**: {row[2]}")

    rel_types: list[str] = []
    rel_lines: list[str] = []
    for row in rel_rows:
        if row and row[0] and row[0].lower() != "type":
            rel_types.append(row[0])
            meaning = row[2] if len(row) >= 3 else f"entity A {row[0]} entity B"
            rel_lines.append(f"- **{row[0]}**: {meaning}")

    for entity_type in DEFAULT_ENTITY_TYPES:
        if entity_type not in entity_types:
            entity_types.append(entity_type)
            entity_lines.append(f"- **{entity_type}**: {entity_type} page")

    for rel_type in DEFAULT_RELATIONSHIP_TYPES:
        if rel_type not in rel_types:
            rel_lines.append(f"- **{rel_type}**: entity A {rel_type} entity B")

    return entity_types, "\n".join(entity_lines), "\n".join(rel_lines)


def load_ingest_rules_from_schema(source_type: str) -> tuple[list[str], str]:
    """Return source-type focus rules for compile prompts."""
    return INGEST_RULES.get(source_type, INGEST_RULES["doc"])

def load_config():
    return get_config()


def get_paths():
    wiki_dir = get_wiki_dir()
    return {
        "wiki_dir": wiki_dir,
        "pages_dir": wiki_dir / "pages",
        "entities_dir": wiki_dir / "pages" / "entities",
        "concepts_dir": wiki_dir / "pages" / "concepts",
        "index_file": wiki_dir / "pages" / "index.md",
        "schema_path": wiki_dir / "schema.md",
        "graph_dir": wiki_dir / "graph",
    }

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
ENTITIES_DIR = PAGES_DIR / "entities"
CONCEPTS_DIR = PAGES_DIR / "concepts"
INDEX_FILE = PAGES_DIR / "index.md"
SCHEMA_PATH = WIKI_DIR / "schema.md"
GRAPH_DIR = WIKI_DIR / "graph"


def atomic_write(path: Path, content: str):
    """Atomic file write (temp + rename, safe against partial writes)."""
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def call_llm(system_prompt: str, user_content: str, config: dict) -> str:
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
            "max_tokens": llm_config.get("max_tokens", 32000),
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
        payload = {
            "model": llm_config.get("model", "deepseek-v4-flash"),
            "temperature": llm_config.get("temperature", 0.3),
            "max_tokens": llm_config.get("max_tokens", 32000),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        
        api_key = llm_config.get("api_key", "")
        if not api_key:
            raise RuntimeError("LLM API key not configured. Set llm.api_key in wiki_config.yaml or DEEPSEEK_API_KEY env var")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=600)
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
        except (json.JSONDecodeError, OSError):
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


def auto_resolve_contradictions(page_id: str, contradictions: list[dict]) -> list[dict]:
    """Return conservative contradiction resolutions without overwriting claims.

    Compile should never abort because a reinforcement conflicts with an
    existing page. The safe default is to flag each contradiction for review
    and preserve both claims in the page history.
    """
    resolutions: list[dict] = []
    for contradiction in contradictions:
        suggestion = str(contradiction.get("resolution_suggestion", "")).strip()
        severity = str(contradiction.get("severity", "medium")).lower()
        confidence = 0.35 if severity == "high" else 0.5
        resolutions.append({
            "page_id": page_id,
            "winner": "manual_review",
            "confidence": confidence,
            "reasoning": suggestion or "Contradiction detected during compile; preserved for manual review.",
            "action": "flag",
        })
    return resolutions


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


def compile_source(source_path: str, source_type: str = "doc", force: bool = False) -> dict:

    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source not found: {source_path}")

    source_file = Path(source_path)
    if source_file.is_dir():
        return compile_path(source_path, source_type=source_type, force=force)

    content, source_name = read_source_content(source_file)

    content = strip_sensitive(content)

    config = load_config()

    lang = detect_language(content)
    entity_types, entity_type_lines, rel_type_lines = load_entity_types_from_schema()
    focus_types, focus_desc = load_ingest_rules_from_schema(source_type)
    entity_type_str = "|".join(entity_types)

    print(f"Compiling {source_name} ({len(content)} chars, {lang}, {source_type})...", file=sys.stderr)
    print(f"  Focus: {', '.join(focus_types)} — {focus_desc}", file=sys.stderr)

    if lang == "zh":
        # Derive a short source abbreviation for ID prefix
        import re as _re
        source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', source_name)[:8].lower() or "doc"
        system_prompt = f"""你是 Wiki 构建助手。你必须用中文撰写所有内容。

## ID 命名规则（最重要！防止同名覆盖）
文档源简称: {source_abbr}

- **实体页 ID**: `{{source_abbr}}-{{实体名}}` — 确保不同来源的同名实体不覆盖
  例: `{source_abbr}-专家评审组`, `{source_abbr}-评审标准`
- **概念页 ID**: 直接使用概念名 — 跨文档共享，由系统自动聚合
  例: `专家评审组`, `评审标准`

## 实体 vs 概念（严格区分！）
- **entity/role/rule/process/event**: 具体事物 — 某个组织的评审组、某份方案的评分标准、某个活动的流程。**必须带 source 前缀**，因为每份文档的实例不同。
- **concept**: 跨文档的抽象模式 — "AI for Value 理念"、"数字化转型"这种通用思想。**不带前缀**，系统会自动聚合所有来源的信息。

一个文档中 60-70% 是实体（entity/role/rule/process/event），30-40% 是概念（concept）。

## 关键要求
- 实体页 ID 必须带 {source_abbr} 前缀
- 概念页 ID 不带前缀
- name 字段用中文（如"专家评审组"）
- 所有标题用中文：概述、关键细节、关联关系、来源上下文
- 所有描述用中文撰写

## Output Format
用 ===PAGE_END=== 分隔每个页面。

每个页面必须包含 YAML frontmatter：
---
id: 实体ID或概念ID
type: {entity_type_str}
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

## 关联关系（必须用下列关键词开头！）
- 使用 [[other]] — 说明
- 依赖 [[other]] — 说明
- 属于 [[other]] — 说明
- 负责 [[other]] — 说明
- 关联 [[other]] — 说明
可选关键词：扩展、改进、取代、导致、修复、替换、实现、base、矛盾

## 来源上下文
> [文档中文原文摘录]

## 质量规则
- 每个文档提取 10-20 个重要页面
- 实体（entity/role/rule/process/event）→ ID 带 {source_abbr} 前缀
- 概念（concept）→ ID 不带前缀
- 实体:概念比例约 6:4
- 描述要详实（不能只有一句话）
- 包含原文摘录

## 实体类型
{entity_type_lines}"""
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

## Relationships (MUST start with one of these keywords!)
- uses [[other]] — explanation
- depends on [[other]] — explanation
- extends [[other]] — explanation
- improves [[other]] — explanation
- contradicts [[other]] — explanation
- supersedes [[other]] — explanation
- caused by [[other]] — explanation
- fixed by [[other]] — explanation
- part of [[other]] — explanation
- relates to [[other]] — explanation

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
{entity_type_lines}"""

    if lang == "zh":
        user_prompt = f"""文档: {source_name}

内容:
{content}

请用中文提取该文档中的关键实体和概念，撰写 Wiki 页面。所有内容（标题、描述、关系说明）必须用中文。

重要：实体（entity/role/rule/process/event）的 ID 必须带 {source_abbr} 前缀，概念（concept）不带前缀。
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

    # Derive source abbreviation for entity ID prefix
    import re as _re
    src_stem = Path(source_name).stem
    source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', src_stem)[:8].lower() or "doc"
    concept_types = CONCEPT_LIKE_TYPES
    # Track which entity IDs need concept pages (base name → list of instance IDs)
    concept_groups: dict[str, list[dict]] = {}

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

        # Determine target directory
        target_dir = CONCEPTS_DIR if entity_type in concept_types else ENTITIES_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        page_path = target_dir / f"{entity_id}.md"

        # ── 同名异实保护：如果已存在同名实体页（非 concept 类型），自动加前缀 ──
        # 即使 force 模式也检测——force 只允许覆盖同源页面，不能覆盖跨源实体
        if entity_type not in concept_types and page_path.exists():
            existing_content = page_path.read_text(encoding="utf-8")
            existing_source = ""
            for line in existing_content.split("\n"):
                if line.startswith("source:"):
                    existing_source = line.replace("source:", "").strip()
                    break
            # If existing page is from a DIFFERENT source, prefix the new one
            if existing_source and existing_source != source_name:
                prefixed_id = f"{source_abbr}-{entity_id}"
                page_path = ENTITIES_DIR / f"{prefixed_id}.md"
                frontmatter["id"] = prefixed_id
                page_lines = page_content.split("\n")
                fm_start = page_lines.index("---")
                fm_end = page_lines.index("---", fm_start + 1)
                new_fm = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip()
                page_content = "---\n" + new_fm + "\n---\n" + "\n".join(page_lines[fm_end + 1:])

                # Register for concept aggregation
                base_name = entity_id
                if base_name not in concept_groups:
                    concept_groups[base_name] = []
                concept_groups[base_name].append({"id": prefixed_id, "type": entity_type, "name": frontmatter.get("name", entity_id)})
                print(f"  Conflict → prefixed: {prefixed_id}.md", file=sys.stderr)

        if page_path.exists() and not force:
            existing_content = page_path.read_text(encoding="utf-8")
            contradictions = detect_contradictions(entity_id, page_content, existing_content)

            if contradictions:
                contradictions_found.extend(contradictions)
                resolutions = auto_resolve_contradictions(entity_id, contradictions)
                
                page_content = existing_content + "\n\n## Contradictions Detected\n\n"
                for c in contradictions:
                    ctype = c.get('contradiction_type', 'unknown')
                    sev = c.get('severity', 'medium')
                    existing = c.get('existing_claim', 'N/A')
                    new = c.get('new_claim', 'N/A')
                    page_content += f"- **{ctype}** ({sev}): {existing} → {new}\n"
                
                if resolutions:
                    page_content += "\n## Resolution\n\n"
                    for i, r in enumerate(resolutions):
                        winner = r.get("winner", "unknown")
                        conf = r.get("confidence", 0.5)
                        reasoning = r.get("reasoning", "")
                        action = r.get("action", "flag")
                        page_content += f"- **Resolved #{i+1}**: {winner} claim accepted ({action}) — confidence {conf:.0%}\n"
                        page_content += f"  - Reasoning: {reasoning}\n"
                        if action == "supersede":
                            page_content += "  - [SUPERSEDED] Old claim marked as superseded.\n"
                
                atomic_write(page_path, page_content)
                updated_pages.append({
                    "id": frontmatter.get("id", entity_id),
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                    "contradictions": len(contradictions),
                    "resolutions": len(resolutions),
                })
                print(f"  Updated: {Path(page_path).name} ({len(contradictions)} contradictions, {len(resolutions)} resolved)", file=sys.stderr)
            else:
                atomic_write(page_path, page_content)
                updated_pages.append({
                    "id": frontmatter.get("id", entity_id),
                    "type": entity_type,
                    "name": frontmatter.get("name", entity_id),
                    "path": str(page_path),
                })
                print(f"  Updated: {Path(page_path).name} (reinforced)", file=sys.stderr)
        else:
            atomic_write(page_path, page_content)
            created_pages.append({
                "id": frontmatter.get("id", entity_id),
                "type": entity_type,
                "name": frontmatter.get("name", entity_id),
                "path": str(page_path),
            })
            print(f"  Created: {Path(page_path).name} ({entity_type})", file=sys.stderr)

    all_pages = created_pages + updated_pages
    if not all_pages:
        print(f"  WARNING: No pages parsed from LLM response! Raw output (500 chars):",
              file=sys.stderr)
        print(f"    {response[:500]}", file=sys.stderr)
        return {"source": source_name, "pages_created": 0, "pages_updated": 0, "pages": []}

    # ── 概念聚合：为每个实体组创建/更新概念页（同名异实保护） ──
    for base_name, instances in concept_groups.items():
        concept_path = CONCEPTS_DIR / f"{base_name}.md"
        instance_links = "\n".join(
            f"- [[{inst['id']}]] — {inst.get('name', inst['id'])}（来源: {source_name}）"
            for inst in instances
        )
        # Also find existing non-prefixed entities with the same base name
        existing_entity = ENTITIES_DIR / f"{base_name}.md"
        if existing_entity.exists():
            existing_source = ""
            for line in existing_entity.read_text(encoding="utf-8").split("\n"):
                if line.startswith("source:"):
                    existing_source = line.replace("source:", "").strip()
                    break
            existing_link = f"- [[{base_name}]] — {base_name}（来源: {existing_source}）"
            if existing_link not in instance_links:
                instance_links = existing_link + "\n" + instance_links

        if concept_path.exists():
            existing = concept_path.read_text(encoding="utf-8")
            new_links = [l for l in instance_links.split("\n") if l not in existing]
            if new_links:
                # Append new instances
                updated_content = existing.rstrip() + "\n\n## 新增实例\n\n" + "\n".join(new_links) + "\n"
                atomic_write(concept_path, updated_content)
                print(f"  Concept updated: {base_name}.md (+{len(new_links)} instances)", file=sys.stderr)
        else:
            # Use LLM to synthesize a concept page from entity instances
            entity_summaries = []
            for inst in instances:
                ep_path = ENTITIES_DIR / f"{inst['id']}.md"
                if ep_path.exists():
                    ep_content = ep_path.read_text(encoding="utf-8")
                    overview_lines = []
                    capture = False
                    for line in ep_content.split("\n"):
                        if line.startswith("## 概述") or line.startswith("## Overview"):
                            capture = True
                            continue
                        if capture and line.startswith("## "):
                            break
                        if capture and line.strip():
                            overview_lines.append(line.strip())
                    entity_summaries.append(f"### {inst['name']}\n{' '.join(overview_lines[:3])}")

            synthesis_prompt = f"""综合以下实体实例，生成一个跨文档概念页。

概念: {base_name}
实例列表:
{instance_links}

实例详情:
{chr(10).join(entity_summaries[:3])}

输出（YAML frontmatter + 中文内容）：
---
id: {base_name}
type: concept
name: {base_name}
confidence: 0.85
source: 跨文档聚合
---

# {base_name}

## 概述
[综合所有实例，提炼通用模式和核心特征，2-4句中文]

## 已知实例
{instance_links}

## 关键特征
[从各实例提炼的共同点和差异性，3-5条中文]

直接输出，不要额外说明。"""
            try:
                concept_content = call_llm(
                    "你是 Wiki 知识聚合助手，综合多个来源的同类实体，生成概念页。",
                    synthesis_prompt,
                    config,
                )
                atomic_write(concept_path, concept_content.strip())
                print(f"  Concept created: {base_name}.md ({len(instances)} instances)", file=sys.stderr)
            except Exception:
                fallback = f"""---
id: {base_name}
type: concept
name: {base_name}
confidence: 0.80
source: 跨文档聚合
---

# {base_name}

## 概述
跨文档概念，聚合自 {source_name}。

## 已知实例
{instance_links}
"""
                atomic_write(concept_path, fallback)
                print(f"  Concept created (fallback): {base_name}.md", file=sys.stderr)

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


def compile_path(
    source_path: str,
    source_type: str = "doc",
    force: bool = False,
    depth: int | None = None,
) -> dict:
    """Compile a single source file or every supported file under a directory."""
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if path.is_file():
        return compile_source(str(path), source_type=source_type, force=force)

    if depth is not None and depth < 0:
        raise ValueError("--depth must be >= 0")

    sources = iter_source_files(path, max_depth=depth)
    if not sources:
        return {
            "source": str(path),
            "directory": True,
            "files_found": 0,
            "compiled": [],
            "failed": [],
            "pages_created": 0,
            "pages_updated": 0,
        }

    compiled = []
    failed = []
    pages_created = 0
    pages_updated = 0

    print(f"Compiling directory {path} ({len(sources)} files)...", file=sys.stderr)
    for source in sources:
        try:
            result = compile_source(str(source), source_type=source_type, force=force)
            compiled.append(result)
            pages_created += result.get("pages_created", 0)
            pages_updated += result.get("pages_updated", 0)
        except Exception as e:
            failed.append({"source": str(source), "error": str(e)})
            print(f"  ERROR: failed to compile {source}: {e}", file=sys.stderr)

    return {
        "source": str(path),
        "directory": True,
        "files_found": len(sources),
        "compiled": compiled,
        "failed": failed,
        "pages_created": pages_created,
        "pages_updated": pages_updated,
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
    parser = argparse.ArgumentParser(description='Wiki compilation')
    parser.add_argument('source', help='Source file or directory to compile')
    parser.add_argument('--type', dest='source_type', default='doc',
                        choices=['doc', 'article', 'code', 'conversation'],
                        help='Source type (controls entity focus)')
    parser.add_argument('--force', action='store_true', help='Force re-compile (overwrite existing pages)')
    parser.add_argument('--depth', type=int, default=None,
                        help='Directory recursion depth: 0 = direct files only, omit = all subdirectories')
    args = parser.parse_args()

    result = compile_path(args.source, source_type=args.source_type, force=args.force, depth=args.depth)

    pages_created = result.get('pages_created', 0)
    pages_updated = result.get('pages_updated', 0)
    if result.get("directory"):
        failed = len(result.get("failed", []))
        print(
            f"\nCompiled {result['source']}: {len(result.get('compiled', []))}/"
            f"{result.get('files_found', 0)} files, {pages_created} pages created, "
            f"{pages_updated} pages updated, {failed} failed"
        )
    else:
        print(f"\nCompiled {result['source']}: {pages_created} pages created, {pages_updated} pages updated")
    print("  → Updated log.md and graph/entities.json")


if __name__ == "__main__":
    main()
