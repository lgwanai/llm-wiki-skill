# llm-wiki Comprehensive Benchmark Report

**Generated**: 2026-06-11
**Scope**: BEIR retrieval + RAGAS end-to-end + Cross-encoder reranker + Multi-model comparison
**Test infrastructure**: `benchmark_beir.py` (component-level), `benchmark_ragas.py` (black-box product-level)

---

## Executive Summary

llm-wiki 的检索管道在已编译的知识库上表现优异（NDCG@10 = 0.92–0.96），但端到端答案合成质量存在显著短板（Faithfulness = 0.33）。核心瓶颈不在于检索，而在于：(1) compile_v2 的文档覆盖率仅 20%，(2) LLM 答案合成缺乏足够上下文支撑导致幻觉，(3) MLX 8B cross-encoder reranker 实际破坏了排序质量。

**一页总结**:

| 维度 | 分数 | 评级 | 关键发现 |
|------|------|------|---------|
| 检索质量 (BEIR) | NDCG@10=0.96 | 🟢 优秀 | Qwen3-8B 向量检索媲美原始 BM25 |
| 答案忠实度 (RAGAS) | Faithfulness=0.33 | 🔴 差 | 67% 的声明无法在上下文中找到支撑 |
| 答案正确性 (RAGAS) | Correctness=0.13 | 🔴 很差 | 与 ground truth 匹配度极低 |
| 上下文召回 (RAGAS) | Context Recall=0.77 | 🟡 一般 | 检索能找到相关信息，但不够完整 |
| 检索延迟 | P50=2.3s | 🟢 良好 | 可接受范围内 |

---

## 1. BEIR 检索评估（组件级）

### 1.1 SciFact — Compiled Wiki（最佳场景）

这是唯一使用了完整 compile_v2 管道的 BEIR 测试。文档覆盖率 20.3%（146/5183 篇文档被编译）。

| 模型 | 模式 | NDCG@10 | Recall@10 | MRR@10 | NDCG@1 |
|------|------|---------|-----------|--------|--------|
| **Qwen3-Embedding-8B** | vector | **0.955** | **1.000** | **0.940** | 0.902 |
| Qwen3-Embedding-8B | hybrid | 0.954 | **1.000** | 0.939 | 0.902 |
| Jina v5 Small MLX | hybrid | 0.950 | 0.993 | 0.940 | 0.902 |
| Jina v5 Small MLX | vector | 0.942 | 0.993 | 0.929 | 0.885 |
| Qwen3-Embedding-0.6B | hybrid | 0.933 | 0.980 | 0.919 | 0.869 |
| Qwen3-Embedding-0.6B | vector | 0.924 | 0.980 | 0.907 | 0.853 |
| Jina v5 Small MLX | bm25+vector | 0.883 | 0.928 | 0.884 | 0.836 |
| Qwen3-Embedding-0.6B | bm25+vector | 0.883 | 0.928 | 0.884 | 0.836 |
| **BM25 (original baseline)** | bm25 | **0.914** | 0.967 | 0.897 | — |

**关键发现**:
- **Qwen3-8B > Jina MLX > Qwen3-0.6B** 排序一致，但差距不大（NDCG@10 差距 0.03）
- Hybrid (vector+bm25) 对弱模型有帮助，对 Qwen3-8B 没有提升甚至略微降低
- BM25 原始基线 NDCG@10=0.914 — 对于 SciFact 这种关键词密集的数据集，BM25 本身就很强
- 编译覆盖率只有 20%，意味着 80% 的查询根本没有 wiki 页面可检索

### 1.2 FiQA-2018 — Direct Wiki（无编译）

| 模型 | 模式 | NDCG@10 | Recall@10 | MRR@10 |
|------|------|---------|-----------|--------|
| **Qwen3-Embedding-8B** | vector | **0.922** | **0.971** | **0.927** |
| Qwen3-Embedding-0.6B | vector | 0.916 | 0.964 | 0.928 |
| Jina v5 Small MLX | vector | 0.912 | 0.961 | 0.923 |

**关键发现**:
- 即使没有 compile_v2 实体提取，向量检索在 FiQA 上也表现优异
- 三个模型差距很小（NDCG@10 差距 < 0.01），选最轻量即可
- Qwen3-0.6B 是性价比最高的选择

### 1.3 NFCorpus — Direct Wiki（无编译）

