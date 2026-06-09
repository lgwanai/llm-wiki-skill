from __future__ import annotations
"""_llm_extract.py — LLM-based entity and relationship extraction.

Configuration: see ../wiki_config.yaml
(OpenAI-compatible) to extract structured knowledge from source text.

Entity types and relationship types are defined in .wiki/schema.md.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import get_wiki_dir

CONFIG_PATH = Path(__file__).parent.parent / "wiki_config.yaml"
WIKI_DIR = get_wiki_dir()
SCHEMA_PATH = WIKI_DIR / "schema.md"

ENTITY_TYPES = []
RELATIONSHIP_TYPES = []


def _load_schema_types() -> tuple[list[str], list[str], dict[str, str], dict[str, str]]:
    """Parse entity types, relationship types, dir map, and descriptions from schema.md."""
    defaults_entities = ["person", "project", "library", "concept", "file", "decision", "pattern", "tool"]
    defaults_rels = ["uses", "variant_of", "extends", "related_to", "feeds_into"]

    if not SCHEMA_PATH.exists():
        return (defaults_entities, defaults_rels, {}, {t: f"entities of type {t}" for t in defaults_entities})

    text = SCHEMA_PATH.read_text(encoding="utf-8")
    entity_types = []
    rel_types = []
    dir_map = {}
    desc_map = {}

    in_entity_table = False
    for line in text.split("\n"):
        if "## Entity Types" in line:
            in_entity_table = True
            continue
        if in_entity_table and line.startswith("## ") and "Entity" not in line:
            in_entity_table = False
            continue
        if in_entity_table and line.startswith("| `"):
            parts = [p.strip("` ") for p in line.split("|")[1:-1]]
            if len(parts) >= 3:
                etype = parts[0]
                directory = parts[1]
                desc = parts[2] if len(parts) > 2 else f"entities of type {etype}"
                entity_types.append(etype)
                dir_map[etype] = directory
                desc_map[etype] = desc

    in_rel_table = False
    for line in text.split("\n"):
        if "## Relationship Types" in line:
            in_rel_table = True
            continue
        if in_rel_table and line.startswith("## ") and "Relationship" not in line:
            in_rel_table = False
            continue
        if in_rel_table and line.startswith("| `"):
            parts = [p.strip("` ") for p in line.split("|")[1:-1]]
            if len(parts) >= 1 and parts[0]:
                rel_types.append(parts[0])

    return entity_types, rel_types, dir_map, desc_map


# Initialize from schema
ENTITY_TYPES, RELATIONSHIP_TYPES, ENTITY_TYPE_DIRS, ENTITY_DESCRIPTIONS = _load_schema_types()


def get_entity_dir(entity_type: str) -> str:
    """Get page directory for an entity type (from schema)."""
    return ENTITY_TYPE_DIRS.get(entity_type, "entities")


def get_all_types() -> list[str]:
    return list(ENTITY_TYPES)


def get_all_relationships() -> list[str]:
    return list(RELATIONSHIP_TYPES)

# Build extraction prompt from schema types
_type_lines = "\n".join(
    f"- **{t}**: {ENTITY_DESCRIPTIONS.get(t, f'entities of type {t}')}"
    for t in ENTITY_TYPES
)
_rel_lines = "\n".join(f"- **{r}**: entity A {r} entity B" for r in RELATIONSHIP_TYPES)

EXTRACTION_PROMPT = f"""You are building a knowledge wiki. Extract ONLY the most important entities and relationships.

## Entity Types
{_type_lines}

## Relationship Types
{_rel_lines}

## CRITICAL RULES

### 1. Entity Consolidation (MOST IMPORTANT)
**Normalize entity names to canonical forms. These are THE SAME entity:**
- "DeepSeek-V3.2", "DeepSeek-V3-2", "deepseek-v3.2", "DeepSeek V3.2" → use `deepseek-v3.2`
- "DeepSeek-V4-Pro", "deepseek-v4-pro", "DeepSeek V4 Pro" → use `deepseek-v4-pro`
- "CSA", "Compressed Sparse Attention", "compressed-sparse-attention" → use `compressed-sparse-attention`
- "mHC", "Manifold-Constrained Hyper-Connections", "manifold-constrained-hyper-connections" → use `manifold-constrained-hyper-connections`

**ID format**: lowercase-with-hyphens (e.g., `muon-optimizer`, `kv-cache`)
**Name format**: Title Case (e.g., "Muon Optimizer", "KV Cache")

