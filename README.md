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
$ wiki compile .wiki/source/deepseek-v4/output.md
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
$ wiki query "What is DeepSeek-V4's architecture?"
**Answer**: Hybrid attention combining CSA and HCA, with mHC connections and Muon optimizer.
**Sources**: [[deepseek-v4-series]], [[deepseek-v4-pro]]
**Related**: [[compressed-sparse-attention]], [[manifold-constrained-hyper-connections]]
```

---

## 快速开始

```bash
# 安装
pip install -e .

# 安装后 shell 中会出现两个等价命令：
#   wiki
#   llm-wiki

# 创建配置文件（或复制 example）
wiki config --init
# 或
cp wiki_config.yaml.example wiki_config.yaml

# 编辑配置，设置 API key
vim wiki_config.yaml

# 初始化 Wiki
wiki init

# 编译文档
wiki compile source.md

# 查询
wiki query "What is X?"

# 健康检查
wiki lint --auto-heal

# 查看状态
wiki status

# 查看配置
wiki config
```

### Windows 设置

项目完全支持 Windows、macOS 和 Linux。部分注意事项：

1. **CLI 命令**：安装后直接使用 `wiki ...`。在 Windows 上确保 Python 和 Scripts 目录在 PATH 中；如果没有 `python` 命令，可用 `py -m pip install -e .` 安装。
2. **符号链接**：`download_models.py --setup-links` 创建模型符号链接在 Windows 上需要启用[开发者模式](https://learn.microsoft.com/windows/apps/get-started/enable-your-device-for-development)（设置 → 隐私和安全性 → 开发者模式），或使用管理员终端运行。
3. **OCR/lightpanda**：`url2markdown.py` 使用的 `lightpanda` 工具暂无 Windows 原生支持。可在 WSL 中使用，或使用其他 URL 转 Markdown 工具。
4. **计划任务**：`.claude/hooks/scheduled/` 目录下的定时任务脚本使用 Python 编写，跨平台通用。在 Windows 上可通过任务计划程序设置定时执行。

### 离线部署

适合无网络或内网环境：在有网络的机器上提前下载所有依赖包，拷贝到目标机后直接安装，无需再次下载。

**下载依赖（在有网络的机器上）：**

```bash
# 下载当前平台的所有依赖（自动检测 macOS/Windows/Linux + arm64/x86_64）
python scripts/offline_download.py

# 下载所有平台（macOS arm64/x86_64 + Windows x86_64 + Linux x86_64）
python scripts/offline_download.py --all

# 下载指定平台的所有架构
python scripts/offline_download.py --platform macos
python scripts/offline_download.py --platform windows
python scripts/offline_download.py --platform linux

# 允许 C 扩展包回退到源码包（目标机器需有 C 编译器）
python scripts/offline_download.py --include-source
```

**下载流程说明：**

脚本自动按平台 tag 下载 `.whl` 预编译包，确保目标机器无需编译器即可安装。对于纯 Python 包（如 `jieba`）没有 `.whl` 的，脚本自动识别并下载 `.tar.gz` 源码包——纯 Python 源码无需编译，跨平台通用。

`--include-source` 允许 **所有** 包回退到源码分发（包括 `numpy`、`faiss-cpu` 等 C 扩展包），意味着目标机器需要 C/C++ 编译器和 Python 开发头文件。仅建议在了解编译环境的情况下使用。

下载后的目录结构：
```
offline/
└── wheels/
    ├── macos-arm64/        # Apple Silicon — 68 .whl + jieba .tar.gz (~237 MB)
    ├── macos-x86_64/       # Intel Mac — 部分包无 wheel（见下方已知限制）
    ├── windows-x86_64/     # Windows x64 — 68 .whl + jieba .tar.gz (~295 MB)
    └── linux-x86_64/       # Linux x64 — 部分包无 wheel（见下方已知限制）
        ├── pyyaml-6.0.2-cp312-cp312-*.whl
        ├── requests-2.32.3-py3-none-any.whl
        ├── jieba-0.42.1.tar.gz        # 纯 Python，自动识别
        ├── requirements.txt
        └── ...
