# llm-wiki 工作场景深测

这次在独立的临时 Wiki 中混搜四份资料，覆盖 **106 题**：PPT 33、JPG 31、合成 PDF 24、艾瑞报告 18。每份资料含一题原文没有答案的反例。题库及预期字段在 [questions.py](questions.py)，逐题召回和回答由 [run.py](run.py) 输出。三份合成资料是虚构的，答案以交付文件中的图、表和代码为准。

| 场景 | 材料 | 代表性问题 |
|---|---|---|
| Northstar 上线评审 | [8 页可编辑 PPT](fixtures/northstar-release.pptx) | 审批的两条分支；组件多跳路径；直接与间接汇报；SLA 差值；甘特图周窗；总分树；闭环事件数与预算占比 |
| Orion 运行手册截图 | [JPG](fixtures/orion-runbook.jpg) | 两条路径怎样汇合；队列下游；谁向 Maya 汇报；P1/P3 时限差；工期重叠；图中数量、增幅和占比 |
| Harbor 容量评审 | [5 页 PDF](fixtures/harbor-capacity.pdf) | HTTP 重试代码跨第 1–2 页；第 1–3 页表格只有第一页有表头；第 4 页并列四表同名行；第 5 页柱形与饼图 |
| 艾瑞真实报告 | 用户提供，72 页 | 区分整体/新一代 AI 采纳率；按图例核对双系列；找图下注释；比较两个年份的预测；还原架构接入和内置 Agent |

## 实测结果

“完整证据”要求检索前五或其同源相邻页包含题目所需的全部片段，涉及关系时核查方向，涉及表格时核查行内绑定。它比“找到了相关页”严格；反例不进入该分母。“回答通过”检查回答中的预期字段、运算结果或应拒答表现。它不是自由文本语义准确率或所有引文的完整评审。对差异题及计算题另做人工检查。

| 场景 | 完整证据：旧 → 新 | 回答字段通过：旧 → 新 |
|---|---:|---:|
| PPT | 0/32 → **32/32** | 6/33 → **33/33** |
| JPG，纯 OCR | 0/30 → **4/30** | 旧版 7/31；新版纯 OCR 未重复调用回答模型 |
| JPG，Codex 看图后归档 | — → **30/30** | — → **31/31** |
| 合成 PDF | 7/23 → **23/23** | 24/24 → **24/24** |
| 艾瑞报告 | 14/17 → **17/17** | 由 Codex 本地复核 [18 题](report-agent-answers.md) |

- PPT 的旧版基线是项目配置的本地 PaddleOCR-VL；它通常把流程、架构、组织图、甘特图及图表保留为裁图，SLA 是可读 HTML。新版直接读取连接线端点、方向、决策标签、表格和图表数据。混有图片时保留同页原生数据和 OCR 结果。原生总分树夹具由可编辑形状搭成，并不是 PowerPoint 的 SmartArt 对象；代码另支持读取 SmartArt 数据模型中的 [父子连接](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/7eaf0521-721d-405f-8e0b-133f4e81fc43)。
- JPG 的已配置视觉 API 实测失败，随后落回本地 OCR；它能读取 SLA 表，不能可靠恢复箭头、甘特图和图表。JPG 的 31/31 是 Codex 检查原图后将观察结果归档、再由 llm-wiki 检索和回答的结果。观察记录与 OCR 原文分开存储，见 [视觉记录](fixtures/orion-reviewed.md)。
- PDF 的旧版答案模型能从分散的文字推回不少正确答案，但证据里没有续表表头、四表行列及可靠的柱值对应关系。新版基于明确的续表标题和对齐的列边界继承表头，保留页码，围栏保留代码缩进；只有柱形、轴标签与数值能唯一对应时才生成数据表。
- 艾瑞报告已索引 72 页，市场规模图的 6 个年份可从原生布局绑定对应柱值。复杂图例、折线和颜色语义仍应核看原页。报告题在本地作答。早期合成题调用回答模型时，混搜返回的少量附件片段随上下文一并发送；最终复测在调用前排除了附件证据。
- 计算题先从同一个图表系列取值。例如 PPT 的 24 + 36 + 60 = 120，10 月占 50%。明确指定一个原生柱状图、全部可见周期和计数口径时，合计可以直接计算和引用，无需调用回答模型。Harbor 六地合计 162 名 worker，需合并第 1–3 页。三份合成资料的 3 道无答案反例均明确表示证据不足。

## 延迟

同一台机器，单跳、仅启用 raw 证据流、前五结果。无向量、无远程重排。读取时间与问答模型时间分别计量；数字不代表生产网络延迟。

| 操作 | 基线 | 当前 |
|---|---:|---:|
| PPT 读取、索引并生成 Agent 任务 | 18.53 s（渲染 + PaddleOCR） | **0.26 s**（原生对象） |
| Harbor PDF 读取、索引并生成 Agent 任务 | 12.89 s（渲染 + PaddleOCR） | **0.31 s**（启用原生模式） |
| 四份资料混搜，热查询 p50 | 16.44 ms | **15.24 ms** |
| 四份资料混搜，热查询 p95 | 34.37 ms | **28.87 ms** |

表中的 PDF 耗时是自适应路由上线前的原生提取测量。当前编译默认逐页判定，若需要 OCR 或 Agent 复核，端到端耗时还需计入这些步骤。评测脚本单独测原生证据层。

合成 PDF 与附件的准确率基线均为旧版原生纯文本。新布局提取比纯文本多做了表格和坐标分析：本次真实附件提取约 1.3 秒，旧纯文本约 0.24 秒。相对 OCR 路径的 PDF 提速是另一组对照；冷启动没有显示稳定改善。上述混搜延迟来自不调用回答模型的自动提取对照；最终含视觉记录的问答复测，检索 p50/p95 为 15.50/29.98 ms。JPG 的 PaddleOCR 加任务生成实测 6.61 秒；Codex 看图时间未计入检索延迟。

## 复跑

在仓库根目录运行。报告可省略，届时只测三份合成文件。默认读取随夹具保存的 PaddleOCR 结果；也可以传入自己的 `--jpg-ocr`、`--ppt-ocr`。加 `--answers` 才会调用已配置的模型，且仅发送合成资料的证据。报告必须保留在本地，代码会在合成问答前排除来自真实报告的检索结果。

```bash
mkdir -p build/media-eval/baseline
git archive 58780c7 | tar -x -C build/media-eval/baseline

python evals/media_workflows/run.py --workspace build/media-eval/before \
  --baseline-repo build/media-eval/baseline --report "/path/to/report.pdf"

python evals/media_workflows/run.py --workspace build/media-eval/after \
  --reviewed-image --report "/path/to/report.pdf"

python -m pytest -q tests/test_media_evidence.py
```

PPT 和 PDF 有生成脚本 [build_deck.mjs](build_deck.mjs)、[build_pdf.py](build_pdf.py)。JPG 通过内置 imagegen 生成，再转 JPEG；[生成提示词](image-prompt.txt)附后。
