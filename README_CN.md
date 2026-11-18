<p align="center">
  <a href="README.md">English</a> &nbsp;|&nbsp;
  <a href="README_CN.md">简体中文</a>
</p>

# llm-wiki

llm-wiki 是一个用于搭建本地知识库的 Python 命令行工具和 Agent 技能。它把文档、图片、笔记和代码编译成可复用的 Markdown 知识页，为概念建立类型化关系，并单独索引来源证据。查询可以串联多份资料，并引用支撑答案的具体页码、幻灯片、章节或表格。

例如，你可以查询某天适用的报销政策，找到审批流程中向财务移交的步骤，核对多份报告里的数值，也可以把教材知识点和考查它们的试题关联起来。

## 快速开始

需要 Python 3.10 或更高版本。安装后，在想要存放知识库的项目目录中运行 `wiki`。

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
# 让当前 Agent 完成并校验生成的编译工作单，再查询。
wiki query "手册规定了哪些例外？" --no-synthesis
wiki query "手册规定了哪些例外？"
```

把 `./handbook.md` 换成你的文件。Agent 模式下，最后一条命令会返回证据包，由当前助手作答并校验。只在终端中运行编译和问答时，先配置模型服务，再分别传入 `--mode llm`。在源码目录也可以通过 `python scripts/wiki.py` 调用命令。

### 安装为 Agent 技能

在宿主的技能目录中克隆或链接整个仓库，使 `SKILL.md`、`scripts/`、`templates/` 和 `references/` 位于同一个技能目录下。Codex 的目录可用 `~/.codex/skills/llm-wiki`，也可使用自定义 Codex 主目录。Claude Code 使用 `~/.claude/skills/llm-wiki`。以 Codex 为例：

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/lgwanai/llm-wiki-skill.git ~/.codex/skills/llm-wiki
python -m pip install -e ~/.codex/skills/llm-wiki
```

在知识库项目中打开助手后，可在 Codex 中输入「用 `$llm-wiki` 把这份手册加入知识库，并回答试用期有哪些例外」。技能会引导助手完成编译任务并校验答案。仓库也提供可选的 Codex 和 Claude Code 会话钩子。 [技能说明](SKILL.md) · [自动化参考](references/automation.md)

### 模型和 OCR 要求

| 运行方式 | 所需资源 |
|---|---|
| **本地检索** | `wiki query --no-synthesis` 返回排序后的证据。默认检索使用本地索引，无需调用回答模型。 |
| **Agent 模式（默认）** | 复用当前 AI 助手的模型连接。CLI 负责生成编译工作单或查询证据包。处理图片或未解析的图表关系时，需要支持图像输入的助手，并为文字提取配置 OCR。 |
| **独立 LLM 模式** | 提前确认模型服务的 API 地址、模型 ID、访问权限、额度和所需 API Key。把密钥放在环境变量里，由 `wiki_config.yaml` 引用。Ollama 需要先启动服务并安装目标模型。 |
| **OCR** | 本地后端需要对应的运行环境和模型权重。独立 OCR 的 API 后端需要可用的视觉模型端点。OCR 使用单独的配置文件。 |

独立 LLM 模式配置模型后，运行 `wiki config --check` 检查本地配置。此命令不会请求模型服务。OCR 环境可用 `ocr list --check` 和 `ocr --doctor` 检查。 [配置指南](CONFIGURATION.md) · [使用指南](docs/USAGE.md)

配置模型服务后，可用下面的命令独立运行。PDF 中仍有未解析的页面证据时，编译可能返回工作单，交由 Agent 看图复核。

```bash
wiki config --check
wiki compile ./handbook.md --mode llm
wiki query "手册规定了哪些例外？" --mode llm
```

## 导入与编译