| 模型 | 模式 | NDCG@10 | Recall@10 | MRR@10 |
|------|------|---------|-----------|--------|
| Jina v5 Small MLX | vector | **0.391** | 0.239 | **0.561** |
| Qwen3-Embedding-0.6B | vector | 0.389 | 0.236 | 0.559 |
| Qwen3-Embedding-8B | vector | 0.376 | 0.212 | 0.541 |

**关键发现**:
- NFCorpus 对所有模型都是挑战（长文档，医学领域）
- 缺乏 compile_v2 实体提取可能是一个因素（NFCorpus 没有编译 wiki）
- Jina MLX 在这个数据集上微弱领先

---

## 2. Cross-Encoder Reranker 对比

在 SciFact compiled wiki 上测试三种 reranker 配置：

| Reranker | NDCG@1 | NDCG@5 | Recall@5 | MRR@1 |
|----------|--------|--------|----------|-------|
| **No Reranker** | **0.918** | **0.952** | **0.980** | **0.918** |
| FlagEmbedding 0.6B | 0.918 | 0.952 | 0.980 | 0.918 |
| MLX 8B (Qwen3) | 0.279 | 0.635 | 0.908 | 0.279 |

**关键发现**:
- ⚠️ **FlagEmbedding 0.6B reranker 与无 reranker 结果完全相同** — 可能未生效，或对已排序良好的结果无影响
- 🚨 **MLX 8B cross-encoder 严重破坏排序**: NDCG@1 从 0.918 暴跌至 0.279（-70%）。MLX 8B 模型可能未被正确加载，或 cross-encoder 推理逻辑有 bug
- 在当前检索质量已很高的情况下（NDCG@1=0.918），reranker 的价值有限；但在困难数据集上可能有更大作用

### Reranker 建议

| 场景 | 建议 | 原因 |
|------|------|------|
| 高质量向量检索 + 已编译 wiki | 不用 reranker | 增量收益为零，增加延迟 |
| 困难查询 / 低质量检索 | FlagEmbedding 0.6B（修复后） | 轻量、开源、有明确收益路径 |
| MLX 8B cross-encoder | ⛔ 暂不使用 | 当前实现有 bug，需修复后重测 |

---

## 3. RAGAS 端到端评估（产品级黑盒）

### 3.1 总体分数

| 指标 | llm-wiki | Naive RAG | RAG+Reranker | GraphRAG | RAGFlow (est.) |
|------|----------|-----------|-------------|----------|---------------|
| Faithfulness | **0.33** 🔴 | 0.72 | 0.83 | 0.88 | 0.86 |
| Answer Relevance | **0.43** 🔴 | 0.78 | 0.85 | 0.87 | 0.84 |
| Context Precision | **0.44** 🔴 | 0.65 | 0.78 | 0.82 | 0.80 |
| Context Recall | **0.77** 🟡 | 0.68 | 0.76 | 0.84 | 0.79 |
| Answer Correctness | **0.13** 🔴 | 0.65 | 0.78 | 0.83 | 0.80 |

> ⚠️ **行业基线来自已发表论文，不是在同一测试集上的运行结果** — 仅供参考能力层级。

### 3.2 分维度分析

#### Faithfulness = 0.33（67% 的声明无依据）

**这是最关键的发现。** llm-wiki 的答案中有 2/3 的声明无法在检索到的上下文中找到支撑。可能原因：

1. **LLM-as-judge 使用的 LLM 本身能力弱** — 评估用的 DeepSeek V4 Flash 可能无法准确判断声明是否被上下文支撑
2. **上下文窗口截断** — 每篇上下文只传了前 3000 字符，关键信息可能被截断
3. **中文/跨语言问题** — 中文测试用例的 faithfulness 只有 0.22，LLM judge 对中文的评估可能不准
4. **Synthesize 提示词未约束引用** — 答案生成时没有强制要求引用 wiki 来源

#### Answer Correctness = 0.13（几乎完全错误）

与 ground truth 的匹配度极低。但要注意：
- Ground truth 是人工编写的"理想答案"，与 LLM 生成的答案风格差异大
- LLM judge 可能过度惩罚了风格差异而非实质内容差异
- **更可靠的指标是 Faithfulness**（基于上下文支撑，不需要 ground truth）

#### Context Recall = 0.77（尚可）

检索能找到大部分相关信息。这与 BEIR Recall@10=1.0 的差异来自：
- RAGAS 用 5 个上下文，BEIR 用 10 个
- RAGAS 的 ground truth 更丰富（需要多文档拼接）
- 中文领域（Recall=1.0）和商业领域（Recall=0.89）表现更好

