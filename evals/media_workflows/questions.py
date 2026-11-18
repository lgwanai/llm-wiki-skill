"""Independent question and evidence oracles for work scenarios.

Each support item is a physical page/slide and literal evidence required on it.
The optional answer fields are checked in the final response, excluding citations.
"""

from typing import Any

CASES: list[dict[str, Any]] = []


def q(doc: str, category: str, text: str, support: dict[int, list[str]], *answer: str) -> None:
    CASES.append(
        {
            "id": f"{doc}-{sum(c['doc'] == doc for c in CASES) + 1:02d}",
            "doc": doc,
            "category": category,
            "question": text,
            "support": support,
            "answer": answer,
        }
    )


def slide(category: str, n: int, text: str, evidence: str, *answer: str) -> None:
    q("ppt", category, text, {n: evidence.split(";")}, *answer)


slide(
    "workflow",
    1,
    "上线冻结期间，变更入口后先经过什么？",
    "Change intake → Risk review",
    "Risk review",
)
slide(
    "workflow",
    1,
    "What happens on the No branch of the emergency change decision?",
    "Approved? → Return to owner [No]",
    "Return to owner",
)
slide(
    "workflow",
    1,
    "If a change is approved, list the two remaining stages in order.",
    "Approved? → Canary deploy [Yes];Canary deploy → Monitor",
    "Canary deploy",
    "Monitor",
)
slide(
    "workflow",
    1,
    "Which node makes the branching decision on slide 1?",
    "Risk review → Approved?",
    "Approved",
)
slide(
    "workflow",
    1,
    "Does the rejection route directly to Monitor, or back to its owner?",
    "Approved? → Return to owner [No]",
    "Return to owner",
)
slide(
    "architecture",
    2,
    "Trace the online entry from Console to Policy Engine.",
    "Console → Edge API;Edge API → Policy Engine",
    "Console",
    "Edge API",
    "Policy Engine",
)
slide(
    "architecture",
    2,
    "Policy Engine 有哪些直接下游？",
    "Policy Engine → Event Bus;Policy Engine → Metrics Store",
    "Event Bus",
    "Metrics Store",
)
slide(
    "architecture",
    2,
    "Which component directly feeds Ledger Writer?",
    "Event Bus → Ledger Writer",
    "Event Bus",
)
slide(
    "architecture",
    2,
    "From Policy Engine, what two-hop route reaches Ledger Writer?",
    "Policy Engine → Event Bus;Event Bus → Ledger Writer",
    "Event Bus",
    "Ledger Writer",
)
slide(
    "organization",
    3,
    "Identity Team 的直属主管是谁？",
    "Platform Lead → Identity Team",
    "Platform Lead",
)
slide(
    "organization",
    3,
    "Who are the direct reports of Delivery Director?",
    "Delivery Director → Platform Lead;Delivery Director → Service Lead",
    "Platform Lead",
    "Service Lead",
)
slide(
    "organization",
    3,
    "What is the escalation chain from Runtime Team up to Delivery Director?",
    "Platform Lead → Runtime Team;Delivery Director → Platform Lead",
    "Runtime Team",
    "Platform Lead",
    "Delivery Director",
)
slide(
    "organization",
    3,
    "Does Support Team report to Platform Lead or Service Lead?",
    "Service Lead → Support Team",
    "Service Lead",
)
slide(
    "table", 4, "What is the first-update limit for SEV-A in minutes?", "SEV-A | 12 | Runtime", "12"
)
slide(
    "table",
    4,
    "SEV-B 的负责人和首次更新时限分别是什么？",
    "SEV-B | 36 | Identity",
    "Identity",
    "36",
)
slide("table", 4, "Which severity is Support responsible for?", "SEV-C | 90 | Support", "SEV-C")
slide(
    "table",
    4,
    "How many minutes longer is SEV-C's first-update limit than SEV-B's?",
    "SEV-C | 90 | Support;SEV-B | 36 | Identity",
    "54",
)
slide(
    "gantt",
    5,
    "When does Migration start and finish on the rollout schedule?",
    "Migration | W2–W3",
    "W2",
    "W3",
)
slide(
    "gantt", 5, "Discovery 与 Migration 重叠在哪一周？", "Discovery | W1–W2;Migration | W2–W3", "W2"
)
slide("gantt", 5, "Which activity occupies W4 on the release schedule?", "Cutover | W4", "Cutover")
slide(
    "gantt",
    5,
    "How many weekly windows does Discovery occupy, counting both ends?",
    "Discovery | W1–W2",
    "2|two|两",
)
slide(
    "hierarchy",
    6,
    "Go-live readiness 下一级的两个分支是什么？",
    "Go-live readiness → Security;Go-live readiness → Reliability",
    "Security",
    "Reliability",
)
slide(
    "hierarchy",
    6,
    "Which branch owns the Failover drill in the readiness tree?",
    "Reliability → Failover drill",
    "Reliability",
)
slide(
    "hierarchy",
    6,
    "What is the complete path from Go-live readiness to Access review?",
    "Go-live readiness → Security;Security → Access review",
    "Go-live readiness",
    "Security",
    "Access review",
)
slide("bar", 7, "How many incidents closed in September (Sep)?", "Sep | 36", "36")
slide(
    "bar",
    7,
    "What is October's share of the three-month closed incident total?",
    "Aug | 24;Sep | 36;Oct | 60",
    "50\\s*%|half|一半",
)
slide("bar", 7, "10 月（Oct）的结案数比 8 月（Aug）多几个？", "Aug | 24;Oct | 60", "36")
slide(
    "bar",
    7,
    "How many incidents closed across all three displayed months?",
    "Aug | 24;Sep | 36;Oct | 60",
    "120",
)
slide(
    "pie",
    8,
    "What share of planned delivery hours is allocated to Service?",
    "Service | 27 | 27%",
    "27\\s*%",
)
slide("pie", 8, "Platform 比 Risk 多几个百分点？", "Platform | 54 | 54%;Risk | 19 | 19%", "35")
slide(
    "pie",
    8,
    "What share of capacity remains if Platform is excluded?",
    "Service | 27 | 27%;Risk | 19 | 19%",
    "46\\s*%",
)
slide(
    "pie",
    8,
    "What is the Platform-to-Service allocation ratio?",
    "Platform | 54 | 54%;Service | 27 | 27%",
    "2\\s*[:：]\\s*1|twice|2倍",
)
q("ppt", "missing", "What is the name of the individual on call for SEV-B at midnight?", {})


