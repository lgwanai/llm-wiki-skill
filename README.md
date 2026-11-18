<p align="center">
  <a href="README.md">English</a> &nbsp;|&nbsp;
  <a href="README_CN.md">简体中文</a>
</p>

# llm-wiki

llm-wiki is a Python CLI and an Agent skill for building a local knowledge base. It compiles documents, images, notes, and code into reusable Markdown concept pages with typed relationships, while indexing the underlying evidence separately. A query can connect information across sources and cite the specific page, slide, section, or table that supports the answer.

Use it to look up which policy applied on a given date, trace a handoff on a workflow diagram, compare figures across reports, or connect textbook concepts to the questions that test them.

## Quick start

Install with Python 3.10 or newer. Run the Wiki commands from the directory where you want to keep the knowledge base.

```bash
git clone https://github.com/lgwanai/llm-wiki-skill.git
cd llm-wiki-skill
python -m pip install -e .
```

```bash
wiki config --init
wiki init
wiki status
wiki compile ./handbook.md --mode agent
# Complete and verify the generated worklist in your Agent.
wiki query "What are the exceptions in the handbook?" --no-synthesis
wiki query "What are the exceptions in the handbook?"
```

Replace `./handbook.md` with your source. In Agent mode, the last command returns an evidence packet for the assistant to answer and verify. For terminal-only document compilation and answer synthesis, configure a model and pass `--mode llm` to each command. From the checkout, `python scripts/wiki.py` is also a CLI entry point.

### Install as an Agent skill