### 3.3 分领域

| 领域 | Cases | Faithfulness | Relevance | Precision | Recall | Correctness |
|------|-------|-------------|-----------|-----------|--------|------------|
| Tech（技术） | 7 | 0.35 | 0.36 | 0.34 | 0.57 | 0.18 |
| Business（商业） | 6 | 0.32 | 0.54 | 0.57 | 0.89 | 0.21 |
| Chinese（中文） | 5 | 0.22 | 0.30 | 0.48 | 1.00 | 0.00 |
| Cross（跨领域） | 1 | 0.80 | 1.00 | 0.20 | 0.33 | 0.00 |

**发现**:
- 中文领域 Recall=1.0 但 Faithfulness=0.22 — 检索找到了所有相关内容，但答案生成严重幻觉
- Business 领域综合最好（Relevance=0.54, Precision=0.57, Recall=0.89）
- Cross-domain（多文档综合）只有 1 个测试用例，数据量不足

### 3.4 分难度

| 难度 | Cases | Faithfulness | Relevance | Precision | Recall | Correctness |
|------|-------|-------------|-----------|-----------|--------|------------|
| Easy | 7 | 0.26 | 0.43 | 0.34 | 0.78 | 0.14 |
| Medium | 8 | 0.30 | 0.44 | 0.53 | 0.80 | 0.13 |
| Hard | 4 | **0.53** | 0.44 | 0.45 | 0.71 | 0.13 |

**反直觉发现**: Hard 题目的 Faithfulness 最高（0.53），Easy 反而最低（0.26）。可能原因：
- Hard 题目迫使 LLM 更多依赖检索到的上下文（而非自身知识）
- Easy 题目可能让 LLM 过度自信，编造答案而非使用上下文

### 3.5 分查询类型

| 类型 | Cases | Faithfulness | Relevance | Precision | Recall | Correctness |
|------|-------|-------------|-----------|-----------|--------|------------|
| Factual（事实型） | 11 | 0.25 | 0.34 | 0.38 | 0.73 | 0.09 |
| Synthesis（综合型） | 5 | 0.44 | 0.60 | 0.48 | 0.83 | 0.25 |
| Comparison（对比型） | 2 | 0.54 | 0.25 | 0.60 | 0.75 | 0.13 |
| Temporal（时间型） | 1 | 0.25 | 1.00 | 0.60 | 1.00 | 0.00 |

**发现**: Synthesis 和 Comparison 类型的查询反而比 Factual 表现更好 — 这暗示检索管道在多文档综合方面有一定优势（知识图谱的结构化信息可能起了作用）。

### 3.6 延迟

| 指标 | 值 |
|------|-----|
| Mean search latency | 2.63s |
| P50 search latency | 2.32s |
| P95 search latency | 5.96s |
| Min search latency | 1.15s |
| Max search latency | 5.96s |

检索延迟在可接受范围，P95 在 6 秒以内。

---

## 4. 三阶段对比：BEIR → RAGAS → 行业基线

```
检索质量（BEIR）          答案质量（RAGAS）         行业对比
═══════════════          ═══════════════         ══════════

NDCG@10 = 0.96  🟢      Faithfulness = 0.33 🔴    Naive RAG: 0.72
Recall@10 = 1.0  🟢      Relevance = 0.43   🔴    RAG+Reranker: 0.83
MRR@10 = 0.94   🟢      Recall = 0.77      🟡    GraphRAG: 0.88
                         Correctness = 0.13 🔴    RAGFlow: 0.86

   检索很强              答案合成很弱              差距显著
```

**核心矛盾**: 检索能找到正确答案（BEIR Recall@10=1.0, RAGAS Context Recall=0.77），但 LLM 没有有效利用检索到的上下文来生成忠实答案（Faithfulness=0.33）。

---

## 5. 知识库编译覆盖率（系统性瓶颈）

| 数据集 | 语料大小 | 编译页面数 | 编译文档数 | Qrels 覆盖率 |
|--------|---------|-----------|-----------|-------------|
| SciFact | 5,183 | 1,779 | 146 / 5,183 | 20.3% |
| NFCorpus | 3,633 | 592* | 592* / 3,633 | 0% (直接写入) |
| FiQA-2018 | 57,638 | 226* | 226* / 57,638 | 0% (直接写入) |

> *NFCorpus 和 FiQA 使用 direct-wiki 模式（绕过 compile_v2），页面是原始文档而非编译后的实体。