```

**离线安装（在目标机器上）：**

```bash
# 1. 将整个 offline/ 目录拷贝到目标机器
# 2. 进入项目目录，执行：
pip install --no-index --find-links offline/wheels/macos-arm64/ .

# Windows 示例：
pip install --no-index --find-links offline\wheels\windows-x86_64\ .

# Linux 示例：
pip install --no-index --find-links offline/wheels/linux-x86_64/ .
```

**平台兼容性：**

| 平台 | 完整下载 | 说明 |
|------|---------|------|
| macOS arm64 (Apple Silicon) | ✅ 69 包 | 全部 wheel 可用 |
| Windows x86_64 | ✅ 69 包 | 全部 wheel 可用 |
| macOS x86_64 (Intel) | ⚠️ 部分 | `faiss-cpu` 无此平台 wheel，需 `--include-source` 或使用 arm64 机器 |
| Linux x86_64 | ⚠️ 部分 | `faiss-cpu` 无此平台 wheel，需 `--include-source` 或换用 `faiss-gpu` |

> **注意**：wheel 是平台相关的。在 Mac 上下载的 `.whl` 只能用于 Mac，Windows 亦然。下载时请匹配目标机器的架构（arm64 vs x86_64）。纯 Python 的 `.tar.gz` 源码包（如 jieba）跨平台通用。

### CLI 命令

| 命令 | 说明 |
|------|------|
| `wiki init` | 初始化 Wiki 结构 |
| `wiki config` | 显示当前配置 |
| `wiki config --init` | 创建默认配置文件 |
| `wiki compile <file-or-dir>` | 编译源文件或目录 → Wiki 页面 |
| `wiki query <question>` | 查询 Wiki → 生成答案 |
| `wiki lint --auto-heal` | 健康检查 + 自动修复 |
| `wiki status` | Wiki 统计信息 |
| `wiki embed` | 生成向量嵌入 |
| `wiki bulk stats` | 详细统计 |
| `wiki bulk clean` | 清理孤立页面 |
| `wiki ledger list` | 列出所有台账表 |
| `wiki ledger create` | 创建台账表 |
| `wiki ledger ask` | 自然语言查询表数据 |
| `wiki ledger sql` | 执行原始 SQL（只读） |

目录编译默认递归所有子目录，跳过 `.wiki` 和 `.git`：

```bash
wiki compile docs/
wiki compile docs/ --depth 0    # 只处理 docs/ 下的直接文件
wiki compile docs/ --depth 1    # 处理直接文件和一层子目录
wiki compile diagram.png        # 图片会先转成带 source 路径的 markdown
```

### 台账管理

台账系统管理结构化表格数据，与 Wiki 页面互补：
- **Wiki 页面** — 处理文档、概念、知识图谱
- **台账表格** — 处理结构化、关系型、类型严格的数据

表格数据自动参与 `wiki query` 的混合检索（BM25 + Vector + Graph + Ledger），搜索结果合并返回。

**导入 CSV/Excel：**

```bash
# 导入表格文件
wiki ledger import data.csv --name "AI 模型对比"
wiki ledger import report.xlsx --name "季度报表"

# 自动类型推断（int/float/date/boolean/percentage 等）
# 自动字段名规范化为英文 slug
```

**查看与搜索：**

```bash
wiki ledger list                              # 列出所有台账
wiki ledger show <table-id>                    # 查看 schema + 前20行
wiki ledger search "预算"                      # 搜索表名/字段/数据
wiki ledger export <table-id> -o output.csv    # 导出 CSV
wiki ledger delete <table-id>                  # 删除台账
```

**创建表格（多轮对话确认字段）：**

```bash
# 创建项目台账
wiki ledger create "项目台账" \
  --fields '[{"name":"项目名称","type":"string","required":true},{"name":"预算","type":"number"},{"name":"状态","type":"string"}]' \
  --unique "项目名称" \
  --auto-increment \
  --description "项目管理台账"
```

**自然语言查询：**

```bash
# 自然语言 → 自动生成 SQL → 执行 → 返回结果
wiki ledger ask "项目台账" "进行中的项目有哪些？预算超过 40 万的按从高到低排"

