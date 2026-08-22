# CLI Reference

## Core Commands

| Command | Description |
|---------|-------------|
| `wiki init` | Initialize .wiki/ structure |
| `wiki config` | Show current configuration |
| `wiki config --init` | Create default wiki_config.yaml |
| `wiki config --check` | Validate configuration |
| `wiki status` | Wiki statistics |
| `wiki compile <file-or-dir>` | Compile sources → wiki pages (Agent mode by default) |
| `wiki compile <file-or-dir> --mode llm` | Compile via configured LLM provider |
| `wiki compile <dir> --depth 1` | Limit directory recursion depth |
| `wiki compile --text "content" --name "title"` | Compile inline text |
| `wiki compile <dir> -j 4` | Parallel compilation (4 workers) |
| `wiki query <question>` | Search + synthesize answer |
| `wiki query <q> --no-synthesis` | Fast search, skip LLM (0.5s) |
| `wiki query <q> --file-back` | Answer + file back to wiki |
| `wiki query <q> --debug-search` | Per-hop coverage, missing subgoals, sections, scores, and stop reason |
| `wiki query <q> --max-hops 3` | Evidence-driven subgoal decomposition and linked retrieval |
| `wiki query <q> --single-hop` | Disable multi-hop for diagnostics/benchmarks |
| `wiki query <q> --format table` | Output as comparison table |
| `wiki lint` | Health check |
| `wiki lint --auto-heal` | Health check + auto-fix |
| `wiki embed` | Generate page embeddings |
| `wiki embed --chunks` | Generate chunk embeddings |
| `wiki embed --force` | Force re-generate |
| `wiki bulks` | Bulk operations (stats, clean) |
| `wiki search doctor` | Retrieval index health diagnostics |
| `wiki search eval <file>` | Evaluate retrieval (Recall@K, MRR) |

## Dream (Self-Looping Maintenance)

| Command | Description |
|---------|-------------|
| `wiki dream` | Run 4-phase auto-maintenance (background) |
| `wiki dream --foreground` | Run inline with live output |

## Doctor (Issue Diagnosis & Repair)

| Command | Description |
|---------|-------------|
| `wiki doctor "<feedback>"` | Report issue in natural language |
| `wiki doctor --check <page>` | Diagnostic check on page |
| `wiki doctor --recompile <source>` | Recompile source document |
| `wiki doctor --re-ocr <file>` | Re-OCR + recompile |
| `wiki doctor --list` | List outstanding issues |
| `wiki doctor --resolve <id>` | Mark issue resolved |

## OKF v0.1

| Command | Description |
|---------|-------------|
| `wiki okf validate <bundle>` | Validate OKF bundle compliance |
| `wiki okf import <bundle>` | Merge external OKF bundle |
| `wiki okf export <path>` | Export wiki as OKF bundle |
| `wiki okf migrate` | Migrate legacy metadata to OKF v0.1 |

## Benchmark

```bash
wiki benchmark <eval_file.jsonl>              # Run RAG evaluation
wiki benchmark <eval_file.jsonl> --method retrieval  # BEIR/MTEB retrieval metrics
wiki benchmark <eval_file.jsonl> --method ragas-lite  # RAGAS-style evaluation
wiki benchmark <eval_file.jsonl> --method both -k 5    # Both methods
```

Retrieval benchmarks report Hit/Recall/MRR/NDCG plus complete subgoal coverage,
topic drift (for cases with `strict_relevant_pages`), hop depth, forbidden leakage,
and P50/P95 latency. Set `"multi_hop": true`, `expected_groups`, and optionally
`strict_relevant_pages` on a JSONL case to exercise the evidence-driven path.

## Ledger

| Command | Description |
|---------|-------------|
| `wiki ledger list` | List all ledgers |
| `wiki ledger create <name>` | Create ledger table |
| `wiki ledger import <file>` | Import CSV/Excel |
| `wiki ledger show <id>` | Show schema + rows |
| `wiki ledger ask <table> <question>` | Natural language → SQL |
| `wiki ledger sql <query>` | Raw SQL (read-only) |
| `wiki ledger search <query>` | Full-text search across all tables |
| `wiki ledger export <id>` | Export to CSV |
| `wiki ledger insert <id> --data` | Insert rows |
| `wiki ledger delete <id>` | Delete ledger |

## OCR

```bash
ocr list                                      # List supported models
ocr list --check                              # Also probe local readiness
ocr use paddlevl                              # Persist global default
ocr config show                               # Show ~/.config/ocr/config.yaml
ocr config set ovis.options.model_path /models/ovis
ocr <file.pdf>                                # Use the default model
ocr <file.pdf> --backend mineru               # One-run override
ocr --batch ./pdfs/                           # Batch entire directory
```

`python -m ocr`, `python -m ocr.cli`, `llm-wiki-ocr`, and `wiki ocr` expose the same parser.

## Output Formats

```bash
wiki query "..." --format markdown   # Default: structured answer + citations
wiki query "..." --format table      # Comparison table
wiki query "..." --format timeline   # Event timeline
wiki query "..." --format slides     # Marp slide deck
wiki query "..." --format json       # Structured JSON export
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `LLM_WIKI_DIR` | Override wiki directory path |
| `LLM_WIKI_SEARCH_STREAMS` | Override retrieval streams |
| `EMBEDDING_MODE` | `local` or `api` |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `OCR_CONFIG` | Override standalone OCR config path |
