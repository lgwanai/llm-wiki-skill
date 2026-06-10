# llm-wiki 黑盒产品评估方案

## 问题诊断：当前 Benchmark 为什么是错的

### 当前做了什么

| 测试 | 测的是什么 | 问题 |
|------|-----------|------|
| BEIR benchmark (`benchmark_beir.py`) | BM25/Dense/Hybrid 检索器在 BEIR 数据集上的 NDCG/Recall/MRR | **测的是 embedding 模型选型，不是产品能力** — 用户用的不是 `BM25Retriever` 类，用户用的是 `wiki query "xxx"` 完整流程 |
| 多模型对比 (Qwen3-8B vs 0.6B vs Jina) | Embedding 模型 A/B test | 用户不关心你用什么 embedding，用户关心"我问的问题能不能找到对的页面、能不能得到对的答案" |
| Private KB benchmark | 6 个合成用例的检索命中率 | 规模太小(6例全满分=什么都没测出来)，且只测了 retrieval 不测 answer synthesis |

### 问题本质

```
当前测的是: 零件 → 零件 vs. 零件 → 有效结论
应该测的是: 完整产品 → 完整产品 vs. 完整产品 → 有效结论
```

用户使用路径是：

```
用户导入文档 → Wiki 编译(实体抽取/关系图/分块) → 用户提问 → 多流检索 
→ RRF 融合 → LLM 合成答案 → 用户获得答案+来源
```

**这 7 个环节中，当前 benchmark 只覆盖了"多流检索"这一个环节，还只测了其中独立的 BM25/Dense retriever，根本没走完整 pipeline。**

---

## 正确的评估维度

对于一个知识库产品，用户关心的维度是：

### 维度一：知识入库质量 (Ingest Quality)

| 指标 | 含义 | 怎么测 |
|------|------|--------|
| 实体识别准确率 | 导入文档后，自动提取的实体是否准确 | 人工标注 ground truth 实体，对比 compile 输出 |
| 关系抽取准确率 | `uses/depends_on/supersedes` 关系是否正确 | 人工标注 ground truth 关系图 |
| 分块质量 | 分块是否保持了语义完整性 | 检查 chunk 边界是否切断关键语义 |
| 敏感信息过滤 | API key/密码/PII 是否正确过滤 | 构造含敏感信息的文档，检查是否被写入 wiki |
| 去重/更新 | 重复导入是否产生重复实体，更新是否正确合并 | 多次导入同一文档的变体 |

### 维度二：检索质量 (Retrieval Quality)

| 指标 | 含义 | 怎么测 |
|------|------|--------|
| Hit@K | 正确答案是否在 Top-K 结果中 | 人工标注 QA 对，走完整 `search_wiki()` |
| MRR | 正确答案的平均排名倒数 | 同上 |
| NDCG@K | 排名质量 | 同上，标注 relevance score |
| 多语言覆盖 | 中英文混合检索是否有效 | 构造中英混合查询 |
| 跨文档推理 | 答案需要多篇文档拼接才能得到 | 构造 multi-hop 查询 |

### 维度三：答案合成质量 (Answer Synthesis Quality)

这是 **产品最核心的能力**，也是当前完全没测的。

| 指标 | 含义 | 怎么测 |
|------|------|--------|
| Faithfulness (忠实度) | 答案是否完全基于 wiki 内容，有无编造 | LLM-as-judge: 逐句检查是否有 wiki 来源支持 |
| Answer Relevance (相关性) | 答案是否切题 | LLM-as-judge: 对 query 的覆盖度 |
| Context Recall (上下文召回) | 答案是否遗漏了 wiki 中的关键信息 | 对比 ground truth answer 和 wiki 原文 |
| Citation Accuracy (引用准确性) | 答案中的 `[[引用]]` 是否指向正确的页面 | 检查引用链接是否真实存在且内容相关 |
| Hallucination Rate (幻觉率) | 答案中无法在 wiki 中找到依据的比例 | LLM-as-judge + 人工抽检 |