# 分页查询
wiki ledger ask "项目台账" "按预算从高到低排序" --page 1 --page-size 20

# 原始 SQL（高级查询）
wiki ledger sql "SELECT \"项目名称\", SUM(\"预算\") FROM \"table_x\" GROUP BY \"项目名称\""

# 批量遍历大数据表
wiki ledger traverse "项目台账" --batch-size 100 --offset 0
```

**插入数据：**

```bash
# 单行
wiki ledger insert "项目台账" --data '{"项目名称":"智能系统","预算":50,"状态":"进行中"}'

# 批量
wiki ledger insert "项目台账" --data '[{...},{...}]'

# 容错模式
wiki ledger insert "项目台账" --data '[...]' --batch
```

**修改表结构：**

```bash
wiki ledger update-schema "项目台账" --add '[{"name":"备注","type":"text"}]'
wiki ledger update-schema "项目台账" --remove "旧字段"
wiki ledger update-schema "项目台账" --rename "旧名:新名"
```

**存储架构：**

```
.wiki/ledger/
├── ledger.duckdb           # DuckDB 数据库（单一文件）
│   ├── _registry           # 元数据表（显示名→实际名映射）
│   ├── _embeddings         # 向量嵌入表（支持语义检索）
│   └── <table_name>        # 用户表（强类型 SQL 列）
└── registry.json / index.json # 旧 JSON 格式（自动迁移后保留）
```

**SQL 生成流程：**

```
用户自然语言
  ↓
Claude 分析意图 → 预测需要的 SQL 函数类别
  ↓
加载 references/sql-functions.md 相关章节
  ↓
构建 Prompt: [Schema + 函数参考 + 问题]
  ↓
LLM 生成 SQL → DuckDB 执行 → 返回结果
```

| 支持类型 | DuckDB 映射 |
|---------|-----------|
| string / text | VARCHAR |
| integer | INTEGER |
| number | DOUBLE |
| boolean | BOOLEAN |
| date | DATE |
| datetime | TIMESTAMP |

### 模型配置

统一使用 `model` 段：

```yaml
model:
  provider: deepseek
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com

# Ollama:
# provider: ollama
# model: llama3.2
# base_url: http://localhost:11434
```

详细配置见 [CONFIGURATION.md](CONFIGURATION.md)。

### OCR 后端

**五**种模式随需切换，**MinerU 为默认**（效果最好，纯 CPU 可用）：

**本地模式（4 个引擎）：**

| 后端 | 引擎 | 核心优势 | 设备需求 | 模型大小 |
|------|------|---------|---------|---------|
| `mineru` ★ | MinerU 3.1 | 公式→LaTeX，表格→HTML，多栏排版 | CPU | ~2GB |
| `deepseek` | DeepSeek-OCR-2 | Vision-Language OCR，文档理解 | GPU/MPS/CPU | ~6.3GB |
| `logics` | Logics-Parsing-v2 | Qwen3VL，多模态文档解析 | GPU/MPS/CPU | ~8.4GB |
| `paddle` | PaddleOCR 3.5 | 109 语言，文档纠偏/展平 | CPU | ~100MB |

**API 模式（无需本地模型）：**

| 后端 | 说明 | 需求 |
|------|------|------|
| `api` | OpenAI 兼容视觉 API | api_url + api_key |

**配置选择：**

```yaml
# 统一 OCR 配置
ocr:
  mode: local                    # local | api
  backend: mineru                # 本地模式: mineru | deepseek | logics | paddle
  options:
    models_path: models/mineru/models
    lang: ch

  # API 模式：provider 预设自动配置 URL 和模型
  # mode: api
  # api_provider: siliconflow    # siliconflow | paddleocr-vl | deepseek | openai
  # api_key: ${SILICONFLOW_API_KEY}

  # 或手动指定 API 参数（会覆盖 provider 预设）
  # api_url: "https://api.siliconflow.cn/v1/chat/completions"
  # api_model: "deepseek-ai/DeepSeek-OCR"
  # api_prompt: "<image>\n<|grounding|>OCR this image."
