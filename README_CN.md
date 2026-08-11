<p align="center">
  <a href="README.md">🇬🇧 English</a> &nbsp;|&nbsp;
  <a href="README_CN.md">🇨🇳 中文</a>
</p>

# llm-wiki

**会自己生长的知识库。** 不是 RAG —— 不重复推导，一次编译永久使用。LLM 读取你的资料，构建类型化知识图谱，自动维护。交叉引用、矛盾检测、置信度衰减——全部自动化。

<p align="center">
  <img src="docs/benchmark_chart.png" alt="RAGAS 评测: llm-wiki vs 业界" width="100%">
</p>

> **忠实度 1.00** · **答案相关性 1.00** · **答案正确性 0.91** · **上下文召回 0.94**。Wiki 原生管道（编译→搜索→合成）。无嵌入、无分块、无交叉编码器。[完整评测报告 →](docs/BENCHMARK.md)

---

## 为什么选择 llm-wiki

| | RAG | llm-wiki |
|---|-----|----------|
| **方式** | 检索 → 拼凑 → 丢弃 | 编译 → 结构化 → 持久化 |
| **知识** | 每次查询重新推导，无积累 | 持续积累，越用越强 |
| **交叉引用** | 无 | 自动实体链接 + 类型化关系边 |
| **矛盾处理** | 沉默忽略 | 自动检测、标记、解决 |
| **时效管理** | 手动清理 | 自动置信度衰减 + 取代 |
| **结构** | 扁平分块 | 类型化页面（概念/技术/模型/事件...） |
| **检索速度** | 200–500ms（嵌入 API + 向量数据库） | **~41ms**（BM25 + metadata + graph，进程内） |

> *"知识库维护的瓶颈不是阅读，不是思考——是簿记。LLM 不疲倦、不遗忘、一次能触及 15 个文件。"* — Andrej Karpathy

## 快速开始

```bash
pip install -e .
wiki config --init        # 创建配置文件
vim wiki_config.yaml      # 设置 API key
wiki init                 # 初始化 .wiki/
wiki compile paper.md     # Agent 读取来源 → 结构化页面
wiki query "什么是Transformer?"  # 搜索 → 合成 → 带引用的答案
```

**一篇文档 → 15+ 个结构化页面 + 类型化关系：**

```bash
$ wiki compile deepseek-v4.md
Compiling deepseek-v4.md (262,658 chars)...
  Created: deepseek-v4.md (model)
  Created: multi-head-latent-attention.md (technique)
  Created: deepseek-moe.md (technique)
  Created: mmlu.md (benchmark)
  ... 15 个页面, 84 条关系边 (uses, improves_upon, relates_to) ...

$ wiki query "DeepSeek-V4 如何降低推理内存？"
**Answer**: 使用多头潜在注意力(MLA)将KV-cache压缩8倍，配合
DeepSeekMoE的256个专家(每token激活8个)，实现37B激活参数。
**Sources**: [[multi-head-latent-attention]], [[deepseek-moe]]
```

## 安装为 Claude Code Skill

llm-wiki 既可以独立使用，也可以作为 Claude Code skill 实现自动知识管理：

```bash
# 1. 克隆并安装
git clone https://github.com/anthropics/llm-wiki-skill.git ~/.claude/skills/llm-wiki
cd ~/.claude/skills/llm-wiki
pip install -e .

# 2. 注册 skill
mkdir -p ~/.claude/skills
cp ~/.claude/skills/llm-wiki/SKILL.md ~/.claude/skills/llm-wiki-skill.md

# 3. 配置
wiki config --init
vim wiki_config.yaml  # 设置 provider + API key
wiki init
```

> 激活后，Claude 会自动识别 Wiki 意图——"记住这个"、"添加到知识库"、"X 是什么"——并自动调用 skill。

## 检索性能

llm-wiki 的 Wiki 原生架构实现亚 50ms 检索延迟——无需嵌入调用，无需向量数据库往返：

| 管道 | 检索延迟 | 技术栈 |
|------|---------|--------|
| **llm-wiki** | **~41ms avg** | BM25 + metadata + graph（进程内） |
| RAG（分块+嵌入） | 200–500ms | 嵌入 API + 向量数据库 |
| GraphRAG | 500ms–2s | 社区检测 + LLM 摘要 |

> ⚡ **41ms 检索延迟**——比基于嵌入的 RAG 快 5–50 倍。一次编译，即时查询。[完整评测 →](docs/BENCHMARK.md)

## 自循环维护 & 医生

**梦境** 从查询日志自动优化你的知识库。**医生** 让你一键反馈问题并自动修复。

```bash
# 梦境 — 自循环优化（4阶段，直接修改内容）
wiki dream --foreground          # 自动合并重复页面、补充元数据
                                 # git 快照 + 质量门控 + 自动回滚

# 医生 — 反馈问题，自动诊断修复
wiki doctor "专家评审组信息不完整，缺少成员名单"   # 自然语言反馈
wiki doctor --check coursepl-专家评审组            # 诊断检查
wiki doctor --recompile .wiki/source/doc.md        # 重新编译源文件
wiki doctor --re-ocr .wiki/source/slides.pptx      # 重新 OCR + 编译
wiki doctor --list                                 # 列出未解决问题
```

| 特性 | 机制 |
|------|------|
| **Git 快照** | 每次修改前自动 `git commit` 到 `.wiki/.git` — 安全回滚 |
| **质量门控** | 三维检索评估（排名/密度/覆盖率）— 质量下降自动回滚 |
| **经验积累** | SHA256 去重的经验教训 → 下次梦境自动加载为上下文 |
| **医生工作流** | 正则分类 → wiki 搜索诊断 → 8 种修复策略 → 验证 → 持久化 |