### 2. Entity Type Classification
- `concept`: Core architecture/mechanism (attention mechanisms, compression, optimization algorithms)
- `model`: AI model series or variants (DeepSeek-V4, GPT-5.4, Gemini-3.1-Pro)
- `technique`: Training methods (GRPO, on-policy distillation, QAT)
- `benchmark`: Evaluation datasets (MMLU, GPQA, SimpleQA)
- `paper`: Academic publications with authors
- `framework`: Infrastructure (TileLang, TVM, CUDA)
- `library`: Dependencies (DeepGEMM, cuBLAS)
- `person`: Individual authors/researchers

### 3. Quality Over Quantity
**Extract ONLY:**
- Core concepts and mechanisms (as `concept`) - typically 5-10 per document
- Main model/technique entities (as `model` or `technique`) - typically 2-5
- Key benchmarks (as `benchmark`) - typically 3-8
- Important papers with authors (as `paper` + `person`) - typically 2-5

**DO NOT extract:**
- Minor mentions without substance
- Generic terms (the, a, both, them)
- Numbers alone
- Redundant variants (use canonical form)

### 4. Detailed Descriptions
Each entity MUST have a substantive description (2-4 sentences):
- What it is
- Why it matters
- How it relates to the main topic

## Output Format
{{
  "entities": [
    {{
      "id": "canonical-slug",
      "name": "Display Name",
      "type": "concept",
      "description": "2-4 sentence substantive description explaining what it is and why it matters"
    }}
  ],
  "relationships": [
    {{"source": "entity-a", "target": "entity-b", "type": "uses", "description": "A uses B for X"}}
  ],
  "main_entity": "canonical-slug"
}}

Output ONLY valid JSON. Target 15-30 high-quality entities per document.

## Document to Analyze