```

**API 提供商标识：**

| Provider | Base URL | 默认模型 |
|----------|----------|---------|
| `siliconflow` | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-OCR` |
| `paddleocr-vl` | `https://api.siliconflow.cn/v1` | `PaddlePaddle/PaddleOCR-VL-1.5` |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-ocr-2` |
| `openai` | `https://api.openai.com/v1` | `gpt-4o` |

**使用方式：**

```bash
# MinerU（默认，本地 CPU）
python scripts/ocr.py paper.pdf

# 本地引擎切换
python scripts/ocr.py paper.pdf --backend deepseek
python scripts/ocr.py paper.pdf --backend logics
python scripts/ocr.py paper.pdf --backend paddle

# API 模式（远程视觉 API，无需本地模型）
python scripts/ocr.py paper.pdf --backend api

# PDF → Wiki 完整流程
python scripts/ocr.py paper.pdf -o .wiki/source/paper/
wiki compile .wiki/source/paper/paper.md
```

**模型目录结构：**

```
models/
├── mineru/models           # MinerU PDF-Extract-Kit
├── deepseek-ocr-v2/model   # DeepSeek-OCR-2
├── logics-parsing-v2/model # Logics-Parsing Qwen3VL
└── paddleocr/              # PaddleOCR (auto-downloaded)
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

### 同名异实保护

不同来源可能有同名实体（如两份方案都有「专家评审组」），直接覆盖会丢失信息。编译时自动检测跨文档冲突：

```
源 A（大赛方案）→ 专家评审组.md（成员: 张总、李总）
源 B（课程方案）→ coursepl-专家评审组.md  ← 自动加前缀，不覆盖！
                 → concepts/专家评审组.md   ← 自动创建概念聚合页
```

概念聚合页综合所有实例，列出通用模式和已知来源：

```markdown
# 专家评审组
## 概述
各类方案中常见的核心评审机构，负责作品筛选和打分...
## 已知实例
- [[专家评审组]] — AI 创新大赛，信息技术委员会主导，4维度评分
- [[coursepl-专家评审组]] — 课程方案 B，教学处主导，5分制
## 关键特征
- 成员构成：通常混合内外部专家，人数 3-5 人...
```

**查询行为**：
- 「专家评审组怎么构成？」→ 读概念页，跨文档综合回答
- 「AI 大赛的专家有谁？」→ 精确命中 `专家评审组.md`
- 「张总在哪个组？」→ 遍历所有 `*专家评审组*` 实例，找到包含「张总」的那个

### 三大操作

```bash
# 摄入：源文档 → Wiki 页面
wiki compile source.md

# 查询：搜索 Wiki → 合成答案 → （可选）回填
wiki query "What is X?" --file-back

# 快速搜索：跳过 LLM 合成，0.5s 出结果
wiki query "专家评审组" --no-synthesis

