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
cp wiki_config.yaml.example wiki_config.yaml

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
├── scripts/                     # 所有自动化脚本（17 个）
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
│   ├── _deepseek_ocr.py         # OCR 引擎（DeepSeek-OCR-4bit）
│   ├── _llm_extract.py          # LLM 实体提取
│   ├── _ollama.py               # 嵌入生成（Ollama）
│   ├── _qdrant.py               # Qdrant 向量库（可选）
│   ├── _agensgraph.py           # AgensGraph 图库（可选）
│   ├── wiki_config.yaml.example # 配置文件模板
│   └── wiki_config.yaml         # 本地配置（不提交）
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

## 知识生命周期

知识不是静态的。从摄入到遗忘，它的置信度、新鲜度、关系都在不断变化。

```
  Source ──→ Compile ──→ Pages + Graph ──→ Query ──→ File-back
                 │              │                │
                 ▼              ▼                ▼
              Log.md      entities.json     Answers → new pages
              Audit       edges.json
                 │              │
                 ▼              ▼
              Lint ────→ Stale ──→ Decay ──→ Archive
              Auto-heal    Contradictions    Forgotten
                 │
                 ▼
          Consolidate ──→ Working → Episodic → Semantic → Procedural
                 │
                 ▼
          Crystallize ──→ Session → Digest → Facts → Working Memory
```

### 阶段 1：摄入（Ingest）

源文档 → LLM 分析 → 结构化 Wiki 页面。

```bash
# 编译一个源文档
python3 scripts/wiki.py compile source.md

# 或直接使用脚本
python3 scripts/compile_v2.py source.md

# 强制重新编译（覆盖已有页面 + 检测矛盾）
python3 scripts/wiki.py compile source.md --force
python3 scripts/compile_v2.py source.md --force
```

**做了什么：**
- LLM 读取源文档（敏感信息已在发送前自动脱敏：API keys、tokens、密码、邮箱）
- 生成 10-15 个结构化 Wiki 页面（YAML frontmatter + Overview/Key Details/Relationships/Source Context）
- 按类型分类存储：`concepts/`、`entities/`
- 更新 `index.md`（按 Concepts / Techniques / Models / Frameworks / Benchmarks 分组）
- 追加 `log.md`（`## [YYYY-MM-DD HH:MM UTC] compile | source-name`）
- 构建知识图谱：实体 → `entities.json`，关系边 → `edges.json`（12 种类型）
- 写入审计日志：`audit.json`

### 阶段 2：图谱构建（Knowledge Graph）

编译时自动从页面 wikilinks 中提取类型化关系。

```bash
# 查看图谱
python3 scripts/graph.py show

# 遍历实体关系（下游影响分析）
python3 scripts/graph.py traverse deepseek-v4-series --depth 2

# 统计
python3 scripts/wiki.py bulk stats
```

**关系类型（12 种）：**
`uses` | `depends_on` | `extends` | `improves_upon` | `contradicts` | `supersedes` | `caused_by` | `fixed_by` | `replaces` | `relates_to` | `part_of` | `implemented_by`

### 阶段 3：查询 & 回填（Query + File-back）

搜索 Wiki → LLM 合成答案 → 可选回填为新页面。

```bash
# 默认 markdown 格式
python3 scripts/wiki.py query "What is DeepSeek-V4's architecture?"

# 多种输出格式
python3 scripts/wiki.py query "compare models" --format table
python3 scripts/wiki.py query "history of X" --format timeline
python3 scripts/wiki.py query "present findings" --format slides
python3 scripts/wiki.py query "export all" --format json

# 搜索 + 答案回填
python3 scripts/wiki.py query "Explain Muon optimizer" --file-back
python3 scripts/query.py "What is CSA?" --file-back
```

### 阶段 4：健康检查 & 自愈（Lint + Auto-heal）

周期性扫描 Wiki，发现问题并自动修复。

```bash
# 仅检查
python3 scripts/wiki.py lint

# 检查 + 自动修复
python3 scripts/wiki.py lint --auto-heal
python3 scripts/lint.py --auto-heal

# 生成报告文件
python3 scripts/lint.py --auto-heal --report-file .wiki/reports/lint-$(date +%Y-%m-%d).md
```

**检测项：**
- 🔴 矛盾页面（新旧信息冲突）
- 🟡 过期 claims（超过保留阈值）
- 🟡 孤页面（无入边/出边）
- 🟡 断裂链接（指向不存在的页面）
- 🟢 缺失概念（重要概念无页面）

### 阶段 5：矛盾检测 & 取代（Contradiction + Supersession）

重新编译同一源时，自动检测新旧信息矛盾。

```bash
# 重新编译 → 自动检测矛盾
python3 scripts/compile_v2.py source.md
# 输出示例：
#   Updated: compressed-sparse-attention.md (4 contradictions)
#   Updated: manifold-constrained-hyper-connections.md (10 contradictions)
```

矛盾类型：`factual` | `temporal` | `numerical` | `opinion`
严重程度：`high` | `medium` | `low`
LLM 自动推荐哪个声明更可靠。

### 阶段 6：衰减 & 遗忘（Confidence Decay + Forgetting）