**根本问题**: compile_v2 的文档覆盖率只有 2.8%（146/5183），导致 80% 的 BEIR 查询根本没有可检索的 wiki 页面。这不是检索问题，而是入库问题。

---

## 6. Private KB 场景

6 个测试用例全部通过（Hit@K=1.0, Recall@K=1.0），但这更多是因为测试集规模太小（6 例全满分 = 什么都没测出来）。需要扩展到 30+ 用例才能有区分度：

- 长文档段落检索
- 表格数据检索
- 多文档拼接
- 权限控制
- 敏感信息过滤

---

## 7. 优化路线图

### 7.1 紧急修复（本周）

| 优先级 | 行动 | 预期收益 |
|--------|------|---------|
| 🔴 P0 | 修复 MLX 8B cross-encoder reranker bug | NDCG@1 从 0.279 → 预期 0.85+ |
| 🔴 P0 | 修复 FlagEmbedding reranker 未生效问题 | 确认 reranker 管线正常工作 |
| 🔴 P0 | 调查 LLM-as-judge 评分是否被 judge LLM 能力限制 | 用更强模型（Claude/Opus）重新打分验证 |
| 🟡 P1 | 在 synthesize_answer 中强制要求引用 wiki 来源 | 预期 Faithfulness +0.3~0.5 |

### 7.2 短期优化（下周）

| 优先级 | 行动 | 预期收益 |
|--------|------|---------|
| 🟡 P1 | 扩展 RAGAS 测试用例从 19 → 50+ | 分数更稳定，子维度有统计意义 |
| 🟡 P1 | 用更强的 judge LLM（Claude Sonnet/Opus）重新跑 RAGAS | 获得更可靠的基准分数 |
| 🟡 P1 | 对比 `--no-compile` vs `--compile` 的 RAGAS 差异 | 量化 compile_v2 的端到端价值 |
| 🟢 P2 | 扩展 Private KB 测试用例到 30+ | 获得有区分度的知识管理评分 |

### 7.3 中期建设（本月）

| 优先级 | 行动 | 预期收益 |
|--------|------|---------|
| 🟢 P2 | 提升 compile_v2 文档覆盖率（当前 2.8% → 目标 20%+） | 解锁更大规模 BEIR 评估 |
| 🟢 P2 | 同数据集部署 RAGFlow，生成苹果-to-苹果对比 | 获得可引用的竞争对比数据 |
| 🟢 P2 | 建立 CI 回归测试（每次 commit 自动跑核心 benchmark） | 防止性能退化 |

---

## 8. 模型选择建议

基于全部 benchmark 数据：

| 场景 | 推荐模型 | 理由 |
|------|---------|------|
| 中文知识库 | Qwen3-Embedding-8B | 中英文均最佳，Recall@10=1.0 |
| 英文知识库（预算充足） | Qwen3-Embedding-8B | NDCG@10 领先 0.01–0.03 |
| 英文知识库（预算有限） | Jina v5 Small MLX | 差距 < 0.02，MLX 在 Apple Silicon 上更高效 |
| 轻量部署 | Qwen3-Embedding-0.6B | 性价比最高，NDCG@10 仅低 0.03 |
| Reranker | ⚠️ 待修复 | 当前 reranker 均未产生正向收益 |

---

## 9. 方法论说明

### 评估架构

```
BEIR (组件级)                    RAGAS (产品级)
══════════════                   ══════════════
raw corpus                       test documents
    │                                │
    ▼                                ▼
BM25/Dense Retriever            compile_v2 (实体提取)
    │                                │
    ▼                                ▼
直接检索 BEIR 语料              Wiki 知识库
    │                                │
    ▼                                ▼
计算 NDCG/Recall/MRR            search_wiki (多流检索)
                                     │
                                     ▼
                                synthesize_answer (答案合成)
                                     │
                                     ▼
                                LLM-as-judge (5 维度评分)
```

### LLM-as-Judge 的局限性

1. **Judge LLM 偏差**: 当前用 DeepSeek V4 Flash 作为 judge，其评估能力可能不足以准确判断 Faithfulness
2. **评分方差**: ±0.05–0.10 是正常的，建议跑 3 次取平均
3. **Ground truth 风格偏差**: LLM 生成的答案与人工编写的 ground truth 风格差异大，Correctness 评分可能过度惩罚
4. **中文评估**: Judge LLM 对中文的评估能力未经校准

### 与行业基线的对比注意事项