| 来源 | 可保留的结构和证据 |
|---|---|
| **Markdown、文本、HTML 文件、代码和对话记录** | 提取标题、事实、定义、代码片段和概念链接。支持单个文件、递归目录、内联文本和标准输入。 |
| **PDF** | 优先提取原生文字和版面信息。结构明确时可保留代码缩进，拼接跨页续表，区分并排表格，并绑定简单图表的标签和数值。存在缺口的页面会渲染后走本地 OCR 或进入 Agent 复核。 |
| **PowerPoint** | 对可编辑的 `.pptx`，提取可用的连接线端点、决策分支、表格单元格和图表数值。含截图的混合幻灯片可在同一页码下保留原生数据和 OCR 结果。 |
| **Word 和 EPUB** | Word 在渲染条件具备时保留页级证据，旧版 `.doc` 可能需要 LibreOffice 或 macOS `textutil` 转换。EPUB 按原书阅读顺序处理，保留章节、节标题和引用的配图。 |
| **截图、扫描件和图片** | OCR 提取文字、公式和表格。支持图像输入的 Agent 读取箭头方向、泳道交接、任务依赖、坐标轴和数据系列等关系。核对后的观察可单独归档为可搜索的证据，并关联原图。 |
| **电子表格和 CSV** | 可作为资料编译，也可用 `wiki ledger import` 导入台账，按行存储和查询。 |

编译可按政策合规、运营、工程、财务、学术研究和教育等领域采用不同的提取规则。制度文件可保留条款编号、许可或禁止、适用范围、例外和生效日期。研究材料可关联定义、公式、假设、结论和限制。教材与试卷可建立「知识点 ↔ 试题」的双向链接。概念之间可以使用 `depends_on`、`tests`、`contradicts`、`supersedes` 等类型化关系。

事实、表格行、键值对和脚注可提取为原子主张，同时保留对应条件和出处。查询也能直接检索按页、幻灯片或 EPUB 章节保存的来源文本。即使知识页没有收录某个字段，仍有机会从来源证据中查到。命中视觉记录时，可同时返回对应的原图和来源位置。

### 来源版本与发布

系统按文件路径识别来源。同名文件位于不同目录时可分别编译，移动或改名后视为新来源。内容未变时可跳过处理。用 `--force` 强制重编译，用 `--dry-run` 预览。

Agent 编译会生成工作单，在暂存区写草稿，并用来源定位和原文摘录记录每一项的覆盖情况。校验成功后，知识页和对应证据一同发布。独立 LLM 模式在暂存编译成功后发布。编译未完成或发布中断时，查询继续使用上一个已发布版本。旧版证据和知识页副本保存在 `.wiki/source/evidence/` 下。

```bash
wiki compile ./documents/ --depth 1
wiki compile ./documents/release-plan.pptx --force
wiki compile --text "审批有效期为 90 天。" --name approval-notes
```