"""


class LLMExtractor:
    """LLM-based entity and relationship extractor."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 32768,
    ):
        self.api_url = base_url.rstrip("/") + "/v1/chat/completions"
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @classmethod
    def from_config(cls, path: Path | None = None) -> "LLMExtractor":
        """Create instance from YAML config or environment variables."""
        import os as _os
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from config import get_llm_config

        llm = get_llm_config()

        return cls(
            api_key=llm.get("api_key") or _os.environ.get("LLM_API_KEY", ""),
            base_url=llm.get("base_url") or _os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
            model=llm.get("model") or _os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
            temperature=llm.get("temperature", 0.3),
        )

    def _call(self, system_prompt: str, user_content: str, enable_thinking: bool = False) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": self.max_tokens,
        }
        if not enable_thinking:
            payload["thinking"] = {"type": "disabled"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return (msg.get("content") or msg.get("reasoning_content") or "").strip()

    def _chunk_text(self, text: str, max_chars: int = 3000) -> list[str]:
        """Split text into chunks using \n\n separator, max 3000 chars per chunk."""
        if len(text) <= max_chars:
            return [text]

        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < max_chars:
                current += p + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                # If single paragraph exceeds max_chars, split it further
                if len(p) > max_chars:
                    # Split by sentences for very long paragraphs
                    sentences = re.split(r'(?<=[.!?])\s+', p)
                    sub_chunk = ""
                    for s in sentences:
                        if len(sub_chunk) + len(s) < max_chars:
                            sub_chunk += s + " "
                        else:
                            if sub_chunk:
                                chunks.append(sub_chunk.strip())
                            sub_chunk = s + " "
                    if sub_chunk:
                        chunks.append(sub_chunk.strip())
                    current = ""
                else:
                    current = p + "\n\n"
        if current:
            chunks.append(current.strip())
        return chunks

    def _build_schema_context(self) -> str:
        """Build entity type context from schema.md."""
        types_desc = ", ".join(get_all_types())
        rels_desc = ", ".join(get_all_relationships())
        return f"Entity types: {types_desc}\nRelationship types: {rels_desc}"

    def _normalize_entity_id(self, eid: str) -> str:
        """Normalize entity ID to canonical form (lowercase, consistent hyphens)."""
        normalized = eid.lower().strip()
        normalized = re.sub(r'[\s_]+', '-', normalized)
        normalized = re.sub(r'-+', '-', normalized)
        normalized = normalized.strip('-')

        # Common normalization patterns
        patterns = {
            r'v(\d+)-(\d+)': r'v\1.\2',  # v3-2 → v3.2
            r'-(\d+)$': r'.\1',           # deepseek-v3-2 → deepseek-v3.2
        }
        for pattern, replacement in patterns.items():
            normalized = re.sub(pattern, replacement, normalized)

        return normalized

    def _find_similar_entity(self, eid: str, existing_entities: dict) -> str | None:
        """Find if a similar entity already exists. Returns canonical ID or None."""
        normalized = self._normalize_entity_id(eid)

        for existing_id in existing_entities:
            existing_normalized = self._normalize_entity_id(existing_id)
            if normalized == existing_normalized:
                return existing_id

            # Check for minor variations
            if abs(len(normalized) - len(existing_normalized)) <= 3:
                # Levenshtein-like check for very similar names
                if normalized.replace('-', '') == existing_normalized.replace('-', ''):
                    return existing_id
                if normalized.replace('.', '-') == existing_normalized.replace('.', '-'):
                    return existing_id

        return None

    def extract(self, text: str, source_name: str = "", max_workers: int = 5) -> dict:
        """Extract entities and relationships from text using LLM with concurrent calls."""
        chunks = self._chunk_text(text)

        if len(chunks) == 1:
            prompt = EXTRACTION_PROMPT + text[:30000]
            response = self._call(
                "You are a precise knowledge extraction system. Always output valid JSON.",
                prompt,
                enable_thinking=False,
            )
            try:
                return self._parse_response(response)
            except Exception as e:
                print(f"  Parse error: {e}", file=sys.stderr)
                print(f"  Raw response (first 500 chars): {response[:500]}", file=sys.stderr)
                return {"entities": [], "relationships": []}

        all_entities = []
        all_relationships = []
        entity_registry = {}

        def extract_chunk(chunk_data: tuple[int, str]) -> dict:
            i, chunk = chunk_data
            prompt = f"{EXTRACTION_PROMPT}Chunk {i+1}/{len(chunks)}\n\n{chunk[:30000]}"
            try:
                response = self._call(
                    "You are a precise knowledge extraction system. Always output valid JSON.",
                    prompt,
                    enable_thinking=False,
                )
                result = self._parse_response(response)
                return {"index": i, "result": result, "success": True}
            except Exception as e:
                return {"index": i, "error": str(e), "success": False}

        print(f"    Processing {len(chunks)} chunks concurrently with {max_workers} workers ...", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(extract_chunk, (i, chunk)) for i, chunk in enumerate(chunks)]

            for future in as_completed(futures):
                result_data = future.result()
                i = result_data["index"]

                if result_data["success"]:
                    result = result_data["result"]
                    print(f"    Chunk {i+1}/{len(chunks)} ✓ ({len(chunks[i])} chars)", file=sys.stderr)
                    for entity in result.get("entities", []):
                        eid = entity["id"]
                        similar_id = self._find_similar_entity(eid, entity_registry)

                        if similar_id:
                            entity_registry[similar_id]['confidence'] = min(1.0,
                                entity_registry[similar_id].get('confidence', 0.5) + 0.1)
                            entity_registry[similar_id].setdefault('aliases', []).append(eid)
                        else:
                            canonical_id = self._normalize_entity_id(eid)
                            entity['id'] = canonical_id
                            entity_registry[canonical_id] = entity
                            all_entities.append(entity)

                    for rel in result.get("relationships", []):
                        source = rel.get("source", "")
                        target = rel.get("target", "")
                        normalized_source = self._normalize_entity_id(source)
                        normalized_target = self._normalize_entity_id(target)

                        if normalized_source in entity_registry or normalized_target in entity_registry:
                            rel["source"] = normalized_source
                            rel["target"] = normalized_target
                            all_relationships.append(rel)
                else:
                    print(f"    Chunk {i+1}/{len(chunks)} ✗ Error: {result_data['error']}", file=sys.stderr)

        main_entity_candidates = [e for e in all_entities if e.get("type") in ["model", "concept"]]
        main_entity = main_entity_candidates[0]["id"] if main_entity_candidates else (all_entities[0]["id"] if all_entities else source_name)

        print(f"    Extracted: {len(all_entities)} unique entities, {len(all_relationships)} relationships", file=sys.stderr)

        return {
            "entities": all_entities,
            "relationships": all_relationships,
            "main_entity": main_entity,
        }

    def _parse_response(self, response: str) -> dict:
        """Parse LLM JSON response, with robust error handling."""
        # Remove markdown code blocks
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            response = json_match.group(1).strip()

        # Find JSON object
        start = response.find("{")
        end = response.rfind("}")
        if start >= 0 and end > start:
            response = response[start:end + 1]

        # Try direct parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Fix common LLM JSON issues
        response = re.sub(r',\s*}', '}', response)     # trailing commas
        response = re.sub(r',\s*]', ']', response)     # trailing commas in arrays
        response = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', response)  # control chars

        # Try to find and fix broken strings by completing them
        # If response ends in the middle of a string, try to close it
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            # Try to truncate at error position
            error_pos = e.pos
            response_fixed = response[:error_pos]
            # Close any open structures
            open_braces = response_fixed.count('{') - response_fixed.count('}')
            open_brackets = response_fixed.count('[') - response_fixed.count(']')
            response_fixed += ']' * open_brackets
            response_fixed += '}' * open_braces
            try:
                return json.loads(response_fixed)
            except json.JSONDecodeError:
                pass

        return {"entities": [], "relationships": []}