### 维度四：知识生命周期管理 (Lifecycle)

这是 **llm-wiki 区别于普通 RAG 产品的核心差异**。

| 指标 | 含义 | 怎么测 |
|------|------|--------|
| 时效性 | 时间敏感问题是否返回最新信息 | 构造版本演化的文档序列，检查旧版本是否被淘汰 |
| 矛盾检测 | 两个文档说相反的事，能否发现 | 导入矛盾文档，检查 lint 输出 |
| 置信度衰减 | 旧知识的置信度是否随时间下降 | 长期观测 |
| 记忆层级提升 | working→episodic→semantic 是否正确流转 | consolidate 前后对比 |

### 维度五：工程能力 (Engineering)

| 指标 | 含义 | 怎么测 |
|------|------|--------|
| 导入吞吐 | 每秒能导入多少文档 | 大语料导入测速 |
| 检索延迟 | P50/P95/P99 查询延迟 | 压测 |
| 索引大小 | embedding 索引的存储开销 | 存储统计 |
| 并发能力 | 多用户同时查询/导入 | 并发测试 |

---

## 对标产品 & 公开数据

### 对标产品

| 产品 | 定位 | 核心差异 |
|------|------|---------|
| **RAGFlow** (infiniflow) | 开源 RAG 引擎，深度文档解析 | 有公开 benchmark，强调文档解析(OCR/表格)和 chunking 策略 |
| **Dify** | 开箱即用的 LLM 应用平台 | 知识库是其一个子功能，强调易用性和工作流编排 |
| **FastGPT** | 知识库 + 对话 | 强调 QA 质量 |
| **LlamaIndex** | RAG 开发框架 | 有评估模块，但不是产品 |
| **Anything LLM** | 桌面端 RAG 应用 | 面向终端用户 |
| **llm-wiki** (本项目) | **个人知识库**，强调知识生命周期管理和结构化 | 不是一次性 RAG，是持续积累的知识系统 |

### 已知的公开 Benchmark

#### RAGFlow 的评估
- RAGFlow 在 GitHub 上有 `deepdoc` 模块的 benchmark
- 主要评测文档解析质量：表格识别、布局分析、OCR
- 检索方面使用 RAGAS 评估框架
- **关键数据点**：RAGFlow 强调其 DeepDoc 解析在复杂 PDF/表格场景下优于 Unstructured/LlamaParse

#### RAG 系统通用评测框架

1. **RAGAS** (ragas.io) — 最广泛使用的 RAG 评估框架
   - 维度：Faithfulness, Answer Relevancy, Context Precision, Context Recall, Context Entity Recall, Answer Correctness
   - 需要 ground truth 或 LLM-as-judge
   - **这是当前 RAG 产品对比的事实标准**

2. **RGB** (Benchmark for RAG) — 中英文双语 RAG benchmark
   - 包含 600 个中文 QA + 600 个英文 QA
   - 评估维度：Noise Robustness, Negative Rejection, Information Integration, Counterfactual Robustness
   - 有公开的 baseline 分数

3. **CRUD-RAG** — 知识库 CRUD 操作 benchmark
   - 评估知识库的创建、检索、更新、删除能力
   - 与 llm-wiki 的知识生命周期管理高度相关

4. **BEIR / MTEB** — 纯检索 benchmark
   - 只测 embedding + retrieval，不测完整 pipeline
   - 适合选 embedding 模型，**不适合做产品对比**

---

## 实施方案

### 第一阶段：RAGAS 端到端评估（本周）

**目标**：获得第一个有意义的完整产品评估分数

```
测试集 → compile_v2 → wiki pages → search_wiki → synthesize_answer → RAGAS 评分
```

#### 1.1 构造测试数据集

选择 3 个领域的文档集（每个 20-50 篇），覆盖：
- 技术文档（如 AI/ML 论文/博客）
- 业务文档（含表格、多版本）
- 中文内容