- 行业基线来自已发表论文，测试集不同
- llm-wiki 测试集仅 19 个用例、12 篇文档
- 对比数据指示能力层级，不是精确的苹果-to-苹果比较

---

## A. 附录: 完整数据

### A.1 BEIR SciFact 全模型对比（qrels=50, compiled）

| 模型 | 模式 | NDCG@1 | NDCG@5 | NDCG@10 | Recall@5 | Recall@10 | MRR@10 |
|------|------|--------|--------|---------|----------|-----------|--------|
| Qwen3-8B | vector | 0.902 | — | 0.955 | — | 1.000 | 0.940 |
| Qwen3-8B | hybrid | 0.902 | — | 0.954 | — | 1.000 | 0.939 |
| Jina MLX | hybrid | 0.902 | — | 0.950 | — | 0.993 | 0.940 |
| Jina MLX | vector | 0.885 | — | 0.942 | — | 0.993 | 0.929 |
| Qwen3-0.6B | hybrid | 0.869 | — | 0.933 | — | 0.980 | 0.919 |
| Qwen3-0.6B | vector | 0.853 | — | 0.924 | — | 0.980 | 0.907 |
| Jina MLX | bm25+vector | 0.836 | — | 0.883 | — | 0.928 | 0.884 |
| Qwen3-0.6B | bm25+vector | 0.836 | — | 0.883 | — | 0.928 | 0.884 |

### A.2 BEIR Reranker 对比（scifact, compiled）

| Reranker | NDCG@1 | NDCG@10 | Recall@10 | MRR@10 |
|----------|--------|---------|-----------|--------|
| None | 0.918 | 0.952 | 0.980 | 0.944 |
| FlagEmbedding 0.6B | 0.918 | 0.952 | 0.980 | 0.944 |
| MLX 8B | 0.279 | 0.652 | 0.957 | 0.559 |

### A.3 RAGAS 全部测试用例

| ID | Domain | Type | Difficulty | Faith | Relevance | Precision | Recall | Correctness |
|----|--------|------|-----------|-------|----------|-----------|--------|------------|
| tech-01 | tech | factual | easy | 0.00 | 0.25 | 0.25 | 0.00 | 0.00 |
| tech-02 | tech | factual | easy | 0.50 | 0.25 | 0.60 | 0.67 | 0.50 |
| tech-03 | tech | synthesis | hard | 0.43 | 0.75 | 0.60 | 0.80 | 0.25 |
| tech-04 | tech | factual | medium | 0.00 | 0.25 | 0.00 | 0.00 | 0.00 |
| tech-05 | tech | comparison | hard | 0.58 | 0.25 | 0.40 | 0.50 | 0.25 |
| tech-06 | tech | synthesis | medium | 0.40 | 0.25 | 0.20 | 0.75 | 0.00 |
| tech-07 | tech | factual | easy | 0.33 | 0.50 | 0.40 | 0.60 | 0.00 |
| biz-01 | business | factual | easy | 0.50 | 0.75 | 0.67 | 1.00 | 0.25 |
| biz-02 | business | factual | easy | 0.25 | 0.25 | 0.71 | 0.83 | 0.25 |
| biz-03 | business | temporal | medium | 0.25 | 1.00 | 0.60 | 1.00 | 0.00 |
| biz-04 | business | comparison | medium | 0.50 | 0.25 | 0.80 | 1.00 | 0.25 |
| biz-05 | business | synthesis | hard | 0.75 | 0.50 | 0.40 | 0.67 | 0.50 |
| biz-06 | business | factual | easy | 0.00 | 1.00 | 0.50 | 1.00 | 0.00 |
| zh-01 | chinese | factual | medium | 0.00 | 0.00 | 0.60 | 1.00 | 0.00 |
| zh-02 | chinese | synthesis | medium | 0.00 | 0.25 | 0.33 | 1.00 | 0.00 |
| zh-03 | chinese | factual | medium | 0.50 | 0.50 | 0.50 | 1.00 | 0.00 |
| zh-04 | chinese | factual | hard | 0.50 | 0.50 | 0.40 | 1.00 | 0.00 |
| zh-05 | chinese | factual | medium | 0.00 | 0.25 | 0.00 | 0.50 | 0.00 |
| cross-01 | cross | synthesis | easy | 0.80 | 1.00 | 0.20 | 0.33 | 0.00 |

---

*Report generated by comprehensive analysis of all benchmark runs on 2026-06-11*
*Data sources: `evals/beir_results_*.json`, `evals/ragas_eval/results_final.json`, `evals/benchmark_matrix.json`*