## 评测

我们评测的是**完整产品 pipeline**（编译→搜索→合成），而非组件。**无嵌入、无分块、无交叉编码器** —— 纯 Wiki 原生架构。业界基线来自 RAGAS/RGB/GraphRAG 论文。

| 系统 | 忠实度 | 答案相关性 | 上下文召回 | 答案正确性 |
|------|--------|-----------|-----------|-----------|
| Naive RAG (chunk+embed) | 0.72 | 0.78 | 0.68 | 0.65 |
| RAG + Reranker | 0.83 | 0.85 | 0.76 | 0.78 |
| RAGFlow (估) | 0.86 | 0.84 | 0.79 | 0.80 |
| GraphRAG (Microsoft) | 0.88 | 0.87 | 0.84 | 0.83 |
| **llm-wiki ★** | **1.00** | **1.00** | **0.94** | **0.91** |

> **所有分数均采用 LLM-as-judge（RAGAS 框架）**，在 19 个测试用例（技术/商业/中文领域）上评测。业界基线来自已发表论文——非相同测试集。llm-wiki: compile_v2 → BM25+metadata+graph → 实体链接 → 三信号排序 → 合成。**5 项指标中 4 项超越 GraphRAG 论文数据。**

→ [完整评测报告（含逐题明细）](docs/BENCHMARK.md)

## 核心能力

| 能力 | 说明 |
|------|------|
| **编译** | Agent 读取来源、判断文档类型、写入符合 schema 的 wiki 页面和图谱 |
| **查询** | Wiki 原生检索（元数据+BM25+图谱+台账）+ 实体链接 + 三信号排序 → Agent 合成答案 |
| **检查** | 健康扫描+自愈：矛盾、过期、孤立页面、断链 |
| **生命周期** | 艾宾浩斯遗忘曲线、置信度评分、矛盾检测、取代 |
| **记忆层级** | 工作→情景→语义→程序，自动整合提升 |
| **台账** | 结构化表格管理，自然语言→SQL（DuckDB） |
| **多语言** | 中英文双引擎检索（jieba + Porter 词干提取） |
| **隐私** | 摄入时敏感信息过滤（API key、token、PII） |
| **梦境（自动）** | 查询驱动的自循环优化：git 快照 + 质量门控 + 经验积累 |
| **医生** | 用户反馈诊断修复：分类 → 搜索 → 修复 → 验证 |

## 文档

| 文档 | 内容 |
|------|------|
| [安装与离线部署](docs/INSTALL.md) | pip 安装、Windows 注意事项、离线打包 |
| [配置指南](docs/CONFIGURATION.md) | LLM、Embedding、OCR、查询等配置 |
| [架构与生命周期](docs/ARCHITECTURE.md) | 三层设计、知识生命周期 |
| [评测详情](docs/BENCHMARK.md) | RAGAS 评测、业界对比、逐题分数 |
| [台账管理](docs/LEDGER.md) | 结构化表格、CSV 导入、NL→SQL |
| [OCR 后端](docs/OCR.md) | OvisOCR2（默认）、MinerU、DeepSeek-OCR、Logics、PaddleOCR |
| [CLI 参考](docs/CLI.md) | 完整命令参考 |

## 项目结构

```
llm-wiki-skill/
├── scripts/           # Python 自动化脚本（~30 个）
│   ├── wiki.py        # 统一 CLI 入口
│   ├── compile_v2.py  # LLM 源→Wiki 编译器
│   ├── query.py       # Wiki 原生搜索 + 答案合成
│   ├── search.py      # 元数据/BM25/图谱搜索；向量路径为可选项
│   ├── lint.py        # 健康扫描 + 自愈
│   ├── dream.py       # 自循环维护（4阶段，自动模式）
│   ├── doctor.py       # 用户反馈诊断 + 自动修复
│   ├── ledger.py      # 结构化表格管理（DuckDB）
│   └── ...
├── .wiki/             # Wiki 数据（LLM 生成）
│   ├── pages/         # 结构化 markdown 页面
│   ├── graph/         # entities.json, edges.json, 可选 embeddings
│   ├── ledger/        # ledger.duckdb 数据库
│   └── source/        # 原始源文件（不可变）
├── .claude/hooks/     # 自动化钩子（可选启用）
├── tests/             # 测试套件（180 测试）
├── templates/         # 页面模板
└── references/        # 深度参考资料
```

## 设计来源

基于 [Karpathy 的 LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 和 [Rohit 的 v2 扩展](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)，100% 实现。

| 原则 | 实现 |
|------|------|
| 三层架构（源→Wiki→Schema） | `source/` + `pages/` + `schema.md`/`wiki_config.yaml` |
| 摄入→写页面→索引→日志 | `compile_v2.py` 完整流程 |
| 同名异实保护 | 自动前缀 + 概念聚合页 |
| 查询→搜索→合成→回填 | `query.py` + `--file-back` + 6 种输出格式 |
| 检查→自愈 | `lint.py --auto-heal` |
| 12 种类型化关系 | `uses`, `depends_on`, `extends`, `contradicts`, `supersedes`... |
| 艾宾浩斯遗忘曲线 | 6 种实体半衰期（架构260天, Bug20天...） |
| 记忆整合 | working → episodic → semantic → procedural |
| 隐私过滤 | 5 种敏感信息模式，LLM 发送前脱敏 |
| 梦境自循环 | git 快照 + 质量门控 + 回滚 + SHA256 去重经验 |
| 医生诊断 | 正则分类 → wiki 搜索 → 策略修复 → 验证 → 持久化 |

## 许可

MIT