# 检查：健康扫描 → 自动修复
wiki lint --auto-heal
```

### 查询模式

| 模式 | 命令 | 耗时 | 输出 |
|------|------|------|------|
| 快速搜索 | `--no-synthesis` | 0.5s | 排名列表 + 相关片段（BM25 + Graph + RRF 融合） |
| LLM 合成 | 默认 | 2.7s | 结构化答案 + 引用 + 关联推荐 |
| 全局关闭 | `query.llm_synthesis: false` | 永久快速 | 配置文件中设置 |

中文检索通过 jieba 分词支持，英文检索使用 BM25 + Porter 词干提取，双引擎自动切换。搜索索引缓存至磁盘（`.wiki/graph/.bm25_index.json`），页面变化时自动重建。

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
├── CONFIGURATION.md             # 配置指南
├── pyproject.toml               # Python 项目配置（含 wiki CLI 入口）
├── wiki_config.yaml.example     # 配置文件模板
├── wiki_config.yaml             # 本地配置（不提交）
│
├── offline/                     # 离线部署 wheel 包（不提交）
│   └── wheels/
│       ├── macos-arm64/        # Apple Silicon wheels
│       ├── macos-x86_64/       # Intel Mac wheels
│       ├── windows-x86_64/     # Windows wheels
│       └── linux-x86_64/       # Linux wheels
│
├── models/                      # OCR 模型目录
│   ├── mineru/models           # MinerU PDF-Extract-Kit
│   ├── deepseek-ocr-v2/model   # DeepSeek-OCR-2 (~6.3GB)
│   ├── logics-parsing-v2/model # Logics-Parsing Qwen3VL (~8.4GB)
│   └── README.md               # 模型目录说明
│
├── scripts/                     # 所有自动化脚本（28 个）
│   ├── wiki.py                  # 统一 CLI ★
│   ├── config.py                # 统一配置加载 ★
│   ├── compile_v2.py            # 主编译：源 → Wiki ★
│   ├── query.py                 # 查询：搜索 + 合成 + 回填 ★
│   ├── lint.py                  # 检查：健康扫描 + 自愈 ★
│   ├── search.py                # 混合搜索：BM25 + 向量 + 图
│   ├── graph.py                 # 知识图谱：实体 + 关系 + 遍历
│   ├── consolidate.py           # 内存整合：层级提升 + 衰减
│   ├── crystallize.py           # 结晶化：Session → Digest
│   ├── bulk.py                  # 批量操作：删除/导出/合并
│   ├── generate_embeddings.py   # 向量嵌入生成（支持 API）
│   ├── download_models.py       # 模型下载/链接工具
│   ├── ledger.py                 # 台账管理（DuckDB 后端）★
│   ├── table_query.py             # 自然语言 → SQL 查询引擎 ★
│   ├── offline_download.py        # 离线部署 wheel 下载
│   ├── ocr.py                   # OCR 接口（5 模式: 4 本地 + API）
│   ├── _ocr_api.py              # 通用 API OCR（OpenAI 兼容视觉 API）
│   ├── _hook_utils.py           # 跨平台钩子工具
│   ├── _mineru_ocr.py           # MinerU 引擎（CPU）★
│   ├── _paddle_ocr.py           # PaddleOCR 引擎（CPU）
│   ├── _deepseek_ocr2.py        # DeepSeek-OCR-2 引擎（GPU/MPS）
│   ├── _logics_parsing.py      # Logics-Parsing 引擎（GPU/MPS）
│   ├── _ollama.py               # Ollama 嵌入生成
│   └── ...
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
│   ├── session_start.py          # 会话开始时注入上下文
│   ├── session_end.py            # 会话结束时结晶化
│   ├── on_new_source.py          # 写入文件时自动编译
│   └── scheduled/               # 定时任务（Python，跨平台）
│       ├── lint_daily.py
│       ├── consolidate_daily.py
│       └── maintenance_weekly.py
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

## 模型设置

### 检查模型状态

```bash
python scripts/download_models.py --info
```

输出示例：
```
✓ mineru
  Path: models/mineru/models
  Backend: CPU
  ✓ Layout
  ✓ OCR
  ✓ MFR

✓ deepseek-ocr-v2
  Path: models/deepseek-ocr-v2/model
  Backend: GPU/MPS/CPU
  ✓ config.json
  ✓ model-00001-of-000001.safetensors

✓ logics-parsing-v2
  Path: models/logics-parsing-v2/model
  Backend: GPU/MPS/CPU
  ✓ config.json
  ✓ model-00001-of-00002.safetensors
```

### 链接现有模型

如果已有模型文件，创建符号链接：

```bash
python scripts/download_models.py --setup-links
```

自动链接位置：
- MinerU: `~/.cache/modelscope/.../PDF-Extract-Kit-1.0/models`
- DeepSeek-OCR-2: `~/project/DeepSeek-OCR-2/models/DeepSeek-OCR-2`
- Logics-Parsing: `~/project/Logics-Parsing/weights/Logics-Parsing-v2`

### 环境变量

```bash
# Wiki 目录
export LLM_WIKI_DIR=/path/to/wiki

# LLM 配置
export DEEPSEEK_API_KEY=sk-xxx
export OPENAI_API_KEY=sk-xxx

# Embedding
export EMBEDDING_MODE=local
export OLLAMA_BASE_URL=http://localhost:11434

