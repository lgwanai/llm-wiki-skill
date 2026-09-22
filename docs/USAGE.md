# llm-wiki 使用指南

本文档面向日常使用，只说明“什么时候使用”和“执行什么命令”。示例不包含运行结果。

## 1. 命令入口

完成可编辑安装后，优先使用 `wiki`：

```bash
pip install -e .
wiki --help
```

如果尚未安装命令行入口，可在项目根目录直接运行脚本：

```bash
python scripts/wiki.py --help
python scripts/wiki.py init
```

后续示例统一使用 `wiki`。把 `wiki` 替换为 `python scripts/wiki.py` 即可使用脚本入口。

## 2. 首次初始化

创建配置文件、初始化 Wiki，并检查当前状态：

```bash
wiki config --init
wiki config --check
wiki init
wiki status
```

默认的 Agent 编译和 Agent 查询不需要配置模型 API。只有显式使用 `--mode llm` 时，才需要在
`wiki_config.yaml` 中配置模型提供方及相应环境变量。

## 3. 编译单个文档

适合导入 Markdown、PDF、Word、PowerPoint、EPUB、图片、代码或普通文本文件：

```bash
wiki compile ./documents/handbook.pdf
```

默认使用 Agent 模式。当前 Agent 会读取完整来源、生成结构化知识页、建立关系和来源追溯。

显式选择 Agent 模式：

```bash
wiki compile ./documents/handbook.pdf --mode agent
```

使用已经配置的模型 API 编译：

```bash
wiki compile ./documents/handbook.pdf --mode llm
```

编译前只检查任务规划，不写入 Wiki：

```bash
wiki compile ./documents/handbook.pdf --dry-run
```

## 4. 编译包含图表和流程图的文档

直接编译包含图表、流程图、泳道图、甘特图、架构图或时序图的 PDF：

```bash
wiki compile ./documents/project-plan.pdf
```

编译时，OCR 用于提取文字、公式和表格；Agent 原生多模态能力用于识别轴线、系列、节点、边、
泳道、任务、依赖和里程碑。原图会保存在 Wiki 资产目录，并进入视觉证据索引。

直接编译图片：

```bash
wiki compile ./images/approval-swimlane.png
wiki compile ./images/release-gantt.png
```

先单独检查 OCR 环境，再进行编译：

```bash
wiki ocr --doctor
wiki ocr ./documents/project-plan.pdf --smoke-pages 3
wiki compile ./documents/project-plan.pdf
```

## 5. 批量编译目录

递归编译目录中的受支持文件：

```bash
wiki compile ./knowledge-sources/
```

只处理目录本身的文件：

```bash
wiki compile ./knowledge-sources/ --depth 0
```

处理当前目录及下一层目录：

```bash
wiki compile ./knowledge-sources/ --depth 1
```

LLM 模式下允许有限并发调用：

```bash
wiki compile ./knowledge-sources/ --mode llm -j 4
```

Agent 模式的大文档会生成有序任务清单。不要让多个 Agent 并行完成同一个清单，因为任务状态按
顺序校验。

## 6. 编译临时文本和标准输入

把一段临时说明直接编译为知识：

```bash
wiki compile --text "退款审批超过五万元时需要财务负责人复核。" --name refund-policy
```

通过标准输入导入文本：

```bash
printf '%s\n' '项目复盘：发布前必须完成回滚演练。' | wiki compile - --name release-retrospective
```

## 7. 普通知识查询

查询知识库并让当前 Agent 基于检索证据组织答案：

```bash
wiki query "订单审批需要经过哪些角色？"
```

查询跨页面关系或多步问题：

```bash
wiki query "设计评审如何影响开发、测试和最终发布时间？" --max-hops 3
```

指定回答格式：

```bash
wiki query "比较方案 A 和方案 B" --format table
wiki query "项目有哪些关键事件？" --format timeline
wiki query "生成项目知识概览" --format slides
wiki query "导出结构化检索结果" --format json
```

## 8. 查询图表、流程图、泳道图和甘特图

