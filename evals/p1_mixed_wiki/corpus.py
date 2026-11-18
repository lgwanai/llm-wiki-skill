"""Synthetic documents and frozen, locator-level answer keys for P1."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

SEED = 731604


@dataclass(frozen=True)
class Doc:
    key: str
    path: str
    title: str
    pages: tuple[tuple[str, str], ...]
    metadata: dict = field(default_factory=dict)

    def markdown(self) -> str:
        return (
            "\n\n".join(
                f"## Page {i}\n\n### {title}\n\n{body}"
                for i, (title, body) in enumerate(self.pages, 1)
            )
            + "\n"
        )


@dataclass(frozen=True)
class Fact:
    slot: str
    doc: str
    page: int
    value: str
    excerpt: str


@dataclass(frozen=True)
class Case:
    key: str
    group: str
    language: str
    question: str
    slots: tuple[str, ...]
    facts: tuple[Fact, ...]
    control: bool = False


def make_corpus() -> tuple[list[Doc], list[Case]]:
    rng = Random(SEED)
    ridge_days, coast_days, ridge_appeal, coast_appeal = rng.sample(range(28, 98), 4)
    trial_days = rng.randrange(102, 119)
    old_grace, next_grace, future_grace = rng.sample(range(11, 47), 3)
    route_minutes, training_minutes = rng.sample(range(9, 47), 2)
    old_retention, new_retention = rng.sample(range(105, 196), 2)
    workshop_time = f"{rng.randrange(6, 9)}.{rng.choice((10, 20, 40))}pm"
    market_time = f"{rng.randrange(2, 5)}.{rng.choice((15, 25, 45))}pm"
    tide_queue, fallback_queue, training_queue = rng.sample(
        ["TIDE-SLATE", "TIDE-WILLOW", "TIDE-EMBER", "TIDE-LARCH"], 3
    )

    docs = [
        Doc(
            "ridge",
            "青榫站/交接手册.md",
            "青榫站正式交接手册",
            (
                (
                    "青榫站工单录音",
                    f"青榫站工单录音留存期限为 {ridge_days} 天。"
                    f" 申诉窗口为 {ridge_appeal} 天。禁止将工单录音发往站外协作群。",
                ),
                ("青榫站夜班交接", "青榫站夜班纸质交接袋由枚鹭组接收。白班改由杉脊组接收。"),
            ),
        ),
        Doc(
            "coast",
            "晚苇站/交接手册.md",
            "晚苇站正式交接手册",
            (
                (
                    "晚苇站工单录音",
                    f"晚苇站工单录音留存期限为 {coast_days} 天。"
                    f" 申诉窗口为 {coast_appeal} 天。允许将工单录音发往已备案的站外协作群。",
                ),
                ("晚苇站夜班交接", "晚苇站夜班纸质交接袋由苇窗组接收。白班改由盐枝组接收。"),
            ),
        ),
        Doc(
            "drill",
            "演练/交接手册.md",
            "青榫站与晚苇站交接演练手册",
            (
                (
                    "交接演练题",
                    f"演练题同时写有青榫站、晚苇站、工单录音、留存期限、夜班。"
                    f" 演练沙箱留存期限为 {trial_days} 天，虚构接收方为薄汐组。"
                    " 演练流程允许转发模拟录音。演练参数仅适用模拟工单。",
                ),
            ),
        ),
        Doc(
            "old",
            "回传规则/杉涟回传-甲.md",
            "杉涟缓冲包回传规则甲版",
            (
                (
                    "杉涟甲版缓冲包规则",
                    f"甲版自 2026-02-10 起生效，至 2026-07-01 失效。"
                    f" 杉涟缓冲包的回传宽限为 {old_grace} 分钟。"
                    " 禁止将杉涟缓冲包发往外部分拣点。",
                ),
                ("杉涟甲版验收留存", f"杉涟验收摘要留存期限为 {old_retention} 天。"),
            ),
            {
                "effective_from": "2026-02-10",
                "effective_until": "2026-07-01",
                "superseded_by": ["concepts/shuilian-new-p1"],
            },
        ),
        Doc(
            "new",
            "回传规则/杉涟回传-乙.md",
            "杉涟缓冲包回传规则乙版",
            (
                (
                    "杉涟乙版缓冲包规则",
                    f"乙版自 2026-07-01 起生效，替代甲版，并于 2026-12-01 失效。"
                    f" 杉涟缓冲包的回传宽限为 {next_grace} 分钟。"
                    " 允许将杉涟缓冲包发往已备案的外部分拣点。",
                ),
                ("杉涟乙版验收留存", f"杉涟验收摘要留存期限为 {new_retention} 天。"),
            ),
            {
                "effective_from": "2026-07-01",
                "effective_until": "2026-12-01",
                "supersedes": ["concepts/shuilian-old-p1"],
            },
        ),
        Doc(
            "future",
            "回传规则/杉涟回传-丙.md",
            "杉涟缓冲包已发布的丙版",
            (
                (
                    "杉涟丙版缓冲包规则",
                    f"丙版于 2026-08-21 发布，自 2026-12-01 起才生效。"
                    f" 杉涟缓冲包的回传宽限为 {future_grace} 分钟。"
                    " 禁止将杉涟缓冲包发往外部分拣点。",
                ),
            ),
            {"effective_from": "2026-12-01", "supersedes": ["concepts/shuilian-new-p1"]},
        ),
        Doc(
            "relay",
            "工程/relay-handoff.md",
            "岬星 Relay Gate 生产运行手册",
            (
                (
                    "Relay Gate 生产入口",
                    f"岬星 Relay Gate 的生产 alias 是 Starling Relay。"
                    f" 正常 ACK 进入 {tide_queue}。岬星生产环境禁止自动重试 DUP-4。",
                ),
                (
                    "Relay Gate 降级记录",
                    f"岬星 Relay Gate 的 fallback queue 为 {fallback_queue}。"
                    f" on-call 在 DLQ 保持 {route_minutes} 分钟后才人工转发。"
                    " 记录字段为 transfer checksum 与 operator alias。",
                ),
            ),
        ),
        Doc(
            "rehearsal",
            "工程/relay-rehearsal.md",
            "岬星 Relay Gate 培训沙盒",
            (
                (
                    "Relay Gate 练习配置",
                    f"岬星 Relay Gate / Starling Relay 的 training sandbox "
                    f"将 fallback queue 写作 {training_queue}。DLQ 保持 {training_minutes} 分钟。"
                    " 沙盒允许自动重试 DUP-4。该页仅供培训。",
                ),
            ),
        ),
        Doc(
            "wax",
            "采购/蜡桥验收备忘.md",
            "蜡桥导轨采购验收备忘",
            (
                (
                    "采购验收批准人",
                    "蜡桥导轨采购验收的 final approver 为乔弦。 交接通知抄送回纹组。",
                ),
                (
                    "采购验收校验",
                    "蜡桥导轨的 pallet checksum 算法为 Hazel-9。 算法只用于箱单核对。",
                ),
            ),
        ),
        Doc(
            "pack",
            "采购/货架抽检说明.md",
            "蜡桥导轨供应商演示记录",
            (
                (
                    "供应商演示",
                    "蜡桥导轨的示例 final approver 为沈铎。"
                    " Vendor Sandbox 的 pallet checksum 示例算法为 Alder-6。"
                    " 该演示未进入正式验收流程。",
                ),
            ),
        ),
        Doc(
            "market",
            "场馆/a-fen-market.md",
            "枯蒲集市器材窗口",
            (
                (
                    "枯蒲集市窗口时间",
                    "枯蒲集市器材窗口开放时间如下。\n"
                    f"Monday to Thursday: 9.00am–{market_time}\nFriday: 8.00am–2.00pm",
                ),
            ),
        ),
        Doc(
            "workshop",
            "场馆/z-tidal-workshop.md",
            "潮桥工坊借具窗口",
            (
                (
                    "潮桥工坊借具窗口时间",
                    "潮桥工坊借具窗口开放时间如下。\n"
                    f"Monday to Thursday: 10.00am–{workshop_time}\nFriday: 10.00am–5.00pm",
                ),
            ),
        ),
        Doc(
            "quay",
            "场馆/鹭湾外借台.md",
            "鹭湾外借台说明",
            (
                (
                    "鹭湾外借台须知",
                    "鹭湾外借台支持凭卡预约取件。本文只说明预约和归还流程。 取件需出示蓝色纸签。",
                ),
            ),
        ),
    ]

    cases: list[Case] = []

    def add(
        key: str,
        group: str,
        language: str,
        question: str,
        *facts: Fact,
        missing: str = "",
        control: bool = False,
    ) -> None:
        slots = tuple(fact.slot for fact in facts) if facts else (missing,)
        cases.append(Case(key, group, language, question, slots, facts, control))

    def fact(slot: str, doc: str, page: int, value: str, excerpt: str) -> Fact:
        return Fact(slot, doc, page, value, excerpt)

    add(
        "S01",
        "同名文件",
        "中文",
        "青榫站正式《交接手册》规定，工单录音要保留多少天？",
        fact("留存", "ridge", 1, f"{ridge_days} 天", f"留存期限为 {ridge_days} 天"),
    )
    add(
        "S02",
        "同名文件",
        "中文",
        "晚苇站正式《交接手册》的工单录音留存期限是多久？",
        fact("留存", "coast", 1, f"{coast_days} 天", f"留存期限为 {coast_days} 天"),
    )
    add(
        "S03",
        "同名文件",
        "混合",
        "请比较青榫站与晚苇站正式《交接手册》的 night shift 交接袋接收组。",
        fact("青榫站", "ridge", 2, "枚鹭组", "夜班纸质交接袋由枚鹭组接收"),
        fact("晚苇站", "coast", 2, "苇窗组", "夜班纸质交接袋由苇窗组接收"),
    )
    add(
        "S04",
        "同名文件",
        "中文",
        "正式工作中，青榫站工单录音可以发往站外协作群吗？",
        fact("规定", "ridge", 1, "禁止", "禁止将工单录音发往站外协作群"),
    )
    add(
        "S05",
        "同名文件",
        "中文",
        "晚苇站工单录音能发进已备案的站外协作群吗？",
        fact("规定", "coast", 1, "允许", "允许将工单录音发往已备案的站外协作群"),
    )
    add(
        "S06",
        "同名文件",
        "中文",
        "青榫站的工单录音争议，申诉窗口多少天？",
        fact("申诉", "ridge", 1, f"{ridge_appeal} 天", f"申诉窗口为 {ridge_appeal} 天"),
    )

    add(
        "T01",
        "新旧规则",
        "中文",
        "截至2026-06-25，杉涟缓冲包回传宽限是多少分钟？",
        fact("宽限", "old", 1, f"{old_grace} 分钟", f"回传宽限为 {old_grace} 分钟"),
    )
    add(
        "T02",
        "新旧规则",
        "混合",
        "As of 2026-09-03，杉涟缓冲包的回传 grace period 是多少分钟？",
        fact("宽限", "new", 1, f"{next_grace} 分钟", f"回传宽限为 {next_grace} 分钟"),
    )
    add(
        "T03",
        "新旧规则",
        "中文",
        "截至2026-12-15，杉涟缓冲包回传规则给多少分钟宽限？",
        fact("宽限", "future", 1, f"{future_grace} 分钟", f"回传宽限为 {future_grace} 分钟"),
    )
    add(
        "T04",
        "新旧规则",
        "中文",
        "在2026-06-25，能把杉涟缓冲包发到已备案的外部分拣点吗？",
        fact("规定", "old", 1, "禁止", "禁止将杉涟缓冲包发往外部分拣点"),
    )
    add(
        "T05",
        "新旧规则",
        "中文",
        "在2026-09-03，杉涟缓冲包能发到已备案的外部分拣点吗？",
        fact("规定", "new", 1, "允许", "允许将杉涟缓冲包发往已备案的外部分拣点"),
    )
    add(
        "T06",
        "新旧规则",
        "混合",
        "对比杉涟甲版和乙版，验收摘要的 retention 各是多少天？",
        fact("甲版", "old", 2, f"{old_retention} 天", f"留存期限为 {old_retention} 天"),
        fact("乙版", "new", 2, f"{new_retention} 天", f"留存期限为 {new_retention} 天"),
    )

    add(
        "D01",
        "干扰页",
        "混合",
        "岬星生产环境的 Relay Gate，fallback queue 的队列名是什么？",
        fact("队列", "relay", 2, fallback_queue, f"fallback queue 为 {fallback_queue}"),
    )
    add(
        "D02",
        "干扰页",
        "混合",
        "岬星 Starling Relay 在 production 是否允许 auto-retry DUP-4？",
        fact("规定", "relay", 1, "禁止", "生产环境禁止自动重试 DUP-4"),
    )
    add(
        "D03",
        "干扰页",
        "混合",
        "岬星 Relay Gate 正常 ACK 落哪条队列，DLQ 又要等多久才人工转发？",
        fact("正常队列", "relay", 1, tide_queue, f"正常 ACK 进入 {tide_queue}"),
        fact("等待", "relay", 2, f"{route_minutes} 分钟", f"DLQ 保持 {route_minutes} 分钟"),
    )
    add(
        "D04",
        "干扰页",
        "混合",
        "正式流程里，蜡桥导轨采购验收的 final approver 是谁？",
        fact("批准人", "wax", 1, "乔弦", "final approver 为乔弦"),
    )
    add(
        "D05",
        "干扰页",
        "混合",
        "正式验收时，蜡桥导轨的 pallet checksum 用哪个算法？",
        fact("算法", "wax", 2, "Hazel-9", "pallet checksum 算法为 Hazel-9"),
    )
    add(
        "D06",
        "干扰页",
        "中文",
        "潮桥工坊借具窗口周二几点停止借具？",
        fact(
            "结束时间", "workshop", 1, workshop_time, f"Monday to Thursday: 10.00am–{workshop_time}"
        ),
    )

    add("N01", "无答案", "中文", "青榫站《交接手册》规定的工单录音加密算法是什么？", missing="算法")
    add(
        "N02",
        "无答案",
        "混合",
        "岬星 Relay Gate 生产环境的 PagerDuty escalation phone 是什么？",
        missing="电话",
    )
    add("N03", "无答案", "中文", "截至2025-11-01，杉涟缓冲包回传宽限是多少分钟？", missing="宽限")
    add(
        "N04",
        "无答案",
        "混合",
        "蜡桥导轨正式验收的 replacement unit price 是多少？",
        missing="单价",
    )
    add("N05", "无答案", "中文", "晚苇站白班负责人实名是什么？", missing="姓名")
    add("N06", "无答案", "混合", "潮桥工坊借具窗口 Sunday 开放时段到几点？", missing="结束时间")

    add(
        "C01",
        "问句规则探针",
        "混合",
        "潮桥工坊借具窗口的 Tuesday close 时间是什么？",
        fact(
            "结束时间", "workshop", 1, workshop_time, f"Monday to Thursday: 10.00am–{workshop_time}"
        ),
        control=True,
    )
    add(
        "C02",
        "问句规则探针",
        "混合",
        "枯蒲集市器材窗口的 Tuesday close 时间是什么？",
        fact("结束时间", "market", 1, market_time, f"Monday to Thursday: 9.00am–{market_time}"),
        control=True,
    )
    add(
        "C03",
        "问句规则探针",
        "混合",
        "鹭湾外借台 Tuesday close 时间是什么？",
        missing="结束时间",
        control=True,
    )
    return docs, cases
