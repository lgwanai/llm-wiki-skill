# llm-wiki 改进方向

> 深度 Review 日期: 2026-06-11
> 基于 Karpathy's LLM Wiki + Rohit's v2 设计理念
> 当前状态: 132 tests passing, Faithfulness 1.00, Answer Correctness 0.91

---

## ★★★ 高优先级 (改动小, 收益大)

### 1. LLM API 重试 & 超时

**问题**: `call_llm()` 没有重试逻辑, 一次网络抖动就导致整个编译失败。`benchmark_ragas.py` 已有 3 次重试 + 指数退避模式, 但未提取到公共函数。

**影响**: 稳定性。编译一篇长文档需要 ~30s, 中途失败浪费用户时间和 API 费用。

**方案**:
- 从 `benchmark_ragas.py` 提取重试逻辑到 `_llm_utils.py` 公共模块
- `call_llm()` 默认 3 次重试, 429 时退避, 非可重试错误(401)直接抛出
- 超时从 300s 缩短到 120s(正常编译 < 60s)

**代码量**: ~30 行

---

### 2. 编译 Dry-Run 模式

**问题**: 用户想知道"这篇文档会提取出什么"而不是直接写入。当前只能 `--force` 覆盖或跳过, 没有预览能力。

**影响**: 新用户不敢随便编译, 怕产生垃圾页面。

**方案**:
```bash
wiki compile paper.md --dry-run  # 调用 LLM 但不写文件, 打印预览
```

**代码量**: ~40 行(在 compile_v2.py 中增加 dry_run 参数, 跳过 atomic_write 和 graph 更新)

---

### 3. 事实提取闭环断裂

**问题**: 当前 LLM 不输出 `## Key Facts` 表格, 只输出 `## Key Details` 的 `**key**: value` 格式。`_lead_section_boost` 不区分"精确事实"和"步骤描述", 噪声大。

**影响**: Answer Correctness 0.91 的剩余 0.09 主要来自这里 — LLM 有时找不到精确数值因为事实跟描述混在一起。

**方案**:
- 在 compile prompt 中将 `## Key Facts` 表格设为**第一个必须输出**(放在 Overview 前面)
- 用更强制性的语言: "You MUST include this section. Pages without a Key Facts table will be rejected."
- 增加 `questions` 字段引导: "这个页面能回答哪些具体问题? 列 2-3 个"

**代码量**: prompt 修改 ~20 行, query.py 解析逻辑不用改

---

### 4. 大文档分段编译

**问题**: 整篇文档一次性发给 LLM, 超过 32K token 的文档后半部分实体可能丢失。LLM 注意力在长上下文中衰减, 后半部分提取质量下降。

**影响**: 长论文/技术报告(如 DeepSeek-V4 paper ~260K chars)后半部分的技术细节可能漏掉。

**方案**:
- 对超过 15K 字符的文档按 `## ` 标题自动切段
- 每段独立调用 LLM 编译(每段限制 12K chars)
- 最后合并去重: 同名 entity → 置信度叠加, concept → 内容合并
- `--chunk-size` 参数可调

**代码量**: ~100 行(新增 `_split_document` + 修改 `compile_source` 循环)

---

## ★★ 中优先级 (改动中等, 收益显著)

### 5. 图谱深度利用

**问题**: `graph_search` 只做实体名匹配 + 1-hop 遍历。12 种关系类型未被查询利用。

**方案**:

**5a. 路径查询** (已部分实现):
```bash
wiki query "X 和 Y 之间有什么依赖关系?"  # 自动调用 find_path
```
在 `plan_query` 中增加路径意图检测, 查到路径后以可视化文本输出。

**5b. 影响力分析** (已实现 `impact_analysis`, CLI 入口不直观):
```bash
wiki search --impact <entity-id>  # 已有, 但用户不知道
```
在 `wiki query` 中当检测到"影响/依赖"意图时自动展示。

**5c. 孤立实体发现**:
```bash
wiki lint  # 增加孤立实体检测: 有 entity 页面但没有 edges 连接的
```
`graph.py` 的 `graph_stats()` 已有 orphan_count, 只是 lint 没调用。

**代码量**: ~60 行(lint 集成 + query 意图路由)

---

### 6. 增量编译

**问题**: 当前 `--force` 完全重建。对于只改了 10% 的文档, 应该只更新受影响的页面。