# OCR 模型路径
export MINERU_MODELS_PATH=models/mineru/models
export DEEPSEEK_OCR_MODEL_PATH=models/deepseek-ocr-v2/model
export LOGICS_PARSING_MODEL_PATH=models/logics-parsing-v2/model
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
wiki compile source.md

# 或直接使用脚本
python scripts/compile_v2.py source.md

# 强制重新编译（覆盖已有页面 + 检测矛盾）
wiki compile source.md --force
python scripts/compile_v2.py source.md --force
```

**做了什么：**
- LLM 读取源文档（敏感信息已在发送前自动脱敏：API keys、tokens、密码、邮箱）
- 生成 10-15 个结构化 Wiki 页面（YAML frontmatter + Overview/Key Details/Relationships/Source Context）
- 按类型分类存储：抽象概念→ `concepts/`，具体实体→ `entities/`
- **同名异实保护**：不同来源的同名实体自动加前缀（如 `coursepl-专家评审组`），不覆盖；自动生成概念聚合页列出所有实例
- 更新 `index.md`（按 Concepts / Techniques / Models / Frameworks / Benchmarks 分组）
- 追加 `log.md`（`## [YYYY-MM-DD HH:MM UTC] compile | source-name`）
- 构建知识图谱：实体 → `entities.json`，关系边 → `edges.json`（12 种类型）
- 写入审计日志：`audit.json`

### 阶段 2：图谱构建（Knowledge Graph）

编译时自动从页面 wikilinks 中提取类型化关系。

```bash
# 查看图谱
python scripts/graph.py show

# 遍历实体关系（下游影响分析）
python scripts/graph.py traverse deepseek-v4-series --depth 2

# 统计
wiki bulk stats
```

**关系类型（12 种）：**
`uses` | `depends_on` | `extends` | `improves_upon` | `contradicts` | `supersedes` | `caused_by` | `fixed_by` | `replaces` | `relates_to` | `part_of` | `implemented_by`

### 阶段 3：查询 & 回填（Query + File-back）

搜索 Wiki → LLM 合成答案 → 可选回填为新页面。

```bash
# 默认 markdown 格式
wiki query "What is DeepSeek-V4's architecture?"

# 多种输出格式
wiki query "compare models" --format table
wiki query "history of X" --format timeline
wiki query "present findings" --format slides
wiki query "export all" --format json

# 搜索 + 答案回填
wiki query "Explain Muon optimizer" --file-back
python scripts/query.py "What is CSA?" --file-back
```

### 阶段 4：健康检查 & 自愈（Lint + Auto-heal）

周期性扫描 Wiki，发现问题并自动修复。

```bash
# 仅检查
wiki lint

# 检查 + 自动修复
wiki lint --auto-heal
python scripts/lint.py --auto-heal

# 生成报告文件
python scripts/lint.py --auto-heal --report-file .wiki/reports/lint-report.md
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
python scripts/compile_v2.py source.md
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
python scripts/consolidate.py

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
python scripts/crystallize.py session.md --topic "DeepSeek-V4 Research"

# 自动结晶化（通过 session-end hook）
# .claude/hooks/session_end.py → 自动触发
```

提取内容：问题是什么？发现了什么？涉及哪些文件/实体？教训是什么？

### 阶段 9：清理 & 批量操作（Bulk Operations）

Wiki 增长后需要治理。所有操作可审计、可逆。

```bash
# 预览清理
wiki bulk clean --dry-run

# 执行清理
wiki bulk clean

# 合并重复实体
wiki bulk merge --dry-run

# 删除过期页面
wiki bulk delete --stale --dry-run

# 删除低置信度页面
wiki bulk delete --confidence 0.3 --dry-run

# 导出子集
wiki bulk export --type concept

# 详细统计
wiki bulk stats
```

### 阶段 10：向量嵌入（Embeddings）

为混合搜索生成语义嵌入。

```bash
# 生成所有页面嵌入
wiki embed

# 验证覆盖
python scripts/generate_embeddings.py --verify
# → total_pages: 15, total_embeddings: 15, coverage_pct: 100.0

# 强制重新生成
wiki embed --force
```

模型：`qwen3-embedding:8b` | 维度：4096 | 距离：Cosine