问题中直接描述要查的视觉关系。视觉检索流会搜索编译时保存的结构化图表信息，并在回答中附带
命中的原始图片：

```bash
wiki query "甘特图中开发任务依赖哪个里程碑？"
wiki query "审批泳道图中哪个步骤从主管移交给财务？"
wiki query "折线图里哪个区域在第二季度下降最快？"
wiki query "架构图中 API 网关和认证服务之间是什么关系？"
```

只检查原始检索结果及关联图片，不进行答案合成：

```bash
wiki query "开发任务依赖哪个里程碑？" --no-synthesis --json
```

## 9. 查询当前、历史和未来生效规则

查询当前有效政策：

```bash
wiki query "当前差旅报销标准是什么？"
```

查询指定日期当时适用的规则：

```bash
wiki query "截至 2025-12-31，差旅住宿上限是多少？"
```

查询已经公布但尚未生效的变化：

```bash
wiki query "下个月将生效的差旅政策有哪些变化？"
```

编译会区分发布日期、批准日期、生效日期和失效日期。查询时不会仅按文档新旧简单过滤。

## 10. 快速检索与问题诊断

跳过答案合成，只查看排序后的知识页和证据：

```bash
wiki query "预算审批阈值" --no-synthesis
```

查看检索流、分数、多跳路径和证据缺口：

```bash
wiki query "预算审批阈值" --debug-search
```

关闭多跳检索，用于对比或诊断：

```bash
wiki query "预算审批阈值" --single-hop --debug-search
```

检查检索索引健康状态：

```bash
wiki search doctor
```

## 11. 更新来源和强制重编译

来源内容发生变化后重新编译：

```bash
wiki compile ./documents/refund-policy.pdf --force
```

通过 Doctor 重新编译已经登记的问题来源：

```bash
wiki doctor --recompile .wiki/source/refund-policy.pdf
```

OCR 识别不完整时重新 OCR 并编译：

```bash
wiki doctor --re-ocr .wiki/source/slides.pptx
```

## 12. 健康检查和修复

检查页面结构、关系、矛盾、孤立页面和断链：

```bash
wiki lint
```

允许自动修复可安全处理的问题：

```bash
wiki lint --auto-heal
```

用自然语言登记知识问题：

```bash
wiki doctor "退款规则缺少华南地区的例外条件"
wiki doctor --list
```

检查指定知识页：

```bash
wiki doctor --check concepts/refund-policy
```

## 13. OKF 校验、导入和导出

校验一个 OKF v0.1 bundle：

```bash
wiki okf validate ./external-bundle
```

导入另一个 OKF bundle：

```bash
wiki okf import ./external-bundle
```

导出当前 Wiki：

```bash
wiki okf export ./exports/team-wiki
```

迁移旧版页面元数据：

```bash
wiki okf migrate
```

## 14. 台账使用

导入 CSV 或 Excel 台账：

```bash
wiki ledger import ./data/projects.xlsx
wiki ledger list
```

查看台账结构和数据：

```bash
wiki ledger show projects
```

用自然语言查询台账：

```bash
wiki ledger ask projects "列出预算超过五十万元且仍在进行中的项目"
```

执行只读 SQL：

```bash
wiki ledger sql "SELECT * FROM projects WHERE budget > 500000"
```

## 15. 检索评测和 Benchmark

运行检索评测：

```bash
wiki search eval ./evals/retrieval.jsonl
```

运行完整 Benchmark：

```bash
wiki benchmark ./evals/rag_benchmark.jsonl --method both -k 5
```

只评估检索：

```bash
wiki benchmark ./evals/rag_benchmark.jsonl --method retrieval -k 5
```

## 16. 常用帮助命令

查看总帮助和子命令帮助：

```bash
wiki --help
wiki compile --help
wiki query --help
wiki doctor --help
wiki ledger --help
wiki okf --help
```

检查配置和 Wiki 状态：

```bash
wiki config --check
wiki status
wiki search doctor
```

更完整的参数列表见 [CLI Reference](CLI.md)，配置字段见
[CONFIGURATION.md](../CONFIGURATION.md)。
