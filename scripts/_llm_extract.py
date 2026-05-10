"""_llm_extract.py — LLM-based entity and relationship extraction.

Loads configuration from wiki_config.yaml. Calls a remote LLM API
(OpenAI-compatible) to extract structured knowledge from source text.

Entity types and relationship types are defined in .wiki/schema.md.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests
import yaml

CONFIG_PATH = Path(__file__).parent / "wiki_config.yaml"
WIKI_DIR = Path(__file__).parent.parent / ".wiki"
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

EXTRACTION_PROMPT = f"""You are a knowledge graph builder. Analyze the following document and extract ALL significant entities and their relationships.

## Entity Types (choose the most appropriate for each entity)
{_type_lines}

## Relationship Types
{_rel_lines}

## Requirements
1. Extract every significant entity mentioned - be thorough
2. For each entity provide: id (slug), name (display), type (from the list above), brief description (1-2 sentences)
3. Describe relationships between entities using the types above
4. Identify the main entity and group related entities under it
5. Output ONLY valid JSON, no preamble or explanation

## Output Format
{{
  "entities": [
    {{"id": "entity-slug", "name": "Display Name", "type": "concept", "description": "Brief 1-2 sentence description"}}
  ],
  "relationships": [
    {{"source": "entity-a", "target": "entity-b", "type": "uses", "description": "A uses B for X"}}
  ],
  "main_entity": "entity-slug"
}}

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
    def from_config(cls, path: Optional[Path] = None) -> "LLMExtractor":
        config_path = path or CONFIG_PATH
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        llm = config["llm"]
        return cls(
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
            temperature=llm.get("temperature", 0.3),
        )

    def _call(self, system_prompt: str, user_content: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return (msg.get("content") or msg.get("reasoning_content") or "").strip()

    def _chunk_text(self, text: str, max_chars: int = 40000) -> list[str]:
        """Split text into chunks that fit the model's context window."""
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
                current = p + "\n\n"
        if current:
            chunks.append(current.strip())
        return chunks

    def _build_schema_context(self) -> str:
        """Build entity type context from schema.md."""
        types_desc = ", ".join(get_all_types())
        rels_desc = ", ".join(get_all_relationships())
        return f"Entity types: {types_desc}\nRelationship types: {rels_desc}"

    def extract(self, text: str, source_name: str = "") -> dict:
        """Extract entities and relationships from text using LLM."""
        chunks = self._chunk_text(text)

        if len(chunks) == 1:
            prompt = EXTRACTION_PROMPT + text[:30000]
            response = self._call(
                "You are a precise knowledge extraction system. Always output valid JSON.",
                prompt,
            )
            try:
                return self._parse_response(response)
            except Exception as e:
                print(f"  Parse error: {e}", file=sys.stderr)
                print(f"  Raw response (first 500 chars): {response[:500]}", file=sys.stderr)
                return {"entities": [], "relationships": []}

        # Multi-chunk
        all_entities = []
        all_relationships = []
        seen_ids = set()

        for i, chunk in enumerate(chunks):
            print(f"    Chunk {i+1}/{len(chunks)} ({len(chunk)} chars) ...", file=sys.stderr)
            prompt = f"{EXTRACTION_PROMPT}Chunk {i+1}/{len(chunks)}\n\n{chunk[:40000]}"
            try:
                response = self._call(
                    "You are a precise knowledge extraction system. Always output valid JSON.",
                    prompt,
                )
                result = self._parse_response(response)
                for entity in result.get("entities", []):
                    eid = entity["id"]
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        all_entities.append(entity)
                all_relationships.extend(result.get("relationships", []))
            except Exception as e:
                print(f"  Warning: chunk {i+1} extraction failed: {e}", file=sys.stderr)
                print(f"  Raw (first 300 chars): {response[:300] if 'response' in dir() else 'N/A'}", file=sys.stderr)

        main_entity = all_entities[0]["id"] if all_entities else source_name
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