### 审计追踪（贯穿所有阶段）

每次操作自动记录到 `audit.json`：

```bash
# 查看审计日志
python -c "import json; print(json.dumps(json.load(open('.wiki/audit.json'))[-2:], indent=2, ensure_ascii=False))"
# → 最后 2 条操作记录（timestamp, operation, pages_created, contradictions）
```

### 自动化 Hooks（可选启用）

```bash
# .claude/hooks/session_start.py   — 会话开始时注入 Wiki 上下文
# .claude/hooks/session_end.py     — 会话结束时自动结晶化
# .claude/hooks/on_new_source.py   — 写入文件时自动编译
# .claude/hooks/scheduled/         — 定时任务（lint + consolidate + maintenance）
```

---

---

## 配置

所有配置集中在 `wiki_config.yaml`。使用 `wiki config --init` 创建默认配置文件。

### 快速配置

```yaml
# Wiki 目录（编译后的文件存放位置）
wiki_dir: .wiki

# LLM 模型配置
model:
  provider: deepseek              # deepseek | openai | ollama | custom
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}    # 使用环境变量

# OCR 后端选择
ocr:
  mode: local        # local | api
  backend: mineru    # 本地: mineru | deepseek | logics | paddle
  api_provider: ""   # API: siliconflow | paddleocr-vl | deepseek | openai

# 图片编译增强：启用后图片先用 VL/omni 模型解析，再按需追加 OCR 文本
image_analysis:
  enabled: false
  api_provider: ""   # siliconflow | openai | deepseek | paddleocr-vl
  api_url: ""        # OpenAI-compatible /v1/chat/completions endpoint
  api_key: ""
  api_model: ""
  ocr_fallback: true

# Embedding 模式
embeddings:
  mode: local  # local | api
  model: "sentence-transformers/all-MiniLM-L6-v2"
```

### 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `wiki_dir` | Wiki 数据存储目录 | `.wiki` |
| `model.provider` | 模型提供商 | `deepseek` |
| `model.api_key` | API 密钥（支持环境变量） | - |
| `model.model` | 模型名称 | `deepseek-v4-flash` |
| `ocr.mode` | OCR 模式: local / api | `local` |
| `ocr.backend` | 本地 OCR 引擎 | `mineru` |
| `ocr.options` | 当前 OCR 后端的本地参数 | `{}` |
| `ocr.api_provider` | API provider 预设 | - |
| `image_analysis.enabled` | compile 图片时是否先用视觉模型理解图片 | `false` |
| `image_analysis.api_url` | 图片识别增强模型的 OpenAI-compatible API URL | - |
| `image_analysis.ocr_fallback` | 图片视觉解析后是否追加 OCR 文字识别 | `true` |
| `embeddings.mode` | Embedding 模式 | `local` |
| `query.llm_synthesis` | 是否使用 LLM 合成答案 | `true` |

### LLM 模型配置

支持四种模式，均写在 `model` 段：

```yaml
# 1. DeepSeek API（默认）
model:
  provider: deepseek
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}

# 2. OpenAI API
model:
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}

# 3. Ollama 本地模型（无需 API key）
model:
  provider: ollama
  model: llama3.2
  base_url: http://localhost:11434

# 4. 自定义 API 端点
model:
  provider: custom
  api_url: http://your-server:8000/v1/chat/completions
  api_key: your-custom-key
  model: your-model
```

### OCR 后端配置

```yaml
ocr:
  mode: local
  backend: mineru
  options:
    models_path: models/mineru/models
    lang: ch
    formula: true

# DeepSeek-OCR-2:
# backend: deepseek
# options:
#   model_path: models/deepseek-ocr-v2/model
#   device: auto
```

### Embedding 配置

支持本地和 API 两种模式：

```yaml
# 本地模式（默认）
embeddings:
  mode: local
  model: "sentence-transformers/all-MiniLM-L6-v2"
  dimension: 384

# 或使用 Ollama
embeddings:
  mode: local
  model: "ollama:nomic-embed-text"

# API 模式
embeddings:
  mode: api
  api_url: "https://api.openai.com/v1/embeddings"
  api_key: ${OPENAI_API_KEY}
  api_model: "text-embedding-3-small"
  dimension: 1536
```