def jpg(category: str, text: str, evidence: str, *answer: str) -> None:
    q("jpg", category, text, {1: evidence.split(";")}, *answer)


jpg("workflow", "What comes immediately after Alert?", "Alert → Triage", "Triage")
jpg(
    "workflow",
    "按 Orion 流程，严重告警如何从判断走到关闭？",
    "Critical? → Page SRE [Yes];Page SRE → Mitigate;Mitigate → Close",
    "Page SRE",
    "Mitigate",
    "Close",
)
jpg(
    "workflow",
    "If the incident is not critical, what happens before Close?",
    "Critical? → Ticket [No];Ticket → Close",
    "Ticket",
)
jpg(
    "workflow",
    "Which two steps directly feed Close?",
    "Mitigate → Close;Ticket → Close",
    "Mitigate",
    "Ticket",
)
jpg(
    "architecture",
    "What sits between Portal and Router?",
    "Portal → Gateway;Gateway → Router",
    "Gateway",
)
jpg(
    "architecture",
    "Router 的两个直接下游是什么？",
    "Router → Cache;Router → Queue",
    "Cache",
    "Queue",
)
jpg(
    "architecture",
    "Trace the path from Router to Vault, listing intermediates in order.",
    "Router → Queue;Queue → Worker;Worker → Vault",
    "Queue",
    "Worker",
)
jpg("architecture", "What is Vault's immediate upstream component?", "Worker → Vault", "Worker")
jpg("organization", "Who reports directly to Maya?", "Maya → Iris;Maya → Noah", "Iris", "Noah")
jpg("organization", "QA 的直属负责人是谁？", "Iris → QA", "Iris")
jpg("organization", "Through whom does Maya oversee Data?", "Maya → Noah;Noah → Data", "Noah")
jpg("organization", "Which two teams sit under Iris?", "Iris → SRE;Iris → QA", "SRE", "QA")
jpg("table", "P1 的时限和负责人是谁？", "P1 | 15 | Iris", "15", "Iris")
jpg("table", "Which tier is Noah responsible for?", "P2 | 45 | Noah", "P2")
jpg("table", "What is the P3 limit in minutes?", "P3 | 120 | Maya", "120")
jpg(
    "table",
    "How many minutes longer is the P3 limit than the P1 limit?",
    "P3 | 120 | Maya;P1 | 15 | Iris",
    "105",
)
jpg("gantt", "Which project task is scheduled for W4 only?", "Launch | W4 | W4", "Launch")
jpg("gantt", "When does Build begin and end?", "Build | W2 | W3", "W2", "W3")
jpg("gantt", "Design 和 Build 共同进行的是哪一周？", "Design | W1 | W2;Build | W2 | W3", "W2")
jpg(
    "hierarchy",
    "What two categories fall directly under Readiness?",
    "Readiness → Security;Readiness → Reliability",
    "Security",
    "Reliability",
)
jpg(
    "hierarchy",
    "What is the path from Readiness to Rollback?",
    "Readiness → Reliability;Reliability → Rollback",
    "Readiness",
    "Reliability",
    "Rollback",
)
jpg("hierarchy", "Review 属于 Security 还是 Reliability？", "Security → Review", "Security")
jpg("bar", "What is the count of Orion tickets in February (Feb)?", "Feb | 60", "60")
jpg("bar", "Mar 的工单量占三个月总量的百分之几？", "Jan | 40;Feb | 60;Mar | 100", "50\\s*%|一半")
jpg(
    "bar",
    "What is the percentage increase in tickets from Jan to Feb?",
    "Jan | 40;Feb | 60",
    "50\\s*%",
)
jpg("bar", "What is the combined Jan and Mar ticket count?", "Jan | 40;Mar | 100", "140")
jpg("pie", "What proportion of Orion workload belongs to Data?", "Data | 30%", "30\\s*%")
jpg("pie", "Ops 与 QA 的工作量份额相差多少个百分点？", "Ops | 50%;QA | 20%", "30")
jpg("pie", "What share is assigned to Data and QA together?", "Data | 30%;QA | 20%", "50\\s*%|half")
jpg("pie", "Which team has the smallest workload share?", "Ops | 50%;Data | 30%;QA | 20%", "QA")
q("jpg", "missing", "Which calendar date does Orion's W1 begin?", {})


