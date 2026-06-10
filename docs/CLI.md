# CLI Reference

## Core Commands

| Command | Description |
|---------|-------------|
| `wiki init` | Initialize .wiki/ structure |
| `wiki config` | Show current configuration |
| `wiki config --init` | Create default wiki_config.yaml |
| `wiki status` | Wiki statistics |
| `wiki compile <file-or-dir>` | Compile sources → wiki pages |
| `wiki compile <dir> --depth 1` | Limit directory recursion depth |
| `wiki query <question>` | Search + synthesize answer |
| `wiki query <q> --no-synthesis` | Fast search, skip LLM (0.5s) |
| `wiki query <q> --file-back` | Answer + file back to wiki |
| `wiki query <q> --debug-search` | Full retrieval trace output |
| `wiki query <q> --format table` | Output as comparison table |
| `wiki lint` | Health check |
| `wiki lint --auto-heal` | Health check + auto-fix |
| `wiki embed` | Generate page embeddings |
| `wiki embed --chunks` | Generate chunk embeddings |
| `wiki embed --force` | Force re-generate |
| `wiki bulk stats` | Detailed statistics |
| `wiki bulk clean` | Remove orphan pages |
| `wiki search doctor` | Retrieval index health diagnostics |
| `wiki search eval <file>` | Evaluate retrieval (Recall@K, MRR) |

## Benchmark

```bash
wiki benchmark ragas                # RAGAS black-box evaluation
wiki benchmark beir scifact         # BEIR retrieval benchmark (single dataset)
wiki benchmark beir --all           # All BEIR datasets
```

## Ledger

| Command | Description |
|---------|-------------|
| `wiki ledger list` | List all ledgers |
| `wiki ledger create <name>` | Create ledger table |
| `wiki ledger import <file>` | Import CSV/Excel |
| `wiki ledger show <id>` | Show schema + rows |
| `wiki ledger ask <table> <question>` | Natural language → SQL |
| `wiki ledger sql <query>` | Raw SQL (read-only) |
| `wiki ledger export <id>` | Export to CSV |
| `wiki ledger insert <id> --data` | Insert rows |
| `wiki ledger delete <id>` | Delete ledger |

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