### 更多配置

详见 [CONFIGURATION.md](CONFIGURATION.md)，包含：
- Wiki 目录配置
- URL/本地模型切换
- OCR 后端配置
- Embedding API 配置
- 知识保留策略
- 向量搜索配置

> `wiki_config.yaml` 在 `.gitignore` 中，不会提交到 git。

---

## 设计来源

基于 [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 和 [Rohit's LLM Wiki v2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)，100% 实现。

### 设计合规清单

| 设计原则 | 来源 | 实现 |
|---------|------|------|
| 三层架构（源→Wiki→Schema） | Karpathy | `source/` + `pages/` + `schema.md`/`wiki_config.yaml` |
| Ingest → 写页面 → index → log | Karpathy | `compile_v2.py` 完整流程 |
| 同名异实保护 | — | 自动前缀 + 概念聚合页 |
| Query → 搜索 → 合成 → 回填 | Karpathy | `query.py` + `--file-back` + 6 种输出格式 |
| 快速搜索（跳过 LLM） | — | `--no-synthesis` 0.5s 出结果 |
| Lint → 自动修复 | Karpathy | `lint.py --auto-heal` |
| index.md + log.md | Karpathy | 编译/查询自动更新 |
| 中文检索 | — | jieba 分词 + BM25 + RRF 混合搜索 |
| 12 种关系类型 | Rohit | 中英文关键词匹配，知识图谱 |
| 置信度评分 | Rohit | YAML frontmatter `confidence` 字段 |
| 矛盾检测 & 取代 | Rohit | `detect_contradictions()` 跨文档对比 |
| Ebbinghaus 遗忘曲线 | Rohit | 6 种实体半衰期（arch 260d, bug 20d...） |
| 内存整合层级 | Rohit | working → episodic → semantic → procedural |
| Graph 遍历 | Rohit | `graph.py` BFS traversal + impact analysis |
| Schema 驱动 | Rohit | `load_entity_types_from_schema()` 动态类型 |
| 隐私过滤 | Rohit | `strip_sensitive()` 5 种敏感信息模式 |
| 审计追踪 | Rohit | `audit.json` 每次操作记录 |
| 自动化 hooks | Rohit | session-start/end, on-new-source, scheduled |
| 结晶化 | Rohit | Session → Digest → Wiki 页面 |

---

## 更新日志

### v2.1.0 (2025-05-27)

**新增功能：**

- **统一 CLI 系统**
  - `wiki` 命令入口点（安装后直接使用）
  - `wiki config` 显示/创建配置
  - `wiki init` 初始化 Wiki 结构

- **统一配置系统**
  - `wiki_config.yaml` 集中管理所有配置
  - 支持 `wiki_dir` 自定义 Wiki 存储路径
  - 环境变量支持 `${VAR_NAME}` 语法

- **四个 OCR 后端**
  - MinerU（默认，CPU）
  - DeepSeek-OCR-2（GPU/MPS/CPU）
  - Logics-Parsing-v2（GPU/MPS/CPU）
  - PaddleOCR（CPU）
  - `ocr.backend` 配置项选择默认后端

- **模型管理**
  - `models/` 目录统一存放 OCR 模型
  - `download_models.py --info` 查看模型状态
  - `download_models.py --setup-links` 链接现有模型

- **Embedding API 支持**
  - `mode: local | api` 切换本地/API 模式
  - 支持 OpenAI/DeepSeek Embedding API
  - 支持 Ollama 本地嵌入

- **LLM 模型切换**
  - DeepSeek API（默认）
  - OpenAI API
  - Ollama 本地模型
  - 自定义 API 端点

**修复问题：**

- 修复 `_llm_extract.py` 缺少 `import os`
- 修复多个文件缺少 `__future__ annotations`
- 统一所有脚本使用 `config` 模块
- Python 3.9+ 兼容性修复

**文档更新：**

- 新增 `CONFIGURATION.md` 详细配置指南
- 更新 README 包含最新功能说明
- 更新模型目录结构说明

---

## 许可

MIT