每篇文档生成：
- 3-5 个事实型查询（答案在单篇文档中）
- 1-2 个综合型查询（答案需要跨文档）
- 1-2 个时间敏感查询
- Ground truth answer + relevant page IDs

#### 1.2 实现评估脚本 `benchmark_ragas.py`

```python
# 黑盒流程
for each test_case:
    # Step 1: 确保文档已入库（通过 compile_v2）
    # Step 2: 搜索
    pages = search_wiki(query)  # 完整 pipeline
    # Step 3: 合成答案
    answer = synthesize_answer(query, pages)
    # Step 4: RAGAS 评估
    scores = evaluate_ragas(
        query=query,
        answer=answer,
        contexts=[read_page(p) for p in pages],
        ground_truth=test_case.ground_truth,
    )
```

输出：
- Faithfulness score
- Answer Relevance score
- Context Precision/Recall
- 总体 RAGAS score

#### 1.3 建立 Baseline 对比

使用相同的测试集，对以下 baseline 进行对比：
- **Raw RAG baseline**：直接用 embedding + LLM，不走 wiki compile
- **llm-wiki full pipeline**：完整 wiki 流程
- **理想上界**：人工标注的 ideal ranking + LLM synthesis

### 第二阶段：多产品对比（下周）

**目标**：同数据集、同指标下对比 llm-wiki vs RAGFlow vs Dify

#### 2.1 使用 RGB 公开数据集

- RGB 提供了标准化的测试集和评估脚本
- 在相同数据集上部署 llm-wiki 和对比产品
- 生成可比较的分数

#### 2.2 使用 RAGAS 公开 benchmark

- RAGAS 社区有一些公开的 benchmark 数据集
- 收集 RAGFlow/Dify 等产品的公开分数

#### 2.3 自行对比测试

如果找不到公开的苹果-to-苹果对比数据：
- 在同一台机器上部署 RAGFlow 和 Dify
- 使用相同的文档集和相同的测试 query
- 用相同的 RAGAS 指标评估

### 第三阶段：知识生命周期专项评估（后续）

**目标**：评估 llm-wiki 独有的知识管理能力

- CRUD 能力测试（创建、更新、删除知识）
- 矛盾检测准确性
- 置信度衰减合理性
- 版本演化的检索正确性

---

## 立即可用的对比数据（来自公开来源）

### RAGFlow 官方公布的分数（来自 GitHub README）

| 数据集 | RAGFlow 指标 | 分数 |
|--------|-------------|------|
| DeepDoc 表格识别 | TEDS | ~0.95 |
| DeepDoc 布局分析 | mAP | ~0.90 |
| RAGAS (内部测试) | Faithfulness | ~0.92 |

### 通用 RAG 基线（来自 RAGAS/RGB 论文）

| 方法 | Faithfulness | Answer Relevance | Context Recall |
|------|-------------|-----------------|----------------|
| Naive RAG (chunk + embed + LLM) | ~0.75 | ~0.80 | ~0.70 |
| RAG + Reranker | ~0.85 | ~0.85 | ~0.80 |
| GraphRAG | ~0.88 | ~0.88 | ~0.85 |

---

## 下一步行动

1. **立即停止**：多 embedding 模型对比测试（Qwen vs Jina vs BGE）—— 这些对产品评估毫无意义
2. **立即开始**：构造 3 领域测试数据集（技术/业务/中文），每个 20 篇文档 + 5-8 个 QA
3. **本周完成**：实现 `benchmark_ragas.py`，走完整黑盒 pipeline，获得第一份有意义的评估分数
4. **下周完成**：部署 RAGFlow，同数据集对比，生成对比报告
5. **长期建设**：积累测试用例到 200+ 条，建立回归测试体系

---

*Created: 2026-06-10*
*Author: Claude (based on user's frustration with component-level testing)*
