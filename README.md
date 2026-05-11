# llm-wiki-skill

**LLM Wiki v2** — 让 LLM 替你维护知识库。读完即归档，永不遗忘。

> 100% 实现 [Karpathy 的 LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 和 [Rohit 的 v2 扩展](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)。

---

## 原理

### 问题

RAG 检索即忘。每次提问，LLM 重新从原始文档中拼凑答案——**没有积累**。五个文档交叉引用的问题？每次都要重新发现。

### 方案

不是检索，而是**编译**。LLM 读源文档，提取实体，构建结构化的 Wiki，维护交叉引用，标记矛盾。知识被编译一次，然后**持续保鲜**——不是每次查询重新推导。

```
RAG:    Source → [检索] → LLM 即时合成 → 回答 → 丢弃
Wiki:   Source → [编译] → Wiki 持久化 → 查询时直接使用已有知识
```

### 核心洞察

> 知识库维护的瓶颈不是阅读，不是思考——是**簿记**。更新交叉引用、保持摘要新鲜、标记新旧矛盾、维持数十页面的一致性。人类放弃 Wiki 是因为维护负担增长超过价值。**LLM 不疲倦、不遗忘、一次能触及 15 个文件。** 维护成本接近零。

— Karpathy

---

## 场景

| 场景 | 怎么做 | 效果 |
|------|--------|------|
| **技术调研** | 读论文/报告 → `wiki compile` → 实体自动提取 | 1 篇 DeepSeek-V4 报告 → 15 页结构化 Wiki |
| **读系列文章** | 逐章编译 → 人物/概念/情节页面 + 关系图 | 类似 Tolkien Gateway 的个人 Wiki |
| **团队知识库** | Slack/会议/文档 → 自动编译 → 自动更新 | 没人维护的 Wiki 也能保持新鲜 |
| **个人积累** | 日记/笔记/播客 → 自动归档 → 置信度衰减 | 虚假信息自动降权，真知灼见自然浮现 |

### 真实案例：编译 DeepSeek-V4 技术报告

```bash
$ python3 scripts/wiki.py compile .wiki/source/deepseek-v4/output.md
Compiling output.md (262658 chars)...
Calling LLM...
  Created: deepseek-v4-series.md (model)
  Created: compressed-sparse-attention.md (concept)
  Created: muon-optimizer.md (technique)
  Created: manifold-constrained-hyper-connections.md (concept)
  ... 15 pages total ...
  Updated index.md (15 pages)

Compiled output.md: 15 pages created
  → Updated log.md and graph/entities.json
```

**结果：**
- 15 个结构化页面（3 concepts + 6 techniques + 4 models + 2 benchmarks）
- 84 条关系边（uses: 19, improves_upon: 6, relates_to: 59）
- 每个页面 2-3KB 详细内容（Overview/Key Details/Relationships/Source Context）

查询效果：
```bash
$ python3 scripts/wiki.py query "What is DeepSeek-V4's architecture?"
**Answer**: Hybrid attention combining CSA and HCA, with mHC connections and Muon optimizer.
**Sources**: [[deepseek-v4-series]], [[deepseek-v4-pro]]
**Related**: [[compressed-sparse-attention]], [[manifold-constrained-hyper-connections]]
```

---

## 快速开始

```bash
# 初始化
python3 scripts/wiki.py init

# 配置（编辑 API key）
cp scripts/wiki_config.yaml.example scripts/wiki_config.yaml

# 编译第一个源文档
python3 scripts/wiki.py compile source.md

# 查询
python3 scripts/wiki.py query "What is X?"

# 健康检查
python3 scripts/wiki.py lint --auto-heal

# 查看状态
python3 scripts/wiki.py status
```

---

## 架构

### 三层设计

```
┌──────────────────────────────────────────────┐
│  Raw Sources (.wiki/source/)                  │
│  不可变。LLM 读，从不修改。                     │
│  论文、文章、PDF、图片。                         │
├──────────────────────────────────────────────┤
│  Wiki (.wiki/pages/)                          │
│  LLM 全权维护。摘要、实体页、概念页、           │
│  对比、综合。交叉引用、一致性。                   │
│  人类只读，不写。                                │
├──────────────────────────────────────────────┤
│  Schema (.wiki/schema.md + wiki_config.yaml)  │
│  约定是什么、怎么摄入、如何查询、                │
│  质量标准。你与 LLM 共同演进。                    │
└──────────────────────────────────────────────┘
```

### 三大操作

```bash
# 摄入：源文档 → Wiki 页面
python3 scripts/wiki.py compile source.md

# 查询：搜索 Wiki → 合成答案 → （可选）回填
python3 scripts/wiki.py query "What is X?" --file-back

# 检查：健康扫描 → 自动修复
python3 scripts/wiki.py lint --auto-heal
```

### 两个核心文件

| 文件 | 用途 |
|------|------|
| `index.md` | 内容目录：按类型分组（Concepts / Techniques / Models / …），每个页面一行 wikilink。查询时先读索引再深入。 |
| `log.md` | 时间线：`## [2026-05-11 13:32 UTC] compile | output.md`，可 grep 解析。 |

### 页面结构

每个 Wiki 页面统一格式：
```markdown
---
id: muon-optimizer
type: technique
name: Muon Optimizer
confidence: 0.90
source: DeepSeek-V4 Technical Report
---

# Muon Optimizer

## Overview
[2-4 句概述]

## Key Details
[关键技术细节]

## Relationships
- uses [[deepseek-v4-series]] — Primary optimizer
- improves upon [[adamw]] — Better convergence

## Source Context
> [原文摘录]
```

---

## 项目结构

```
llm-wiki-skill/
├── SKILL.md                     # Claude Code skill 入口
├── README.md                    # 本文件
├── pyproject.toml               # Python 项目配置
│
├── scripts/                     # 所有自动化脚本（16 个）
│   ├── wiki.py                  # 统一 CLI
│   ├── compile_v2.py            # 主编译：源 → Wiki ★
│   ├── query.py                 # 查询：搜索 + 合成 + 回填 ★
│   ├── lint.py                  # 检查：健康扫描 + 自愈 ★
│   ├── search.py                # 混合搜索：BM25 + 向量 + 图
│   ├── graph.py                 # 知识图谱：实体 + 关系 + 遍历
│   ├── consolidate.py           # 内存整合：层级提升 + 衰减
│   ├── crystallize.py           # 结晶化：Session → Digest
│   ├── bulk.py                  # 批量操作：删除/导出/合并
│   ├── generate_embeddings.py   # 向量嵌入生成
│   ├── url2markdown.py          # URL → Markdown 转换
│   ├── ocr.py                   # OCR 接口
│   ├── _ollama.py               # 嵌入生成（Ollama）
│   ├── _qdrant.py               # Qdrant 向量库（可选）
│   ├── _agensgraph.py           # AgensGraph 图库（可选）
│   └── wiki_config.yaml         # 统一配置文件
│
├── .wiki/                       # Wiki 数据（LLM 生成）
│   ├── pages/
│   │   ├── concepts/            # 概念页
│   │   ├── entities/            # 实体页
│   │   └── index.md             # Wiki 目录
│   ├── graph/
│   │   ├── entities.json        # 实体注册表
│   │   ├── edges.json           # 关系边
│   │   └── embeddings.json      # 向量嵌入
│   ├── source/                  # 原始源文档
│   ├── memory/                  # 内存层级
│   ├── audit.json               # 审计日志
│   ├── log.md                   # 操作日志
│   └── schema.md                # Wiki 模式
│
├── .claude/hooks/               # 自动化钩子（可启用）
│   ├── session-start.sh         # 会话开始时注入上下文
│   ├── session-end.sh           # 会话结束时结晶化
│   └── scheduled/               # 定时任务
│       ├── lint-daily.sh
│       ├── consolidate-daily.sh
│       └── maintenance-weekly.sh
│
├── references/                  # 深度参考文档
├── templates/                   # 页面模板
└── .planning/                   # GSD 开发规划
```

### 脚本依赖关系

```
query.py → search.py → graph.py
consolidate.py → crystallize.py
wiki.py → compile_v2.py, query.py, lint.py, bulk.py, generate_embeddings.py
```

---

## v2 增强功能

### 知识生命周期

| 机制 | 实现 | 说明 |
|------|------|------|
| **置信度评分** | `entities.json` 中 `confidence` 字段 | 初始 0.85，多源强化 +0.05，max 1.0 |
| **取代** | 矛盾检测 → 标记 → 旧版保留但标 stale | `detect_contradictions()` |
| **遗忘** | Ebbinghaus 曲线按类型衰减 | arch 260d, bug 20d, meeting 10d |
| **整合层级** | working → episodic → semantic → procedural | `consolidate.py` |

### 知识图谱

- 实体提取：每次编译自动提取结构化实体
- **类型化关系**：12 种关系类型（uses / depends_on / extends / improves_upon / contradicts / supersedes / caused_by / fixed_by / replaces / relates_to / part_of / implemented_by）
- 图遍历：从实体出发沿关系发现下游影响

### 混合搜索

| 流 | 实现 | 捕获 |
|----|------|------|
| BM25 | 关键词 + 词干 | 精确匹配 |
| 向量 | `qwen3-embedding:8b` (4096 维) | 语义相似 |
| 图 | 实体感知的关系遍历 | 结构连接 |

融合策略：Reciprocal Rank Fusion。

### 质量 & 自愈

```bash
$ python3 scripts/wiki.py lint
# Wiki Health Report
# Issues found: 45
# Orphans: 14 | Stale: 0 | Broken links: 31

$ python3 scripts/wiki.py lint --auto-heal
# Auto-healed: orphans linked, broken links repaired
```

### 隐私 & 审计

- **摄入过滤**：自动脱敏 API keys、tokens、密码、邮箱
- **审计日志**：每操作记录 timestamp + what + why → `audit.json`
- **批量操作**：delete/export/merge/clean，全部可审计可逆

### 输出格式

```bash
python3 scripts/wiki.py query "compare models" --format table     # 对比表
python3 scripts/wiki.py query "history" --format timeline         # 时间线
python3 scripts/wiki.py query "all" --format slides               # Marp 幻灯片
python3 scripts/wiki.py query "entities" --format json            # JSON 导出
python3 scripts/wiki.py query "structure" --format graph          # 依赖图
```

### 可选后端

| 后端 | 用途 | 启用方式 |
|------|------|----------|
| Qdrant (`localhost:6333`) | 生产级向量搜索 | 在 `wiki_config.yaml` 中取消注释 |
| AgensGraph (`localhost:5433`) | 生产级图数据库 | 在 `wiki_config.yaml` 中取消注释 |

---

## 配置

所有配置集中在 `scripts/wiki_config.yaml`：

```yaml
llm:                          # LLM API（编译 + 查询）
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"

embeddings:                   # 向量嵌入（语义搜索）
  provider: ollama
  model: "qwen3-embedding:8b"

hooks:                        # 自动化行为
  on_new_source: {enabled: true, auto_ingest: true}

retention:                    # 衰减曲线
  architecture: {half_life_days: 180}
  bug: {half_life_days: 20}

quality:                      # 质量标准
  auto_heal: true
  min_score: 0.4
```

---

## 设计来源

- **Karpathy's LLM Wiki** — 原始三层架构概念：源 → Wiki → Schema，index+log，entity/concept 页面
- **Rohit's LLM Wiki v2** — 生产强化：置信度评分、取代、遗忘曲线、知识图谱、混合搜索、自动化 hooks、结晶化

完整对照：`.wiki/IMPLEMENTATION_STATUS.md`（100% 实现 Karpathy v1 + Rohit v2）

---

## 许可

MIT
