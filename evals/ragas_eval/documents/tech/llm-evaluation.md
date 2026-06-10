# LLM Evaluation Metrics

Evaluating LLMs requires measuring performance across multiple dimensions. No single metric captures all aspects of model quality.

## Knowledge & Reasoning

### MMLU (Massive Multitask Language Understanding)
57 subjects across STEM, humanities, social sciences. Standard metric for measuring broad knowledge. Multiple-choice format with 4 answer options.

### GSM8K
Grade-school math word problems requiring multi-step reasoning. Measures arithmetic and logical reasoning. Models must output the final answer, not multiple choice.

### MATH
High-school competition mathematics problems across algebra, geometry, number theory, and more. Significantly harder than GSM8K. Requires step-by-step reasoning.

### HumanEval
Programming benchmark where models write Python functions from docstrings. Evaluated on functional correctness via unit tests. Pass@k measures the probability of at least one correct solution among k samples.

## Language & Generation

### MT-Bench
Multi-turn conversation benchmark where a strong LLM (GPT-4) judges response quality across writing, reasoning, coding, math, and roleplay categories. Scores on a 1-10 scale.

### AlpacaEval
Automated evaluation against reference responses. Measures win rate against GPT-4 or text-davinci-003. Fast to compute but sensitive to judge model preferences and length bias.

### Chatbot Arena (LMSys)
Human preference evaluation platform. Users chat with anonymous models and rate responses. Elo scores are calculated from pairwise comparisons. Considered the gold standard for real-world usefulness.

## Task-Specific

| Domain | Metric | Description |
|--------|--------|-------------|
| Summarization | ROUGE-L | Longest common subsequence overlap |
| Translation | BLEU | N-gram overlap with reference |
| NER | F1 Score | Precision/recall of entity spans |
| Code | Pass@k | Functional correctness |
| Math | Exact Match | Final answer correctness |

## Key Limitations of Current Evaluation

1. **Benchmark contamination**: Training data may include test sets, inflating scores
2. **Surface form over substance**: Metrics often reward stylistic similarity over factual correctness
3. **English-centric**: Most benchmarks are in English, with limited multilingual coverage
4. **Static benchmarks**: Fixed test sets don't account for changing world knowledge
5. **Prompt sensitivity**: Small prompt changes can cause large score variations

## Emerging Evaluation Paradigms

### LLM-as-Judge
Using a stronger LLM to evaluate outputs. MT-Bench and AlpacaEval use this approach. Challenges include judge bias, position bias (preferring first/last response), and verbosity bias.

### Dynamic Benchmarks
Generating new test cases automatically to prevent contamination. Examples include DyVal (dynamic evaluation) and LiveBench (periodically updated questions).

### Agentic Evaluation
Evaluating models on multi-step tasks that require tool use, planning, and interaction. Examples include SWE-bench (software engineering tasks), WebArena (web navigation), and GAIA (general AI assistant tasks).