**方案**:
- 编译前 diff 新旧 LLM 输出
- 只写入新增/变更的页面, 删除不再存在的页面(可选)
- 保留用户手动编辑的内容(通过 `source: manual` 标记)

**代码量**: ~150 行(核心是页面 diff + 选择性写入)

---

### 7. 查询排序可解释性

**问题**: `--debug-search` 输出 JSON trace, 不方便人阅读。

**方案**: 改为 Markdown 表格:
```
| Rank | Page ID | BM25 | Metadata | Graph | Final Score |
|------|---------|------|----------|-------|-------------|
| 1    | audit-log-retention | 0.45 | 0.30 | 0.15 | 0.90 |
```

**代码量**: ~30 行(在 `_main()` 或 `query_wiki()` 中增加格式化输出)

---

### 8. 宽泛 `except Exception` 静默吞错

**问题**: 18 处 `except Exception` 无日志, 调试困难。

**影响**: 生产环境出问题找不到原因。

**方案**:
- 最少输出 `traceback.format_exc()` 到 stderr
- 可选: 写入 audit log 的错误通道

**代码量**: 逐处修改, ~50 行

---

## ★ 低优先级 (改动大或收益间接)

### 9. 并发编译

**问题**: `compile_path` 逐文件串行调用 LLM, 12 篇文档 ~10 分钟

**方案**: Thread pool (3-4 并发), 限制并发数防止 API rate limit

**代码量**: ~80 行(`concurrent.futures.ThreadPoolExecutor`)

**风险**: API rate limit, 需要可配并发数

---

### 10. BM25 增量更新

**问题**: 当前任何页面修改都重建全量索引。目前 199 页 ~0.1s, 问题不大。但设计上 10K+ 页时需要增量更新。

**方案**: 写入时更新单页 BM25 token/freq, 而非全量重建。用 `filesize + mtime` 检测单页变更。

**代码量**: ~100 行(修改 `_pages_changed` 为增量检测)

**时机**: Wiki 超过 1000 页后再做

---

### 11. 配置 Schema 校验

**问题**: `wiki_config.yaml` 没有 schema 验证。用户可能配错 OCR backend 和 API key, 运行时才知道。

**方案**: 用 pydantic 或简单 dict 校验, `wiki config` 时检查并提示

**代码量**: ~80 行

---

### 12. 端到端测试

**问题**: 132 个单元测试, 但核心路径(compile → search → answer)缺乏 e2e 测试。

**方案**: 添加 3-5 个 e2e 测试:
- 编译 1 篇短文档 → 搜索 → 断言结果包含特定页面
- 查询已知实体 → 断言返回结果非空
- 编译 + 台账交叉链接 → 断言 wiki 页面有 `linked_ledger_tables`

**代码量**: ~100 行(利用 tmp_path, 需要 mock LLM 或小文档)

---

## 架构层面建议

| 维度 | 当前 | 建议 |
|------|------|------|
| 公共 LLM 调用 | 3 处重复(`compile_v2`, `query`, `benchmark_ragas`) | 提取到 `_llm_utils.py` |
| 错误处理 | `except Exception: pass` | 结构化错误日志 |
| 缓存策略 | 模块级全局变量 | 考虑 `functools.lru_cache` 或显式 CacheManager 类 |
| 配置热加载 | 不支持 | 增加 `wiki config --reload` 或文件 watch |
| 并发安全 | 单进程, 无线程安全 | 多文件编译时加文件锁 |

---

## 优先级排序

```
1. LLM API 重试 (#3)      ← 最影响稳定性, 5 行/函数
2. 编译 dry-run (#4)       ← 用户体验, ~40 行
3. 事实提取闭环 (#1)       ← 直接影响 Answer Correctness
4. 大文档分段 (#2)         ← 防止长文档信息丢失
5. 排序可解释性 (#7)       ← 调试必备
6. 图谱深度利用 (#5)       ← 差异化能力, lint 集成
7. 宽泛异常处理 (#8)       ← 可观测性
8. 增量编译 (#6)           ← 大型 wiki 效率
9. 并发编译 (#9)           ← 速度
10. 配置校验 (#11)
11. 端到端测试 (#12)
12. BM25 增量更新 (#10)    ← >1000 页后再做
```