Clone or link the complete repository as a single skill directory, with `SKILL.md`, `scripts/`, `templates/`, and `references/` together. For Codex, put it under `~/.codex/skills/llm-wiki` (or under your configured Codex home). For Claude Code, use `~/.claude/skills/llm-wiki`. For example, to install for Codex from a fresh clone:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/lgwanai/llm-wiki-skill.git ~/.codex/skills/llm-wiki
python -m pip install -e ~/.codex/skills/llm-wiki
```

Open the assistant in your knowledge-base project. In Codex, ask `$llm-wiki` to add a source and answer a question against it. The skill guides the assistant through completing the worklist and verifying the final answer. Repo-local session hooks for Codex and Claude Code are optional. [Skill instructions](SKILL.md) · [Automation reference](references/automation.md)

### Model and OCR requirements

| Workflow | Resources |
|---|---|
| **Local retrieval** | `wiki query --no-synthesis` returns ranked evidence without an answer model. The default retrieval configuration uses local indexes. |
| **Agent mode (default)** | Uses the current assistant's model connection. The CLI prepares compile worklists and query evidence packets for that assistant. Images and unresolved chart or diagram relationships need an assistant with image input and a configured OCR path for text extraction. |
| **Standalone LLM mode** | Uses the configured model service. Confirm the API endpoint, model ID, access, quota, and any required API key. Reference the key through an environment variable in `wiki_config.yaml`. Ollama requires a running service and an installed model. |
| **OCR** | Requires a ready backend with its runtime and model weights, or a configured vision endpoint for the standalone OCR API backend. OCR has its own configuration. |

For standalone LLM mode, run `wiki config --check` after editing the model settings. It checks local prerequisites without contacting the provider. Run `ocr list --check` and `ocr --doctor` to inspect OCR readiness. [Configuration guide](CONFIGURATION.md) · [Usage guide](docs/USAGE.md)

With the model service configured, run the standalone path as follows. A PDF with unresolved page evidence can still return a worklist for visual review.

```bash
wiki config --check
wiki compile ./handbook.md --mode llm
wiki query "What are the exceptions in the handbook?" --mode llm
```

## Compile sources into reusable knowledge

| Source | Evidence and structure captured |
|---|---|
| **Markdown, text, HTML files, code, and transcripts** | Headings, facts, definitions, snippets, and links between concepts. Compile accepts individual files, recursive directories, inline text, and standard input. |
| **PDF** | Reads the native text layer and layout first. When layout is clear, it can preserve code indentation, join continued tables across pages, distinguish adjacent tables, and associate simple chart values with labels. Pages with gaps are rendered for local OCR or sent for Agent review. |
| **PowerPoint** | For editable `.pptx` files, extracts available native shape connections, decision branches, table cells, and chart values. Slides with embedded raster content can combine native and rendered/OCR evidence at the same slide number. |
| **Word and EPUB** | Word uses page rendering where available. Legacy `.doc` may require LibreOffice or macOS `textutil` for conversion. EPUB follows the book's reading order, retains chapter and section locators, and extracts referenced images. |
| **Screenshots, scans, and images** | OCR extracts text, formulas, and tables. A vision-capable Agent inspects visual relationships such as arrow direction, lanes and handoffs, task dependencies, axes, and series. Reviewed observations can be attached as searchable evidence with a reference to the original image. |
| **Spreadsheets and CSV** | Compile worksheet or file content as source material, or use `wiki ledger import` for row-level storage and SQL queries. |

Compilation can apply domain-specific extraction guidance for policy and compliance, operations, engineering, finance, academic research, and education. A policy page can retain article numbers, operative language, scope, exceptions, and effective dates. A research page can link definitions, formulas, assumptions, findings, and limitations. A textbook and its exam papers can form bidirectional links between knowledge points and questions. Linked concepts can carry relationships such as `depends_on`, `tests`, `contradicts`, and `supersedes`.

Concept pages and original evidence serve different lookup needs. The compiler can materialize atomic claims from facts, cells, key/value fields, and footnotes while preserving their context. The evidence index also searches extracted source text directly by page, slide, or EPUB section, so a field omitted from a concept summary can still be retrieved. Matched visual records can include the persisted image and its source locator.

### Revisions and publication

Source identity is derived from the file path, so two files with the same name in different directories can be compiled independently. Moving or renaming a source creates a new identity. Unchanged inputs can be skipped. Use `--force` to recompile and `--dry-run` to preview the work.

Agent compilation stages draft pages and uses a worklist to track source coverage. Drafts carry source locators and supporting excerpts. Verification publishes the pages and evidence together. Standalone LLM compilation publishes after its staged run succeeds. If a run is incomplete or interrupted, queries continue to use the last published revision. Prior evidence and compiled copies are retained under `.wiki/source/evidence/`.

```bash
wiki compile ./documents/ --depth 1
wiki compile ./documents/release-plan.pptx --force
wiki compile --text "Approval expires after 90 days." --name approval-notes
```

[Publication and worklist commands](docs/CLI.md#source-versions-and-publication) · [Visual evidence](references/visual-evidence.md) · [Document and image examples](evals/media_workflows/README.md)

## Search, answer, and verify

Default local retrieval combines **raw source evidence, atomic claims, metadata, BM25F, structured visuals, the knowledge graph, and DuckDB ledgers**. It weights each stream by query intent and merges results with reciprocal rank fusion. Long pages remain intact in storage, while heading-bounded sections get their own lexical retrieval signals. Chinese and English queries use local tokenization and can expand with bilingual aliases and a project glossary at `.wiki/query_lexicon.yaml`.

- **Answer across documents.** Multi-hop retrieval breaks compound questions into subgoals and follows relevant links. It stops when evidence covers the subgoals, no useful links remain, or it reaches the hop limit. The default is three hops.
- **Resolve policy applicability.** Current queries favor the active rule and can surface scheduled replacements. Historical queries evaluate the requested date against `effective_from` (inclusive) and `effective_until` (exclusive). Missing applicability dates remain unknown.
- **Inspect exact values and visual evidence.** Search can surface a particular page, chart, table row, or footnote. Where structured chart evidence uniquely identifies the required series and values, some totals and proportions can be computed directly.
- **Verify before reuse.** In Agent mode, the query task supplies a local verification command for the answer draft. LLM mode checks the generated answer directly. Verification checks support for citations, explicit permissions or prohibitions, exact amounts and units, and date applicability. An unsupported or conflicting claim blocks `--file-back` even if regular answer verification is disabled.
- **Resolve follow-up questions.** `--conversation-stdin` accepts up to six user/assistant pairs as JSON. The configured model resolves references in the current question before retrieval. The newly retrieved evidence supports the answer.
- **Choose an output.** Retrieve evidence only, synthesize an answer with citations, or select Markdown, a comparison table, a timeline, Marp slides, JSON, or a relationship graph.

```bash
wiki query "Which reimbursement policy applied on 2025-07-01?"
wiki query "Which milestone blocks the rollout in the Gantt chart?"
wiki query "Compare the thresholds in the two regional policies" --format table
wiki query "Where does the workflow hand off to Finance?" --no-synthesis --debug-search
wiki query "Summarize the approved escalation process" --file-back
```

Optional semantic search uses embedded Zvec and an embedding model. Install with `python -m pip install -e '.[vector]'`, enable `embeddings`, and add `vector` to `query.search_streams`. Optional FlagEmbedding reranking uses `python -m pip install -e '.[rerank]'` and `reranker.enabled`. The native retrieval streams remain available when these layers are disabled or unavailable. [Hybrid retrieval](references/hybrid-search.md) · [Answer verification commands](docs/CLI.md#answer-evidence-verification)

## Query and manage structured tables

Tables discovered during compilation can be inspected with `wiki table list` and `wiki table show <table>`. Use `wiki ledger` to maintain structured records in DuckDB. It can import CSV/Excel, create tables with typed columns, insert rows in batches, update schemas, search across tables, and export to CSV. Ledger results can also contribute evidence to general Wiki queries.

```bash
wiki ledger import ./data/projects.xlsx
wiki ledger list
wiki ledger show projects
wiki ledger sql "SELECT * FROM projects WHERE budget > 500000"
wiki ledger ask projects "Which projects exceed the budget threshold?"
```

Use the table and field names in your data. `wiki ledger sql` is read-only. `wiki ledger ask` and `wiki table ask` use the configured model. `wiki ledger context` provides schema and function context for an Agent to generate SQL. [Ledger commands](docs/CLI.md#ledger) · [SQL function reference](references/sql-functions.md)

## Maintain and share the Wiki

| Task | Entry point | Behavior |
|---|---|---|
| Inspect the Wiki | `wiki status`, `wiki search doctor` | Shows Wiki counts and checks retrieval indexes. |
| Check and repair | `wiki lint`, `wiki lint --auto-heal` | Reports orphan pages, broken links, stale content, and contradictions. Auto-heal applies available repairs. |
| Investigate a specific issue | `wiki doctor "The regional exception is missing"` | Records the issue, searches for evidence, and applies an appropriate strategy such as recompile, re-OCR, metadata repair, or flagging for review. |
| Improve using query history | `wiki dream --foreground` | Updates metadata, audits query history, and can merge duplicates or enrich pages. It evaluates changes against retrieval quality and uses Git snapshots for rollback. |
| Retain useful session knowledge | `wiki consolidate`, session digest workflow | Supports memory consolidation and confidence decay. Session crystallization turns decisions, findings, and lessons into searchable pages. |
| Share curated knowledge | `wiki export`, `wiki import`, `wiki okf` | Exchanges compiled pages and attachments as Wiki ZIPs or OKF bundles. |

Confidence metadata supports decay and reinforcement over time. Existing pages and graph records can still use legacy `high`, `medium`, and `low` labels. Contradictions and supersession links preserve the context for reviewing conflicting or replaced knowledge. [Knowledge lifecycle](references/lifecycle.md)

### Storage and portability

`.wiki/pages/` is a native [Open Knowledge Format v0.1 draft](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle. Each concept is Markdown with YAML frontmatter and a Concept ID derived from its path relative to the bundle root. Standard Markdown links connect concepts. The source evidence, graph indexes, and ledger database live in separate directories. Set `LLM_WIKI_DIR` to use a different Wiki and `LLM_WIKI_CONFIG` to select a configuration file.

```text
.wiki/
├── pages/            OKF concept pages, session digests, and linked assets
├── source/evidence/  Extracted source records, manifests, and revisions
├── graph/            Typed relationships and retrieval indexes
├── ledger/           DuckDB structured tables
├── schema.md         Wiki page and entity conventions
└── audit.json        Compile audit entries
```

```bash
wiki export team-wiki.zip
wiki export onboarding.zip --module modules/onboarding --page concepts/access
wiki okf validate onboarding.zip
wiki import onboarding.zip
wiki okf export ./exports/team-okf
```

ZIP sharing preserves paths and metadata for compiled pages and their included attachments. Full exports include session pages. Use repeatable `--module` and `--page` options to share a subset and include related concepts explicitly. Export archives cover the compiled bundle. Raw evidence history, runtime configuration, and the DuckDB database stay in the originating Wiki. Import skips identical files and reports conflicts before merging. `wiki okf` also imports and validates directories and migrates legacy page metadata. [Sharing walkthrough](docs/USAGE.md#13-分享知识库和知识模块)

### Data handling

The Wiki and default retrieval indexes live on disk. New text snapshots and extracted evidence redact recognized credential patterns. The original image pixels can still display sensitive content. A remote assistant, standalone model, or API OCR backend may receive the source or retrieved excerpts it needs for the operation. Review the selected mode, attachments, and bundle contents before working with or sharing sensitive material. [Privacy and governance](references/privacy-governance.md)

## OCR as a standalone tool

`ocr` also runs outside a Wiki. Choose a backend based on the source and the available hardware or model endpoint.

| Backend | Engine and typical use |
|---|---|
| `paddlevl` | Default. PaddleOCR-VL-1.6 with MLX on Apple Silicon, for layout and structured document parsing. |
| `ovis` | OvisOCR2 on MLX, with Markdown, math, and figure extraction. |
| `mineru` | MinerU for page layout, tables, and formulas. |
| `deepseek` | DeepSeek-OCR-2 for vision-based document parsing. |
| `logics` | Logics-Parsing-v2 for multimodal document parsing. |
| `paddle` | PaddleOCR PP-OCRv5 for multilingual text recognition. |
| `api` | A configured OpenAI-compatible vision endpoint. |

```bash
ocr list --check
ocr --doctor
ocr handbook.pdf --smoke-pages 3
ocr handbook.pdf -o ./parsed/
ocr --batch ./pdfs/
```

An OCR run writes Markdown and a manifest with source identity, requested and parsed pages, coverage, and references to extracted assets where available. Use `ocr use <backend>` to set the default, `--backend <backend>` for one run, and `ocr config` to manage settings in `~/.config/ocr/config.yaml`. The CLI is also available via `python -m ocr` or `wiki ocr`. [OCR configuration](CONFIGURATION.md#ocr) · [OCR commands](docs/CLI.md#ocr)

## Evaluation and further reading

- **Long-document QA.** The repository reports **62/62** on the same 34 PDFs, 1,945 pages, and 62 questions used by the PageIndex OSS benchmark. The answer and judge models differ, so treat this as a directional result on that material. [Benchmark and reproducibility details](docs/BENCHMARK.md)
- **Multimodal evidence.** The document benchmark distinguishes native PowerPoint extraction, PDF layout recovery, OCR-only images, and images with reviewed visual observations. [Media workflow results](evals/media_workflows/README.md)
- **Mixed-source QA.** The mixed Wiki evaluation measures evidence recall, citation support, correct abstention, and local verification for same-named sources, policy revisions, and distractors. [Mixed Wiki evaluation](evals/p1_mixed_wiki/README.md)

Run your own JSONL cases with `wiki benchmark <cases.jsonl> --method retrieval`. It reports recall, ranking quality, coverage across subgoals, and P50/P95 retrieval latency. `--method both` adds local RAGAS-style scores over supplied or extractive answers. [Benchmark commands](docs/CLI.md#benchmark)

| Reference | What it covers |
|---|---|
| [Usage guide](docs/USAGE.md) | Task-oriented workflows and copyable commands |
| [CLI reference](docs/CLI.md) | Options, worklists, evidence checks, and document format handling |
| [Configuration](CONFIGURATION.md) | Model, OCR, retrieval, and embedding settings |
| [Architecture and lifecycle](docs/ARCHITECTURE.md) | Storage, retrieval, and knowledge maintenance |
| [Agent skill](SKILL.md) | Agent workflows for compiling, answering, maintaining, and sharing |

Inspired by [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and [Rohit's v2 extension](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2). Released under the [MIT License](LICENSE).