知识不是永久的。使用 Ebbinghaus 遗忘曲线按实体类型衰减：

| 实体类型 | 半衰期 | 说明 |
|----------|--------|------|
| architecture | 260 天 | 架构决策衰减慢 |
| project | 130 天 | 项目事实 |
| pattern | 87 天 | 模式 |
| bug | 20 天 | Bug 衰减快 |
| meeting | 10 天 | 会议内容 |
| preference | 527 天 | 偏好长期有效 |

```bash
# confidence 衰减规则（compile_v2.py + lint.py 自动执行）：
#   retention < 0.5  → 标记为 stale
#   retention < 0.15 → 标记为 archived
#   每次 reinforcement → confidence +0.05, 重置衰减曲线
```

### 阶段 7：内存整合（Consolidation Tiers）

观察 → 片段 → 事实 → 模式。四级管道自动提升。

```bash
# 执行整合
python3 scripts/consolidate.py

# 检查当前内存状态
ls -la .wiki/memory/
# working.json    — 最近观察，未处理
# episodic.json   — 会话摘要
# semantic.json   — 跨会话事实
```

| 层级 | 文件 | 说明 |
|------|------|------|
| Working | `working.json` | 最近观察，未处理 |
| Episodic | `episodic.json` | 会话摘要，从观察压缩 |
| Semantic | `semantic.json` | 跨会话事实，从片段整合 |
| Procedural | 代码模式 | 工作流和模式，从重复语义提取 |

### 阶段 8：结晶化（Crystallization）

完整工作链 → 结构化摘要 → Wiki 页面。

```bash
# 从会话文件结晶化
python3 scripts/crystallize.py session.md --topic "DeepSeek-V4 Research"

# 自动结晶化（通过 session-end hook）
# .claude/hooks/session-end.sh → 自动触发
```

提取内容：问题是什么？发现了什么？涉及哪些文件/实体？教训是什么？

### 阶段 9：清理 & 批量操作（Bulk Operations）

Wiki 增长后需要治理。所有操作可审计、可逆。

```bash
# 预览清理
python3 scripts/wiki.py bulk clean --dry-run

# 执行清理
python3 scripts/wiki.py bulk clean

# 合并重复实体
python3 scripts/wiki.py bulk merge --dry-run

# 删除过期页面
python3 scripts/wiki.py bulk delete --stale --dry-run

# 删除低置信度页面
python3 scripts/wiki.py bulk delete --confidence 0.3 --dry-run

# 导出子集
python3 scripts/wiki.py bulk export --type concept

# 详细统计
python3 scripts/wiki.py bulk stats
```

### 阶段 10：向量嵌入（Embeddings）

为混合搜索生成语义嵌入。

```bash
# 生成所有页面嵌入
python3 scripts/wiki.py embed

# 验证覆盖
python3 scripts/generate_embeddings.py --verify
# → total_pages: 15, total_embeddings: 15, coverage_pct: 100.0

# 强制重新生成
python3 scripts/wiki.py embed --force
```

模型：`qwen3-embedding:8b` | 维度：4096 | 距离：Cosine

### 审计追踪（贯穿所有阶段）

每次操作自动记录到 `audit.json`：

```bash
# 查看审计日志
python3 -c "import json; print(json.dumps(json.load(open('.wiki/audit.json'))[-2:], indent=2, ensure_ascii=False))"
# → 最后 2 条操作记录（timestamp, operation, pages_created, contradictions）
```

### 自动化 Hooks（可选启用）

```bash
# .claude/hooks/session-start.sh  — 会话开始时注入 Wiki 上下文
# .claude/hooks/session-end.sh    — 会话结束时自动结晶化
# .claude/hooks/scheduled/        — 定时任务（lint + consolidate + maintenance）
```

---

---

## 配置

所有配置集中在 `scripts/wiki_config.yaml.example`（复制为 `wiki_config.yaml` 后编辑）：

```yaml
ocr:                          # OCR 服务（本地 DeepSeek-OCR）
  api_url: "http://127.0.0.1:12345/v1/chat/completions"
  api_key: "your-ocr-api-key"
  model: "DeepSeek-OCR-4bit"

llm:                          # LLM API（编译 + 查询）
  provider: deepseek
  api_key: "your-llm-api-key"
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  temperature: 0.3

hooks:                        # 自动化行为
  on_new_source: {enabled: true, auto_ingest: true}

retention:                    # 衰减曲线
  architecture: {half_life_days: 180}
  bug: {half_life_days: 20}

quality:                      # 质量标准
  auto_heal: true
  min_score: 0.4
```

> `wiki_config.yaml` 在 `.gitignore` 中，不会提交到 git。

---

## 设计来源

- **Karpathy's LLM Wiki** — 原始三层架构概念：源 → Wiki → Schema，index+log，entity/concept 页面
- **Rohit's LLM Wiki v2** — 生产强化：置信度评分、取代、遗忘曲线、知识图谱、混合搜索、自动化 hooks、结晶化

完整对照：`.wiki/IMPLEMENTATION_STATUS.md`（100% 实现 Karpathy v1 + Rohit v2）

---

## 许可

MIT
