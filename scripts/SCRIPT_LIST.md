# LLM Wiki v2 Scripts

## Core Scripts (Active)

### Primary Operations
| Script | Lines | Purpose | Dependencies |
|--------|-------|---------|--------------|
| `compile_v2.py` | 440 | **Compile source → build wiki** | None |
| `query.py` | 235 | **Search wiki → answer questions** | `search.bm25_search` |
| `query_multihop.py` | — | Subgoal coverage, typed linked traversal, path scoring, diverse top-k | Injected official search callback |
| `query_language.py` | — | Model-free bilingual alias and glossary expansion | `query.py` |
| `lint.py` | 277 | **Health check → auto-heal** | None |

### Support Scripts
| Script | Lines | Purpose | Dependencies |
|--------|-------|---------|--------------|
| `search.py` | 325 | BM25 + graph search engine | `graph.traverse` |
| `graph.py` | 329 | Knowledge graph operations | None |
| `consolidate.py` | 307 | Memory tier consolidation | `crystallize.check_contradictions` |
| `crystallize.py` | 330 | Session → digest pipeline | None |

### Utilities
| Script | Lines | Purpose | Dependencies |
|--------|-------|---------|--------------|
| `url2markdown.py` | 280 | URL → markdown conversion | None |
| `ocr.py` | shim | Backward-compatible wrapper for `wiki ocr` | `ocr.cli` |
| `epub.py` | — | EPUB spine → Markdown with persistent image extraction | BeautifulSoup, markdownify |
| `_deepseek_ocr.py` | 358 | DeepSeek OCR backend | None |
| `_ollama.py` | 52 | Ollama embeddings | None |

### CLI Wrapper
| Script | Lines | Purpose | Dependencies |
|--------|-------|---------|--------------|
| `wiki.py` | ~150 | **Unified CLI** | Calls: compile_v2.py, query.py, lint.py |

## Deleted Scripts (Obsolete)

| Script | Lines | Reason |
|--------|-------|--------|
| `ingest.py` | 828 | Replaced by `compile_v2.py` (simpler, 440 lines) |
| `wiki.py` (old) | 596 | Simplified to ~150 lines, removed ingest.py dependency |

## Dependency Graph

```
query.py → query_multihop.py → search.py → graph.py
consolidate.py → crystallize.py
wiki.py → compile_v2.py, query.py, lint.py
ocr.py → ocr.cli → selected OCR backend
```

## Usage Examples

### Direct Scripts
```bash
# Compile source
python3 scripts/compile_v2.py source.md

# Query wiki
python3 scripts/query.py "What is X?" --file-back

# Health check
python3 scripts/lint.py --auto-heal

# Graph operations
python3 scripts/graph.py show

# Consolidate memory
python3 scripts/consolidate.py

# Crystallize session
python3 scripts/crystallize.py session.md --topic "Research"
```

### CLI Wrapper
```bash
# Compile
wiki compile source.md

# Query
wiki query "What is X?"

# Lint
wiki lint --auto-heal

# Status
wiki status

# Initialize
wiki init
```

## File Structure

```
scripts/
├── wiki.py              # Unified CLI (~150 lines)
├── compile_v2.py        # Main compilation (440 lines) ★
├── query.py             # Wiki querying (235 lines) ★
├── lint.py              # Health checking (277 lines) ★
├── search.py            # BM25 search engine (325 lines)
├── graph.py             # Knowledge graph (329 lines)
├── consolidate.py       # Memory consolidation (307 lines)
├── crystallize.py       # Session → digest (330 lines)
├── url2markdown.py      # URL conversion (280 lines)
├── ocr.py               # Backward-compatible wrapper for wiki ocr
├── _deepseek_ocr.py     # OCR backend (358 lines)
├── _ollama.py           # Embeddings (52 lines)
└── __init__.py          # Package init (12 lines)

Total: ~2,700 lines (down from 4,882 lines)
```

## Key Improvements

1. **Simplified compilation**: `compile_v2.py` (440 lines) vs `ingest.py` (828 lines)
   - 81% reduction in code
   - LLM-generated markdown, Python only writes files
   
2. **Clean dependencies**: No circular imports, clear hierarchy
   
3. **Unified CLI**: `wiki.py` wraps core scripts with simple interface
   
4. **Tested**: All imports and dependencies verified working