def pdf(category: str, n: int, text: str, evidence: str, *answer: str) -> None:
    q("pdf", category, text, {n: evidence.split(";")}, *answer)


pdf("continuation", 1, "How many workers are assigned to Cedar?", "Cedar | 12 | 420", "12")
pdf(
    "continuation",
    2,
    "Maple 的 worker 数和美元成本是多少？",
    "Region | Workers | Cost (USD);Maple | 24 | 840",
    "24",
    "840",
)
pdf(
    "continuation",
    2,
    "Which region on the second Harbor page costs 1050 USD?",
    "Region | Workers | Cost (USD);Ash | 30 | 1050",
    "Ash",
)
pdf(
    "continuation",
    3,
    "How many workers and how much USD are assigned to Birch?",
    "Region | Workers | Cost (USD);Birch | 42 | 1470",
    "42",
    "1,?470",
)
pdf(
    "continuation",
    3,
    "What are the original column labels for the Willow record?",
    "Region | Workers | Cost (USD);Willow | 36 | 1260",
    "Region",
    "Workers",
    "Cost",
    "USD",
)
q(
    "pdf",
    "continuation",
    "Across all three Harbor worker allocation pages, what is the total number of workers?",
    {
        1: ["Cedar | 12 | 420", "Juniper | 18 | 630"],
        2: ["Maple | 24 | 840", "Ash | 30 | 1050"],
        3: ["Willow | 36 | 1260", "Birch | 42 | 1470"],
    },
    "162",
)
q(
    "pdf",
    "continuation",
    "跨页比较，Birch 的成本比 Cedar 高多少美元？",
    {1: ["Cedar | 12 | 420"], 3: ["Birch | 42 | 1470"]},
    "1,?050",
)
q(
    "pdf",
    "continuation",
    "What is the combined USD cost for the six regions in Worker allocation by region?",
    {
        1: ["420", "630"],
        2: ["Region | Workers | Cost (USD)", "840", "1050"],
        3: ["Region | Workers | Cost (USD)", "1260", "1470"],
    },
    "5,?670",
)
pdf(
    "code",
    1,
    "What delay does harbor_retry return for HTTP 429 at attempt 8?",
    "def harbor_retry;        return min(64, 2 ** attempt)",
    "64",
)
q(
    "pdf",
    "code",
    "harbor_retry 对 429 的上限和 503 的重试条件分别是什么？",
    {
        1: ["return min(64, 2 ** attempt)"],
        2: ["    if status == 503 and attempt < 3:", "        return 5"],
    },
    "64",
    "503",
    "3",
    "5",
)
q(
    "pdf",
    "code",
    "For harbor_retry, compare the result for HTTP 503 at attempts 2 and 3.",
    {
        1: ["def harbor_retry"],
        2: ["    if status == 503 and attempt < 3:", "        return 5", "    return None"],
    },
    "5",
    "None",
)
q(
    "pdf",
    "code",
    "What does harbor_retry return for HTTP 500?",
    {1: ["def harbor_retry"], 2: ["    return None"]},
    "None",
)
pdf(
    "multi-table",
    4,
    "Who is the alert routing owner for Export?",
    "Alert routing;Export | Parker",
    "Parker",
)
pdf("multi-table", 4, "Export 的延迟上限是多少毫秒？", "Latency limits;Export | 300", "300")
pdf("multi-table", 4, "How many retry attempts does Ingest get?", "Retry budgets;Ingest | 4", "4")
pdf(
    "multi-table",
    4,
    "Ingest 的保留期比 Export 多几天？",
    "Retention windows;Ingest | 21;Export | 7",
    "14",
)
pdf(
    "multi-table",
    4,
    "For Export, provide alert owner, latency limit, and retry budget, in that order.",
    "Export | Parker;Export | 300;Export | 2",
    "Parker",
    "300",
    "2",
)
pdf("bar", 5, "How many incidents were resolved in May?", "May | 45", "45")
pdf(
    "bar",
    5,
    "What is June's share of all resolved incidents in the Harbor chart?",
    "April | 30;May | 45;June | 75",
    "50\\s*%|half",
)
pdf("bar", 5, "5 月到 6 月（May to June）结案数增加了多少？", "May | 45;June | 75", "30")
pdf("pie", 5, "What is Edge's share of team costs?", "Edge 28%", "28\\s*%")
pdf(
    "pie",
    5,
    "What is the ratio of Core's cost share to Edge's?",
    "Core 56%;Edge 28%",
    "2\\s*[:：]\\s*1|twice|2倍",
)
pdf("pie", 5, "QA 的成本份额比 Edge 少几个百分点？", "QA 16%;Edge 28%", "12")
q("pdf", "missing", "Who approved the Harbor rollout budget?", {})