[工作单、版本和发布命令](docs/CLI.md#source-versions-and-publication) · [视觉证据说明](references/visual-evidence.md) · [文档和图片示例](evals/media_workflows/README.md)

## 检索、问答与答案校验

默认检索融合 **原文证据、原子主张、页面元数据、BM25F、视觉记录、知识图谱和 DuckDB 台账**。系统按问题意图调整各路权重，通过倒数排名融合合并结果。长知识页完整保留，标题下的段落单独参与词法检索。中英文检索在本地分词，支持利用双语别名和 `.wiki/query_lexicon.yaml` 中的项目词表扩展查询。

- **跨资料回答。** 多跳检索将复合问题拆成子目标，沿相关概念链接找证据。证据齐全、没有可用链接或达到跳数上限时停止，默认三跳。
- **判断政策时效。** 查询当前规则会优先返回已生效版本，并可提示将生效的替代规则。历史查询按所问日期判断是否落入 `effective_from`（含）与 `effective_until`（不含）定义的区间。适用日期缺失时保留为未知。
- **核对具体字段和原图。** 可定位到来源页、图表、表格行或脚注。当结构化图表证据能唯一确定所需的数据系列和数值时，部分合计和占比可直接计算。
- **校验并写回。** Agent 模式生成的查询任务附带本地答案校验命令，独立 LLM 模式直接校验生成内容。检查包括引用、许可或禁止的方向、数值与单位、日期适用性。即使关闭常规答案校验，`--file-back` 也会拦截缺少证据或与证据冲突的陈述。
- **理解追问。** `--conversation-stdin` 可传入最多六轮问答的 JSON 历史。配置的模型先补全当前问题中的指代，再按完整问题检索。本轮答案以新检索到的证据为依据。
- **按用途输出。** 可只返回证据，也可生成带引用的答案。支持 Markdown、对比表、时间线、Marp 幻灯片、JSON 和关系图。

```bash
wiki query "2025 年 7 月 1 日适用哪版报销政策？"
wiki query "甘特图中哪个里程碑阻塞了上线？"
wiki query "比较两个地区政策中的审批阈值" --format table
wiki query "哪个步骤把审批移交给财务？" --no-synthesis --debug-search
wiki query "总结已批准的升级处理流程" --file-back
```

可选的语义检索使用嵌入式 Zvec 和向量模型。用 `python -m pip install -e '.[vector]'` 安装，启用 `embeddings`，并将 `vector` 加入 `query.search_streams`。可选的 FlagEmbedding 重排使用 `python -m pip install -e '.[rerank]'` 安装，通过 `reranker.enabled` 启用。这些组件未启用或不可用时，原生检索仍可运行。 [混合检索说明](references/hybrid-search.md) · [答案校验命令](docs/CLI.md#answer-evidence-verification)

## 表格与台账

编译提取的表格可通过 `wiki table list` 和 `wiki table show <table>` 查看。用 `wiki ledger` 在 DuckDB 中维护结构化记录，支持导入 CSV 或 Excel、定义字段、批量写入、调整表结构、跨表搜索和导出 CSV。通用 Wiki 查询也可以从台账返回证据。

```bash
wiki ledger import ./data/projects.xlsx
wiki ledger list
wiki ledger show projects
wiki ledger sql "SELECT * FROM projects WHERE budget > 500000"
wiki ledger ask projects "哪些项目的预算超过五十万元？"
```

请按实际数据替换表名和字段名。`wiki ledger sql` 执行只读查询。`wiki ledger ask` 和 `wiki table ask` 使用已配置的模型。也可通过 `wiki ledger context` 获取表结构和函数说明，让当前 Agent 生成 SQL。 [台账命令](docs/CLI.md#ledger) · [SQL 函数参考](references/sql-functions.md)

## 维护、存储与分享

| 任务 | 命令 | 行为 |
|---|---|---|
| 查看状态 | `wiki status`、`wiki search doctor` | 查看知识库统计，诊断检索索引。 |
| 检查和修复 | `wiki lint`、`wiki lint --auto-heal` | 检查孤立页面、断链、过时内容和矛盾，并按需应用可用修复。 |
| 处理具体问题 | `wiki doctor "华南地区的例外条件缺失"` | 记录问题并检索证据，根据类型重编译、重新 OCR、补充元数据或标记复核。 |
| 按查询历史优化 | `wiki dream --foreground` | 更新元数据、审计近期查询，并尝试合并重复页或补充内容。用检索质量检查评估改动，并借助 Git 快照回滚。 |
| 沉淀会话知识 | `wiki consolidate`、会话结晶流程 | 支持记忆整合和置信度衰减，可把会话中的决策、发现和经验保存为可检索的摘要。 |
| 分享知识 | `wiki export`、`wiki import`、`wiki okf` | 通过 Wiki ZIP 或 OKF bundle 交换已编译的知识页和附件。 |

置信度会随时间衰减，也可通过强化更新。已有页面和图谱中的 `high`、`medium`、`low` 旧标签仍可读取。矛盾标记和取代关系保留了复核冲突或旧知识所需的上下文。 [知识生命周期](references/lifecycle.md)

### 数据目录和可移植性

`.wiki/pages/` 是原生的 [Open Knowledge Format v0.1 草案](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle。概念用带 YAML frontmatter 的 Markdown 保存，Concept ID 来自页面相对于 bundle 根目录的路径。页面用标准 Markdown 链接表达关系。来源证据、图索引和台账数据库各有存储目录。用 `LLM_WIKI_DIR` 切换知识库，用 `LLM_WIKI_CONFIG` 指定配置文件。

```text
.wiki/
├── pages/            OKF 知识页、会话摘要和引用附件
├── source/evidence/  来源记录、证据清单和历史版本
├── graph/            类型化关系和检索索引
├── ledger/           DuckDB 结构化台账
├── schema.md         页面和实体规范
└── audit.json        编译审计记录
```

```bash
wiki export team-wiki.zip
wiki export onboarding.zip --module modules/onboarding --page concepts/access
wiki okf validate onboarding.zip
wiki import onboarding.zip
wiki okf export ./exports/team-okf
```

ZIP 保留知识页和随包附件的相对路径及元数据。全量导出包括会话页面。按主题分享时，可重复使用 `--module` 和 `--page`，显式带上相关知识页。ZIP 的范围是已编译的 bundle，原文证据历史、运行配置和 DuckDB 数据库留在原库。导入时跳过相同文件，并在合并前报告冲突。`wiki okf` 也支持校验、导入目录及迁移旧版页面元数据。 [分享与导入说明](docs/USAGE.md#13-分享知识库和知识模块)

### 数据处理

知识库和默认检索索引保存在本地。新生成的文本快照和提取文本会脱敏已识别的凭据，原图像素仍可能包含敏感信息。使用远程助手、独立模型或 API OCR 时，操作所需的来源或检索片段可能会发送到所选服务。处理或分享敏感资料前，可以核对当前运行方式、附件和导出包内容。 [隐私与治理](references/privacy-governance.md)

## 独立 OCR

`ocr` 可以脱离 Wiki 单独使用。可根据资料类型、硬件环境或可用模型端点选择后端。

| 后端 | 引擎和典型用途 |
|---|---|
| `paddlevl` | 默认后端。在 Apple Silicon 上用 MLX 运行 PaddleOCR-VL-1.6，提取版面和结构化内容。 |
| `ovis` | MLX 上的 OvisOCR2，可提取 Markdown、公式和图像。 |
| `mineru` | MinerU，用于提取页面布局、表格和公式。 |
| `deepseek` | DeepSeek-OCR-2，用视觉模型解析文档。 |
| `logics` | Logics-Parsing-v2，用于多模态文档解析。 |
| `paddle` | PaddleOCR PP-OCRv5，用于多语言文字识别。 |
| `api` | 已配置的 OpenAI 兼容视觉模型端点。 |

```bash
ocr list --check
ocr --doctor
ocr handbook.pdf --smoke-pages 3
ocr handbook.pdf -o ./parsed/
ocr --batch ./pdfs/
```

OCR 输出 Markdown 和清单。清单记录来源标识、请求页数、实际解析范围和覆盖情况，并在可用时记录资产引用。用 `ocr use <backend>` 切换默认后端，`--backend <backend>` 可单次覆盖，`ocr config` 管理 `~/.config/ocr/config.yaml`。也可以用 `python -m ocr` 或 `wiki ocr` 调用。 [OCR 配置](CONFIGURATION.md#ocr) · [OCR 命令](docs/CLI.md#ocr)

## 评测与文档

- **长文档问答。** 仓库在 PageIndex OSS Benchmark 使用的同一批 34 份 PDF、1,945 页和 62 道问题上记录了 **62/62** 的结果。回答模型和评判模型不同，该数字适合作为同语料的方向性结果。 [评测详情与复现方法](docs/BENCHMARK.md)
- **多模态证据。** 文档场景评测分别考察 PPT 原生结构、PDF 版面恢复、图片纯 OCR，以及补充视觉观察后的检索与问答。 [多模态评测](evals/media_workflows/README.md)
- **混合来源问答。** 混合 Wiki 评测覆盖同名来源、政策版本和干扰页，记录证据召回、引用支持、证据不足时的拒答和本地答案校验。 [混合 Wiki 评测](evals/p1_mixed_wiki/README.md)

可以用 `wiki benchmark <cases.jsonl> --method retrieval` 跑自己的检索用例，查看召回、排序、子目标覆盖率及 P50/P95 检索延迟。`--method both` 还会对提供的答案或抽取式答案计算本地 RAGAS 风格的指标。 [评测命令](docs/CLI.md#benchmark)

| 文档 | 内容 |
|---|---|
| [使用指南](docs/USAGE.md) | 按场景组织的完整流程和可复制命令 |
| [CLI 参考](docs/CLI.md) | 参数、工作单、证据校验和文档处理 |
| [配置指南](CONFIGURATION.md) | 模型、OCR、检索和向量配置 |
| [架构与生命周期](docs/ARCHITECTURE.md) | 存储、检索和知识维护机制 |
| [Agent 技能](SKILL.md) | Agent 编译、问答、维护和分享协议 |

项目受 [Karpathy 的 LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 和 [Rohit 的 v2 扩展](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2) 启发，采用 [MIT 许可](LICENSE)。
