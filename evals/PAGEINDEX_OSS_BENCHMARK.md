# PageIndex OSS Benchmark for llm-wiki

This evaluation reuses the public material and scoring shape from
[VectifyAI/PageIndex-OSS-Benchmark](https://github.com/VectifyAI/PageIndex-OSS-Benchmark).
It measures end-to-end document QA, not only embedding similarity.

![PageIndex and llm-wiki comparison](../docs/pageindex_comparison.png)

For the visual executive summary, full PageIndex model matrix, architecture diagram,
failure-mode analysis, and project highlights, see
[the illustrated benchmark report](../docs/BENCHMARK.md).

## Pinned material

- PageIndex benchmark commit: `ad4c0b92970a6f4801f09ff2e647389e8f5874fa`
- MMLongBench-Doc-V2 judge commit: `3aba3c6831a432ee882f763435f9ebe92ab75ed9`
- Questions: 62
- PDFs: 34
- Source pages: 1,945
- Question set SHA-256:
  `f0cc046c0e3bdd4c8c4a4dc977e08e107d21d6a2d22fb8237914111d0f6e256e`
- PDF corpus fingerprint:
  `a0ed377618ed48a6753d959062fd24cca3d1e607f5f490767ff510b57480a833`

The runner refuses a mismatched question set, document manifest, or PDF corpus. The
benchmark material remains outside the repository and is not redistributed by this
project.

## Matched protocol

The following PageIndex choices are preserved:

1. Use the same 62 lookup questions and 34 source PDFs.
2. Keep only running-text facts; the set contains no chart, table, figure, counting,
   or arithmetic questions.
3. Index each document once, then reuse that index for its questions.
4. Answer each question against its named PDF only. Documents are never pooled into a
   shared corpus.
5. Save the complete response with `question`, `answer`, `answer_format`, and
   `response`, ready for the official MMLongBench-Doc-V2 semantic-equivalence judge.
6. Report question-level accuracy and latency without dropping failed questions.

The llm-wiki equivalent of PageIndex's index/query path is:

```text
PDF native text layer (no OCR) -> compile_v2 --mode llm -> isolated OKF wiki
-> query_wiki --mode llm
```

## Run

Obtain the pinned PageIndex benchmark checkout or release archive, then run:

```bash
python scripts/benchmark_pageindex.py run /path/to/PageIndex-OSS-Benchmark \
  --jobs 4 \
  --chunk-tokens 12000 \
  --output evals/pageindex_oss_results/predictions.json
```

Compilation caches live under `.benchmarks/pageindex-oss/` and are isolated by PDF
hash, llm-wiki Git revision, and model configuration. The output file is checkpointed
after every question and is resumable. The 12K cap is applied only when a document
exceeds the configured model's normal context threshold; smaller documents remain whole.

For a directly comparable score, use the official judge:

```bash
git clone https://github.com/VectifyAI/MMLongBench-Doc-V2
cd MMLongBench-Doc-V2
python -m eval.judge /path/to/predictions.json --out judged.json
```

The official benchmark pins `gpt-5.6-luna` with high reasoning effort. When that model
is unavailable, a directional score can be produced with llm-wiki's configured model:

```bash
python scripts/benchmark_pageindex.py judge-configured predictions.json
python scripts/benchmark_pageindex.py report predictions.configured-judged.json
```

To reuse the exact prompt text from the pinned official judge while retaining the
locally configured model, pass its source file explicitly:

```bash
python scripts/benchmark_pageindex.py judge-configured predictions.json \
  --official-judge-file /path/to/MMLongBench-Doc-V2/eval/judge.py
```

Directional scores must name the actual judge model and must not be presented as
directly comparable to PageIndex's published result.

## Latest results

Run date: 2026-09-19. Compile and answer model: `deepseek-v4-flash`. The semantic
judge used the same configured model with the exact `PROMPT` string from the pinned
MMLongBench-Doc-V2 `eval/judge.py`. This is a **directional**, not official
leaderboard-comparable, score because PageIndex publishes results with OpenAI chat
models and the official structured-output judge.

| Measure | Before lossless evidence | Latest |
|---|---:|---:|
| Questions / PDFs / source pages | 62 / 34 / 1,945 | 62 / 34 / 1,945 |
| Semantically equivalent | 38 / 62 | **62 / 62** |
| Directional accuracy | 61.3% | **100.0%** |
| Compile or query runtime errors | 0 | 0 |
| Generated knowledge pages | 1,204 | 1,204 |
| Indexing time | 5,211.30 s total | 5,211.30 s total (cache reused) |
| Query latency | 2.91 s mean; 5.59 s p95 | 2.58 s mean; 4.03 s p95 |

The improvement comes from a lossless source-evidence layer, cross-page neighbor
context, exact-field and structural routing, typo correction, and high-precision
deterministic extraction for counts, paired year/value tables, footnotes, procedures,
and other exact lookups. The raw evidence coverage gate verifies that every normalized
source unit is persisted before compile succeeds.

PageIndex's pinned published matrix ranges from 53/62 (85.5%) for `gpt-5.6-luna`
with none/low reasoning to 62/62 (100%) for `gpt-5.6-terra` high and `gpt-5.6-sol`
medium/high. Its `gpt-5.6-luna` high row is 60/62 (96.8%). The latest llm-wiki run
therefore reaches the same directional ceiling on the same 62 questions, but the model
and judge mismatch means this must not be claimed as a strict model-for-model win.

Latest artifacts:

- `predictions-lossless-v5-2026-09-19.json` — all predictions in the official-compatible
  schema.
- `predictions-lossless-v5-2026-09-19.manifest.json` — pinned corpus, model, runtime
  fingerprint, and compile records.
- `predictions-lossless-v5-2026-09-19.configured-judged.json` — directional verdicts.
- `predictions-lossless-v5-2026-09-19.configured-judged.judge-manifest.json` — judge
  model and exact prompt fingerprint.
- `REPORT-LOSSLESS-V5-2026-09-19.md` — aggregate and per-document-type metrics.
