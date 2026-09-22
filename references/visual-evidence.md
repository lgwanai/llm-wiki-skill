# Visual Evidence Compilation

OCR answers “which characters are visible.” It does not reliably answer “which box points to
which box,” “who owns this step,” “which task blocks another,” or “which series rises after a
milestone.” Compile visual semantics separately and keep the exact source image beside them.

## Required record

Every information-bearing figure retained in a compiled concept has one frontmatter `visuals`
entry. Paths are relative to the concept page and point to the persisted original under
`.wiki/pages/assets/**`.

```yaml
visuals:
  - id: approval-swimlane-p12
    kind: swimlane
    title: 订单审批泳道图
    image: ../assets/policy/page-012.png
    source_locator: Page 12
    summary: 申请人提交后由主管审批；金额超阈值时转财务复核。
    keywords: [订单审批, 金额阈值, 财务复核, 交接]
    entities: [申请人, 主管, 财务]
    lanes: [申请人, 主管, 财务]
    nodes:
      - {id: submit, label: 提交订单, lane: 申请人, shape: start}
      - {id: manager, label: 主管审批, lane: 主管, shape: decision}
      - {id: finance, label: 财务复核, lane: 财务, shape: process}
    edges:
      - {from: submit, to: manager, label: 提交, kind: sequence}
      - {from: manager, to: finance, label: 超过阈值, kind: conditional_handoff}
    handoffs:
      - {from_lane: 主管, to_lane: 财务, condition: 超过阈值}
    uncertainty: []
```

Do not put host-specific absolute paths in `image`. Never replace the source visual with a
redrawn diagram. Crops may supplement the original, but the original must remain displayable.

## Type-specific structure

### Charts and plots

Record `axes`, `series`, legend mapping, readable values, units, annotations, and trends. Keep
individual observations distinct from an inferred trend. A pie or donut chart may use
`axes: {type: categorical}` so the field remains explicit.

```yaml
kind: line_chart
axes: {x: 月份, y: {label: 故障数, unit: 次}}
series:
  - name: 华东
    legend: 蓝线
    values: [{x: 2026-01, y: 18}, {x: 2026-02, y: 11}]
trends: [华东故障数下降]
```

### Flowcharts, architecture, and sequence diagrams

Record stable node IDs, exact labels, node roles/shapes, directed edges, edge labels, conditions,
boundaries, external systems, and loops. Never infer arrow direction when the connector is
ambiguous; put it in `uncertainty`.

### Swimlanes

Record `lanes`, each node's lane/owner, directed `edges`, cross-lane `handoffs`, decisions,
exceptions, and loops. Lane order alone does not establish process order.

### Gantt charts

Record the displayed `timescale`, tasks, groups/owners, readable start/end or duration,
dependencies, milestones, progress, and critical path only when visible.

```yaml
kind: gantt
timescale: week
tasks:
  - {id: design, label: 方案设计, start: 2026-09-01, end: 2026-09-12}
  - {id: review, label: 设计评审, milestone: true, date: 2026-09-15}
  - {id: build, label: 开发, start: 2026-09-16, depends_on: [review]}
```

Never invent dates hidden by resolution or compression. Use `unreadable` or an `uncertainty`
entry and preserve the image for human verification.

## Body evidence

Each page with `visuals` includes a display section:

```markdown
## 图表与视觉证据

![订单审批泳道图（原图）](../assets/policy/page-012.png)

图中有三个泳道。申请人提交订单后进入主管审批；只有“超过阈值”分支跨泳道交给财务。
连接到“归档”的箭头较模糊，方向待核验。
```

The prose should answer likely questions using visually encoded meaning, not merely repeat OCR
labels. It should mention important relationships, conditions, scale, ownership, and uncertainty.

## Retrieval and answer display

The `visual` search stream indexes both common and type-specific fields. Query-time fusion returns
matched `visual_hits`; synthesis receives those records, and the final result exposes the original
asset in `visuals` and `images`. If a page has multiple figures, prefer the specifically matched
images instead of displaying unrelated figures from the same page.

Agent task completion fails closed when an image-bearing compiled page lacks structured visual
records, references a missing image, omits the visual evidence section, or omits required
type-specific structure.