def report(category: str, n: int, text: str, evidence: str, *answer: str) -> None:
    q("report", category, text, {n: evidence.split(";")}, *answer)


report(
    "chart",
    5,
    "艾瑞报告中 2026Q1 大中型企业的新一代 AI 采纳率是多少？",
    "2026Q1;81.3%;90.9%",
    "81.3%",
)
report(
    "chart", 5, "2026Q1 大中企业的整体 AI 采纳率比新一代 AI 高几个百分点？", "90.9%;81.3%", "9.6"
)
report(
    "chart",
    5,
    "第 5 页 L1 探索试验级中，新一代 AI 的企业占比是多少？",
    "L1：探索试验级;67.3%",
    "67.3%",
)
report("chart", 5, "2026Q1 新一代 AI 的 L1 与 L2 合计多少？", "67.3%;24.0%", "91.3%")
report(
    "footnote",
    8,
    "艾瑞 2025–2026 年中国企业级 AI Agent 成熟度和投资占比散点图覆盖多少家企业？",
    "= 300;免费产品不纳入统计",
    "300",
)
report(
    "risk",
    11,
    "企业须重视的 AI Agent 三重失控是什么？",
    "人对AI的失控;AI自身的失控;数据泄露失控",
    "人对AI",
    "AI自身",
    "数据泄露",
)
report(
    "risk",
    11,
    "在 AI 领先型企业中，关注数据泄露失控的占比比关注人对 AI 失控高多少？",
    "数据泄露失控”风险;93%;73%",
    "20",
)
report(
    "table",
    13,
    "2026 年 H1 AI Agent 厂商调研中，解决复杂业务和专业场景问题的能力受访者关注率是多少？",
    "83.7%;解决复杂业务和专业场景问题的能力",
    "83.7%",
)
report(
    "table",
    13,
    "第 13 页，业务领导者和技术领导者对关键产品能力指标的关注程度各是多少？",
    "关键产品能力指标",
    "3",
    "5",
)
report("chart", 20, "艾瑞预计 2027e 中国企业级智能体市场规模是多少亿元？", "2027e | 252.7", "252.7")
report(
    "chart",
    20,
    "报告第 20 页，2029e 企业级智能体市场规模比 2028e 增加多少亿元？",
    "2029e | 627.0;2028e | 430.9",
    "196.1",
)
report("chart", 20, "2025 至 2030 年企业级智能体市场规模 CAGR 是多少？", "70.9%;CAGR", "70.9%")
report(
    "chart",
    20,
    "2026e 智能体市场规模和同比增速分别是多少？",
    "2026e | 129.4;131.5%",
    "129.4",
    "131.5%",
)
report(
    "architecture",
    56,
    "南京大学的校园智能体通过什么方式接入哪些系统或端？",
    "通过接口;校园业务系统和网页端",
    "接口",
    "校园业务系统",
    "网页端",
)
report(
    "architecture",
    56,
    "南京大学的星辰校园平台有哪些开箱即用的内置 Agent？",
    "科研助手;SCI翻译助手;PPT大师;智能简历生成",
    "科研助手",
    "SCI翻译",
    "PPT大师",
    "简历",
)
report(
    "case",
    63,
    "铁小智案例中，厂商宣称的版式识别准确率和问答准确度各是多少？",
    "95.04%;93%",
    "95.04%",
    "93%",
)
report(
    "case",
    63,
    "铁小智案例的厂商介绍中，教育行业 AI 服务减少了多少咨询人工量？",
    "重复咨询人工量下;60%",
    "60%",
)
q("report", "missing", "艾瑞报告是否逐家披露了 300 家受访企业的名称？", {})
