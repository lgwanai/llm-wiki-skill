#!/usr/bin/env python3
"""compile_v2.py — Simplified wiki compilation.
...
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from _llm_utils import call_llm, get_chunk_threshold, llm_fuse_pages
from config import (
    get_config,
    get_image_analysis_config,
    get_ocr_config,
    get_vision_skill_config,
    get_wiki_dir,
)
from table_extract import persist_page_tables


def _log_exc(msg: str = ""):
    """Log exception traceback to stderr for debugging."""
    import traceback as _tb
    if msg:
        print(f"  [WARN] {msg}: {_tb.format_exc()}", file=sys.stderr)
    else:
        print(f"  [WARN] {_tb.format_exc()}", file=sys.stderr)



SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r'(?:sk|pk|rk)-(?:[a-zA-Z0-9]{20,})', '[REDACTED: API key]'),
    (r'(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}', '[REDACTED: GitHub token]'),
    (r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     '[REDACTED: Private key]'),
    (r'password\s*[=:]\s*\S+', 'password=[REDACTED]'),
    (r'[\w\.-]+@[\w\.-]+\.\w{2,}', '[REDACTED: Email]'),
]

KEYWORD_RELATION_MAP = [
    # English patterns
    (r'(?i)\buses?\b\s*\[\[', 'uses'),
    (r'(?i)\bdepends?\s+on\b.*?\[\[', 'depends_on'),
    (r'(?i)\bextends?\b\s*\[\[', 'extends'),
    (r'(?i)\bimproves?\s+(?:upon|over)?\s*\[\[', 'improves_upon'),
    (r'(?i)\bcontradicts?\b\s*\[\[', 'contradicts'),
    (r'(?i)\bsupersedes?\b\s*\[\[', 'supersedes'),
    (r'(?i)\bcaused?\s+by\b.*?\[\[', 'caused_by'),
    (r'(?i)\bfixed?\s+by\b.*?\[\[', 'fixed_by'),
    (r'(?i)\breplaces?\b\s*\[\[', 'replaces'),
    (r'(?i)\brelated\s+to\b.*?\[\[', 'relates_to'),
    (r'(?i)\bpart\s+of\b.*?\[\[', 'part_of'),
    (r'(?i)\bimplemented\s+(?:by|via)\b.*?\[\[', 'implemented_by'),
    # Chinese patterns
    (r'(?:使用|采用|利用|调用|借助|依据|通过)\s*\[\[', 'uses'),
    (r'(?:依赖|取决于|依赖于)\s*\[\[', 'depends_on'),
    (r'(?:扩展|继承|基于\s*)\s*\[\[', 'extends'),
    (r'(?:改进|优化|提升|增强)\s*\[\[', 'improves_upon'),
    (r'(?:矛盾|冲突|不一致|违背)\s*\[\[', 'contradicts'),
    (r'(?:取代|替代|替换\s*掉|淘汰)\s*\[\[', 'supersedes'),
    (r'(?:导致|引起|造成|触发|引发)\s*\[\[', 'caused_by'),
    (r'(?:修复|解决|修正|纠正)\s*\[\[', 'fixed_by'),
    (r'(?:替换|更换|换成|切换)\s*\[\[', 'replaces'),
    (r'(?:关联|相关|有关|涉及|对接|协作|配合|协调)\s*\[\[', 'relates_to'),
    (r'(?:属于|组成部分|包含于|隶属于)\s*\[\[', 'part_of'),
    (r'(?:实现|实施|执行|落实|负责|承担|主持)\s*\[\[', 'implemented_by'),
]

TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".svg",  # SVG is XML text, not pixel data
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb",
    ".sh", ".bash", ".zsh", ".sql", ".toml", ".ini", ".cfg",
}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".tiff", ".tif", ".avif", ".heic", ".heif",
}
PAGINATED_DOCUMENT_EXTENSIONS = {".pdf", ".ppt", ".pptx"}
MARKITDOWN_DOCUMENT_EXTENSIONS = {
    ".doc", ".docx", ".xls", ".xlsx", ".rtf", ".epub", ".msg",
}
DOCUMENT_EXTENSIONS = PAGINATED_DOCUMENT_EXTENSIONS | MARKITDOWN_DOCUMENT_EXTENSIONS
SKIP_DIR_NAMES = {".wiki", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
DEFAULT_ENTITY_TYPES = [
    "entity", "concept", "process", "rule", "role", "event",
    "model", "technique", "framework", "benchmark", "paper",
]
DEFAULT_RELATIONSHIP_TYPES = [
    "uses", "depends_on", "extends", "improves_upon", "contradicts",
    "supersedes", "caused_by", "fixed_by", "replaces", "relates_to",
    "part_of", "implemented_by",
]
CONCEPT_LIKE_TYPES = {"concept", "technique", "model", "framework", "benchmark", "paper", "pattern"}
INGEST_RULES = {
    "doc": (
        ["entity", "concept", "process", "rule", "role", "event"],
        "core concepts, named entities, processes, roles, rules, and events",
    ),
    "article": (
        ["concept", "entity", "model", "technique", "benchmark", "paper"],
        "claims, concepts, models, techniques, benchmarks, and cited work",
    ),
    "code": (
        ["entity", "concept", "framework", "tool", "file", "library", "decision"],
        "source files, libraries, tools, architectural decisions, and implementation patterns",
    ),
    "conversation": (
        ["decision", "concept", "entity", "process", "rule"],
        "decisions, findings, open questions, rules, and follow-up actions",
    ),
}

DOMAIN_EXPERTS = {
    "legal": {
        "label": "法律法规与合规专家",
        "signals": ("法律", "法规", "条例", "办法", "规定", "法条", "本法", "应当", "不得", "处罚", "管辖", "生效", "废止"),
        "instructions": "按法律层级、章/节/条保留原编号与原文；拆出适用主体、地域、事项、条件、例外、程序、期限、法律后果、引用法条、生效/修订/废止状态。不得把‘可以/应当/不得’互换，不得把例外并入一般规则。优先形成法条导航页、制度主题页和交叉引用。",
    },
    "policy": {
        "label": "销售营销政策与商业运营专家",
        "signals": ("销售", "营销", "促销", "返利", "折扣", "渠道", "经销商", "客户", "区域", "政策期", "活动期", "适用范围", "考核"),
        "instructions": "围绕谁在何地、何时、对什么产品/渠道/客户、满足何条件、可获何权益、由谁审批、如何核算与结算来组织；完整保留地区、主体、产品、渠道、时间窗、门槛、梯度、互斥/叠加、例外、审批、凭证和失效条件。用适用性矩阵与计算示例连接规则，禁止脱离限定条件摘录金额或比例。",
    },
    "academic": {
        "label": "学术研究与科学知识专家",
        "signals": ("摘要", "研究", "论文", "方法", "实验", "假设", "定理", "证明", "公式", "变量", "数据集", "基线", "显著", "结论", "参考文献"),
        "instructions": "区分定义、假设、命题、公式、推导、方法、实验设计、结果、限制与结论；逐字保留公式、符号、变量含义、单位和适用条件。建立概念依赖、推导链、因果/相关边界、方法到证据的逻辑链，并保留引用与页码/章节定位。不得把作者主张写成公认事实。",
    },
    "curriculum": {
        "label": "培训信息架构与课程设计专家",
        "signals": ("课程大纲", "培训", "学员", "教学目标", "学习目标", "课时", "讲师", "模块", "单元", "练习", "作业", "考核", "教学活动"),
        "instructions": "以便于后续组课为目标，区分课程定位、受众画像、先修要求、可观察学习目标、模块/知识点层级、概念依赖、难点误区、案例练习、教学活动、课时、资料与评估方式。保持原大纲顺序，同时建立知识点到目标、练习、考核的映射；不要把课程章节机械地等同于知识点。",
    },
    "finance": {
        "label": "财务会计与经营分析专家",
        "signals": ("财务", "会计", "资产负债表", "利润表", "现金流", "收入确认", "成本", "预算", "税务", "凭证", "科目", "毛利", "净利润"),
        "instructions": "区分会计口径、管理口径和税务口径；保留币种、期间、主体、科目、借贷方向、确认条件、计算公式、数据来源与勾稽关系。组织报表项目、核算政策、预算差异、指标树和风险事项，任何金额或比率不得脱离期间与口径。",
    },
    "operations": {
        "label": "业务运营与流程管理专家",
        "signals": ("运营", "SOP", "流程", "工单", "排班", "履约", "转化率", "留存率", "服务水平", "周转", "产能", "异常处理"),
        "instructions": "按目标、输入、角色、步骤、决策点、SLA、产能、指标、异常、升级与复盘组织；还原端到端流程及责任边界，建立指标口径、上下游依赖和异常闭环。区分标准路径、例外路径与人工判断点。",
    },
    "product": {
        "label": "产品管理与用户体验专家",
        "signals": ("产品需求", "PRD", "用户故事", "用户旅程", "功能", "版本", "验收标准", "优先级", "原型", "痛点", "场景", "需求池"),
        "instructions": "围绕用户、场景、问题、价值、需求、功能、规则、交互、状态、边界、依赖、埋点、指标与验收标准组织；区分用户事实、产品假设和已确认决策，建立需求到方案、版本和验证证据的追踪链。",
    },
    "engineering": {
        "label": "软件工程与系统架构专家",
        "signals": ("架构", "接口", "API", "数据库", "服务", "部署", "代码", "算法", "协议", "依赖", "故障", "性能", "安全漏洞"),
        "instructions": "保留组件职责、接口契约、数据模型、控制流/数据流、依赖、配置、版本、环境、性能约束、安全边界、故障模式和运维步骤；把设计决策与实现事实分开，并链接需求、代码位置、测试和已知限制。",
    },
    "project": {
        "label": "项目与项目群管理专家",
        "signals": ("项目计划", "里程碑", "WBS", "交付物", "关键路径", "进度", "项目风险", "干系人", "资源计划", "变更请求"),
        "instructions": "按目标、范围、交付物、工作分解、负责人、时间、依赖、里程碑、资源、风险、问题、决策和变更组织；保留计划基线与实际状态的区别，建立需求—任务—交付—验收的追踪关系。",
    },
    "hr": {
        "label": "人力资源与组织发展专家",
        "signals": ("招聘", "岗位职责", "任职资格", "绩效", "薪酬", "员工", "职级", "晋升", "人才盘点", "组织架构", "劳动合同", "离职"),
        "instructions": "围绕适用员工、组织层级、岗位、职级、能力、流程、周期、评价标准、薪酬口径、审批和员工影响组织；区分制度、流程与个案，保留劳动关系地域、时间和例外条件，避免推断敏感个人信息。",
    },
    "supply_chain": {
        "label": "采购、供应链与物流专家",
        "signals": ("采购", "供应商", "招标", "库存", "仓储", "物流", "交期", "订单", "补货", "安全库存", "运输", "供应链"),
        "instructions": "按需求、寻源、供应商、合同、订单、库存、仓储、运输、交付、结算和绩效组织；保留物料/服务范围、数量、单位、价格口径、交期、Incoterms、质检、风险和异常责任，建立端到端流转与单据关系。",
    },
    "manufacturing": {
        "label": "制造工程与质量管理专家",
        "signals": ("生产", "工艺", "BOM", "产线", "设备", "良率", "质量", "检验", "缺陷", "批次", "作业指导书", "追溯"),
        "instructions": "保留产品/物料版本、BOM、工序、工艺参数、设备、批次、检验标准、抽样规则、缺陷等级、良率、控制计划和追溯链；区分规范值、实测值和处置结论，串联变更、偏差、根因与纠正预防措施。",
    },
    "risk_audit": {
        "label": "风险管理、内控与审计专家",
        "signals": ("风险", "内控", "审计", "控制点", "合规检查", "整改", "证据", "抽样", "风险等级", "控制测试", "缺陷认定"),
        "instructions": "按目标、风险、控制、责任人、频率、证据、测试方法、发现、影响、根因、整改和复核组织；区分固有风险与剩余风险、设计有效性与执行有效性，不把建议写成已执行事实。",
    },
    "healthcare": {
        "label": "医疗健康与临床信息专家",
        "signals": ("患者", "诊断", "治疗", "药物", "剂量", "临床", "指南", "适应症", "禁忌症", "不良反应", "检验", "预后"),
        "instructions": "区分指南建议、研究证据与个案信息；完整保留人群、适应症、禁忌症、剂量、途径、频次、疗程、检查指标、证据等级和不良反应。建立症状—诊断—检查—治疗—随访逻辑，并明确来源版本与适用边界，不生成原文没有的医疗建议。",
    },
    "education": {
        "label": "教育教学与学习科学专家",
        "signals": ("教学", "学生", "学习成果", "课程标准", "教案", "课堂", "评价量规", "学科", "作业", "测验", "教学策略"),
        "instructions": "围绕学习者、目标、先备知识、核心概念、学习进阶、教学活动、资源、形成性评价和总结性评价组织；保留学段、学科、课时与评价标准，建立目标—教学—评价一致性和概念先后依赖。",
    },
    "customer_service": {
        "label": "客户服务与体验运营专家",
        "signals": ("客服", "客诉", "投诉", "咨询", "服务话术", "满意度", "响应时长", "升级", "退换货", "服务工单", "客户体验"),
        "instructions": "按客户类型、场景、意图、问题分类、诊断步骤、话术边界、解决方案、权限、SLA、升级、补偿和闭环组织；区分事实核验、标准答复与酌情处理，保留渠道、地区、产品和时间限制。",
    },
    "strategy": {
        "label": "企业战略与商业分析专家",
        "signals": ("战略", "商业模式", "市场规模", "竞争格局", "增长", "战略目标", "核心能力", "进入壁垒", "SWOT", "情景分析"),
        "instructions": "区分事实、假设、判断与决策；按外部环境、市场、客户、竞争、能力、选择、目标、举措、资源、指标和情景组织，建立证据—洞察—选择—行动链，并保留预测口径、时间范围与不确定性。",
    },
    "data": {
        "label": "数据分析与指标治理专家",
        "signals": ("数据分析", "指标", "口径", "维度", "数据源", "SQL", "仪表盘", "样本", "统计", "归因", "漏斗", "数据质量"),
        "instructions": "保留指标定义、公式、分子分母、单位、粒度、维度、过滤条件、时间窗、数据源、刷新频率和负责人；区分描述、相关、因果与预测结论，记录样本、缺失、偏差和数据质量限制，建立指标血缘与业务解释。",
    },
}


def match_domain_experts(content: str, source_name: str = "") -> list[dict[str, str]]:
    """Select one or more domain lenses from evidence in the document itself."""
    sample = f"{source_name}\n{content[:120_000]}".lower()
    ranked: list[tuple[int, str]] = []
    for key, profile in DOMAIN_EXPERTS.items():
        score = sum(sample.count(signal.lower()) for signal in profile["signals"])
        if score:
            ranked.append((score, key))
    ranked.sort(reverse=True)
    if not ranked:
        return []
    best = ranked[0][0]
    # Multi-label routing handles mixed documents; weak incidental matches are excluded.
    selected = [key for score, key in ranked if score >= max(2, best // 3)][:3]
    return [{"id": key, **DOMAIN_EXPERTS[key]} for key in selected]


def build_domain_expert_guidance(content: str, source_name: str = "") -> str:
    experts = match_domain_experts(content, source_name)
    if experts:
        routes = "\n".join(
            f"- **{item['label']}**：{item['instructions']}" for item in experts
        )
    else:
        routes = "- **通用知识架构专家**：先识别文档真实用途、读者任务和内在结构，再决定页面粒度；不得套用固定页数、固定实体比例或固定拆分模板。"
    return f"""## 领域专家路由（基于内容动态选择）
{routes}

先通读并判断文档体裁、权威性、目标读者与后续查询任务，再选择拆解粒度。允许多个专家视角协同，也允许发现更准确的领域后自行调整。章节只是证据边界，不必一章一页；页面数量、事实条数和实体/概念比例均由内容决定。若后续通用模板出现“固定页数”“每页固定事实数”或“固定实体/概念比例”，本节优先，忽略这些配额。所有解释性归纳须与原文明确区分，并附可回溯的原文定位。"""

IMAGE_ANALYSIS_PROMPT = """Analyze this image for knowledge-base ingestion and retrieval.

Return clean markdown in Chinese when the image contains Chinese; otherwise use the image's main language.

## Required Sections (all images):

### 1. Image Type & Summary
- What type of image is this? (mind map / flowchart / architecture diagram / chart / table / document screenshot / photo / other)
- One-sentence summary of what this image communicates.
- Who is the likely audience? (engineers / managers / general / academic)

### 2. Content Extraction
- Preserve ALL visible text, labels, headings, legends, axes, units, numbers, tables, and annotations verbatim.

**★ Flowcharts & Process Diagrams (highest priority — default assumption for diagrams):**
Flowcharts encode logic through ARROWS — the direction IS the meaning. Missing an arrow = losing the entire logic chain.

Required output for any flowchart/process diagram:
1. **Start point**: where does the flow begin? (labeled node, or visually prominent entry)
2. **Step-by-step sequence**: number each step in execution order (Step 1 → Step 2 → ...). For each step:
   - Node text (verbatim)
   - Node shape if meaningful (rectangle=process, diamond=decision, oval=start/end, cylinder=data)
   - What arrow(s) come OUT of this node, and where they point
3. **Decision nodes** (diamonds): for EACH branch, state:
   - The condition written on the branch arrow (e.g., "Yes", "No", "> 1000", "审批通过")
   - Which node each branch leads to
   - If a branch loops back, state clearly: "↩ loops back to Step N"
4. **Parallel/concurrent flows**: if multiple paths run simultaneously, group them and state they are parallel
5. **End point(s)**: where does the flow terminate? Are there multiple end states?
6. **Logical summary**: after reconstructing all steps, write a 3-5 sentence summary of the overall logic:
   "This flowchart describes [process]. It starts at [X], then [key decision/action], and ends at [Y]. The critical path is [most important branch sequence]."

**Arrow direction conventions to watch for:**
- ↓ downward arrow: sequential next step
- → right arrow: forward progression / positive branch
- ← left arrow: loop back / return to previous step
- ↑ upward arrow: escalation / return to parent
- Diamond → two+ arrows: decision branch (ALWAYS capture both/all branches)
- Dashed arrow: optional / async / message passing
- Thick/bold arrow: main flow / primary path

- If it is a mind map: restore the full hierarchy as nested bullet lists.
- If it is an architecture diagram: identify layers, components, data flow direction, and protocols between components.
- If it is a chart: restore chart type, data series, axis labels with units, numeric values, and visible trends.
- If it is a document screenshot: extract text faithfully with section structure.
- If it contains a table: reproduce the table in markdown table format with all rows and columns.

**★ Data fidelity (non-negotiable):** Every number, date, amount, percentage,
threshold, unit, and name must be copied **exactly as shown** — no rounding, no
unit conversion, no merging/dropping/reordering of table cells, and never
infer or fabricate a value that is not clearly visible. If a value is unclear,
mark it `[unclear]` rather than guessing.

### 3. Visual Properties
- Color scheme (dominant colors, color coding if meaningful)
- Layout style (top-down / left-to-right / radial / grid / freeform)
- Approximate element count (nodes, branches, cells, data points)
- Any visual emphasis (highlighted elements, callouts, annotations)
- Background: solid / transparent / gradient / image

### 4. Key Entities
- List named entities visible in the image (people, organizations, projects, systems, metrics, dates).
- These will be used for knowledge graph linking.

Avoid generic descriptions like "this is an image of a diagram" — be specific about what the image contains and how it's organized.
"""


def strip_sensitive(content: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def is_text_source(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def is_image_source(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_paginated_document_source(path: Path) -> bool:
    return path.suffix.lower() in PAGINATED_DOCUMENT_EXTENSIONS


def is_document_source(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


def is_supported_source(path: Path) -> bool:
    return path.is_file() and (
        is_text_source(path) or is_image_source(path) or is_document_source(path)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _readonly_working_copy(source_path: Path):
    """Yield a temporary copy so external readers never touch the source file."""
    source_path = source_path.resolve()
    original_stat = source_path.stat()
    original_hash = _file_sha256(source_path)

    with tempfile.TemporaryDirectory(prefix="llm-wiki-source-") as tmpdir:
        work_path = Path(tmpdir) / source_path.name
        shutil.copy2(source_path, work_path)
        work_path.chmod(0o400)
        yield work_path

    after_stat = source_path.stat()
    if (
        after_stat.st_size != original_stat.st_size
        or _file_sha256(source_path) != original_hash
    ):
        raise RuntimeError(
            f"Source file changed during read-only processing: {source_path}"
        )


def iter_source_files(root: Path, max_depth: int | None = None) -> list[Path]:
    """Return supported source files under root, sorted for deterministic compiles.

    max_depth counts directory levels below root:
    - 0: only files directly under root
    - 1: include root's direct child directories
    - None: recurse through all subdirectories
    """
    files: list[Path] = []

    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        rel_parts = current_path.relative_to(root).parts
        depth = len(rel_parts)

        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIR_NAMES and not (current_path / d).is_symlink()
        )

        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []

        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                continue
            if is_supported_source(path):
                files.append(path)

    return files


def _ocr_image_with_config(image_path: Path) -> str:
    """Run the configured OCR backend on an image and return markdown text."""
    ocr_config = get_ocr_config()
    backend = ocr_config.get("backend", "mineru")

    if ocr_config.get("mode") == "api" or backend == "api":
        from ocr._ocr_api import OCRApiBackend
        return OCRApiBackend.from_config().ocr_image(str(image_path))
    if backend == "deepseek":
        from ocr._deepseek_ocr2 import DeepSeekOCR2
        return DeepSeekOCR2.from_config().ocr_image(str(image_path))
    if backend == "logics":
        from ocr._logics_parsing import LogicsParsingOCR
        return LogicsParsingOCR.from_config().ocr_image(str(image_path))
    if backend == "paddle":
        from ocr._paddle_ocr import PaddleOCRWrapper
        return PaddleOCRWrapper.from_config().ocr_image(str(image_path))
    from ocr._mineru_ocr import MinerUOCR
    return MinerUOCR.from_config().ocr_image(str(image_path))


def _copy_to_source_images(image_path: Path) -> Path:
    """Copy image to .wiki/source/images/ for persistent storage.

    Images referenced by original path will break if the file moves.
    Copying to the wiki ensures the image is always available.
    Preserves original filename; appends a short hash if collision.
    """
    SOURCE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCE_IMAGES_DIR / image_path.name
    if dest.exists():
        # Avoid collision: append short hash of original path
        import hashlib
        path_hash = hashlib.md5(str(image_path.resolve()).encode()).hexdigest()[:6]
        stem, ext = image_path.stem, image_path.suffix
        dest = SOURCE_IMAGES_DIR / f"{stem}-{path_hash}{ext}"
    import shutil
    shutil.copy2(image_path, dest)
    return dest


def analyze_image_for_compile(image_path: Path, for_agent: bool = False) -> str:
    """Convert an image source to markdown for wiki compilation.

    Image recognition precedence:
      1. vision-skill (Agent-side, preferred) — declared dependency, used in
         agent mode when the Agent has the skill available.
      2. OCR — configured OCR backend (Python-side fallback).
      3. Agent's own image-parsing capability — last resort.

    In agent mode (``for_agent=True``, the default compile mode), emit a
    precedence instruction for the Agent and pre-extract OCR text as a
    fallback. The ``image_analysis`` vision API is NOT used here — it is
    reserved for ``--mode llm`` where no Agent is in the loop to invoke a
    skill.

    In llm mode (``for_agent=False``), use the configured ``image_analysis``
    vision API first, then OCR, then hand the image to the model as a last
    resort.
    """
    # ── Step 1: Copy to persistent storage ──
    try:
        stored_path = _copy_to_source_images(image_path)
    except Exception as e:
        stored_path = image_path
        print(f"  WARNING: could not copy image to source/images: {e}", file=sys.stderr)

    if for_agent:
        return _build_agent_image_task(image_path, stored_path)
    return _build_llm_image_task(image_path, stored_path)


def _image_source_header(image_path: Path, stored_path: Path) -> list[str]:
    """Shared markdown header for an image source."""
    return [
        f"# Image Source: {image_path.name}",
        "",
        f"> **Original**: `{image_path.resolve()}`",
        f"> **Stored at**: `{stored_path.resolve()}`",
        f"> **Format**: {image_path.suffix.upper().lstrip('.')}",
        f"> **Size**: {image_path.stat().st_size // 1024} KB",
        "",
    ]


def _build_llm_image_task(image_path: Path, stored_path: Path) -> str:
    """llm-mode image task: vision API → OCR → model handoff.

    Used by ``--mode llm`` where no Agent is in the loop to invoke a skill,
    so the configured ``image_analysis`` vision API is the primary path.
    """
    image_config = get_image_analysis_config()
    analysis = ""
    ocr_text = ""

    # ── Vision model analysis (Python-side) ──
    vision_enabled = bool(image_config.get("enabled"))
    if vision_enabled:
        try:
            analysis = _analyze_page_image_with_vision(image_path)
        except Exception as e:
            print(f"  WARNING: image analysis failed for {image_path}: {e}", file=sys.stderr)

    # ── OCR only as fallback (vision already extracts text) ──
    if not vision_enabled or not analysis:
        should_ocr = bool(image_config.get("ocr_fallback", True))
        if should_ocr:
            try:
                ocr_text = _ocr_image_with_config(image_path)
            except Exception as e:
                print(f"  WARNING: OCR fallback failed for {image_path}: {e}", file=sys.stderr)

    sections = _image_source_header(image_path, stored_path)

    if analysis:
        sections.extend(["## Visual Analysis", "", analysis.strip(), ""])
    if ocr_text and ocr_text.strip() != analysis.strip():
        sections.extend(["## OCR Text (fallback)", "", ocr_text.strip(), ""])

    # ── Last resort: hand the image to the consuming model ──
    if not analysis and not ocr_text:
        sections.extend(
            [
                "## Image Recognition Required",
                "",
                "No vision model or OCR backend is configured, so this image was not "
                "processed automatically. If the consuming model is multimodal, read the "
                "image below and compile its visible content; otherwise ask the user for a "
                "text export or summary.",
                "",
                f"![{image_path.stem}]({stored_path.resolve()})",
                "",
            ]
        )

    return "\n".join(sections).strip() + "\n"


def _build_agent_image_task(image_path: Path, stored_path: Path) -> str:
    """Agent-mode image task: vision-skill → OCR → Agent's own capability.

    The vision-skill is the declared dependency for image sources and the
    preferred recognition path. OCR is pre-extracted by Python as a fallback
    (the Agent cannot run OCR backends itself). The Agent's native
    image-parsing capability is the last resort.
    """
    vision_config = get_vision_skill_config()
    vision_enabled = bool(vision_config.get("enabled"))

    # Pre-extract OCR fallback only when a backend is usable, to avoid
    # warning noise when the user relies solely on the vision-skill.
    ocr_text = ""
    if _ocr_backend_available():
        try:
            ocr_text = _ocr_image_with_config(image_path)
        except Exception as e:
            print(f"  WARNING: OCR fallback failed for {image_path}: {e}", file=sys.stderr)

    sections = _image_source_header(image_path, stored_path)
    sections.extend(
        [
            "## Image Recognition",
            "",
            "**Precedence: vision-skill → OCR → your own capability.**",
            "",
        ]
    )

    tier = 1
    if vision_enabled:
        sections.extend(
            [
                f"{tier}. **vision-skill (preferred)** — This skill depends on the "
                "`vision-skill` skill. If it is available in this environment, use it to "
                "analyze the image and compile its visible content (text, structure, "
                "diagrams, charts, tables) into the wiki page.",
                "",
            ]
        )
        scripts_path = vision_config.get("scripts_path", "")
        fmt = vision_config.get("recognize_format", "markdown_note")
        if scripts_path:
            cli = Path(os.path.expanduser(str(scripts_path))) / "vision_cli.py"
            sections.extend(
                [
                    "   Invoke the skill directly, or run its CLI for structured markdown:",
                    "",
                    "   ```bash",
                    f"   python3 {cli} recognize \\",
                    f'     "{stored_path.resolve()}" --format {fmt} --wait',
                    "   ```",
                    "",
                ]
            )
        tier += 1

    sections.extend(
        [
            f"{tier}. **OCR fallback** — If the vision-skill is unavailable, use the OCR "
            "text below (pre-extracted by the configured OCR backend).",
            "",
        ]
    )
    tier += 1
    sections.extend(
        [
            f"{tier}. **Native capability** — If OCR is also unavailable, read the image "
            "directly with your own image-parsing capability.",
            "",
            f"![{image_path.stem}]({stored_path.resolve()})",
            "",
        ]
    )

    if ocr_text:
        sections.extend(["### OCR Text (fallback)", "", ocr_text.strip(), ""])
    else:
        sections.extend(
            [
                "### OCR Text (fallback)",
                "",
                "[No OCR backend configured — vision-skill or your own capability is required.]",
                "",
            ]
        )

    return "\n".join(sections).strip() + "\n"


def _document_images_dir(source_path: Path) -> Path:
    """Return stable storage for rendered document page images."""
    import hashlib

    # Non-cryptographic: only used to disambiguate filesystem directory names.
    source_hash = hashlib.md5(str(source_path.resolve()).encode()).hexdigest()[:8]
    safe_stem = re.sub(r"[^a-zA-Z0-9_.-]+", "-", source_path.stem).strip("-") or "document"
    return WIKI_DIR / "source" / "document_images" / f"{safe_stem}-{source_hash}"


def _clear_rendered_pages(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("page-*.png"):
        existing.unlink()


def _render_pdf_pages_to_images(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Render every PDF page to PNG files and return them in page order."""
    _clear_rendered_pages(output_dir)
    dpi = int(get_ocr_config().get("pdf_dpi", 150) or 150)

    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        images: list[Path] = []
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(doc.page_count):
            pix = doc.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"page-{page_index + 1:03d}.png"
            pix.save(str(image_path))
            images.append(image_path)
        doc.close()
        return images
    except Exception as fitz_error:
        try:
            from pdf2image import convert_from_path

            pages = convert_from_path(str(pdf_path), dpi=dpi)
            images = []
            for page_index, page in enumerate(pages, start=1):
                image_path = output_dir / f"page-{page_index:03d}.png"
                page.save(str(image_path), "PNG")
                images.append(image_path)
            return images
        except Exception as pdf2image_error:
            raise RuntimeError(
                "Could not render PDF pages with PyMuPDF or pdf2image: "
                f"{fitz_error}; {pdf2image_error}"
            ) from pdf2image_error


def _convert_office_to_pdf(source_path: Path, output_dir: Path) -> Path:
    """Convert PPT/PPTX and other Office files to PDF using LibreOffice."""
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise RuntimeError("LibreOffice/soffice is not installed; cannot render slides to images.")

    output_dir.mkdir(parents=True, exist_ok=True)
    before = set(output_dir.glob("*.pdf"))
    cmd = [
        converter,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    after = set(output_dir.glob("*.pdf"))
    candidates = sorted(after - before) or sorted(output_dir.glob(f"{source_path.stem}*.pdf"))
    if result.returncode != 0 or not candidates:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"LibreOffice conversion failed: {message}")
    return candidates[0]


def _render_paginated_document_to_images(
    source_path: Path,
    storage_source_path: Path | None = None,
) -> tuple[list[Path], str]:
    """Render all pages/slides from a PDF/PPT/PPTX source into images."""
    output_dir = _document_images_dir(storage_source_path or source_path)
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf_pages_to_images(source_path, output_dir), "pdf-pages"
    if suffix in {".ppt", ".pptx"}:
        pdf_path = _convert_office_to_pdf(source_path, output_dir)
        return _render_pdf_pages_to_images(pdf_path, output_dir), "slides-via-pdf"
    raise RuntimeError(f"Unsupported paginated document type: {suffix}")


def _ocr_backend_available() -> bool:
    """Return whether a configured OCR backend appears usable.

    Mirrors the fallback logic in ocr._ocr_api.create_vision_backend so that
    env-var keys and provider-preset models are recognised.
    """
    ocr_config = get_ocr_config()
    backend = ocr_config.get("backend", "mineru")

    if ocr_config.get("mode") == "api" or backend == "api":
        provider = ocr_config.get("api_provider", "") or ocr_config.get("provider", "")
        provider_presets: dict[str, dict[str, str]] = {}
        if provider:
            from ocr._ocr_api import _PROVIDER_PRESETS
            provider_presets = _PROVIDER_PRESETS

        # Resolve api_url (config or provider preset)
        if ocr_config.get("api_url"):
            api_url_ok = True
        elif provider:
            api_url_ok = bool(provider_presets.get(provider, {}).get("api_url"))
        else:
            api_url_ok = False

        # Resolve api_key (config or environment variables)
        api_key_ok = bool(
            ocr_config.get("api_key")
            or os.environ.get("OCR_API_KEY")
            or os.environ.get("SILICONFLOW_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )

        # Resolve api_model (config or provider preset)
        if ocr_config.get("api_model") or ocr_config.get("model"):
            api_model_ok = True
        elif provider:
            api_model_ok = bool(provider_presets.get(provider, {}).get("default_model"))
        else:
            api_model_ok = False

        return api_url_ok and api_key_ok and api_model_ok

    try:
        if backend == "deepseek":
            import ocr._deepseek_ocr2  # noqa: F401
        elif backend == "logics":
            import ocr._logics_parsing  # noqa: F401
        elif backend == "paddle":
            import ocr._paddle_ocr  # noqa: F401
        else:
            import ocr._mineru_ocr  # noqa: F401
        return True
    except Exception:
        return False


def _image_analysis_available() -> bool:
    image_config = get_image_analysis_config()
    return bool(image_config.get("enabled"))


def _analyze_page_image_with_vision(image_path: Path, backend: object | None = None) -> str:
    """Analyze a single page image with a vision backend.

    Args:
        image_path: Path to the rendered page image.
        backend: Optional pre-created vision backend.  When omitted a new
            backend is created (convenient for single-image callers).
    """
    if backend is not None:
        return backend.ocr_image(str(image_path))

    image_config = get_image_analysis_config()
    from ocr._ocr_api import create_vision_backend

    backend = create_vision_backend(image_config, IMAGE_ANALYSIS_PROMPT)
    return backend.ocr_image(str(image_path))


def _rendered_page_markdown(image_path: Path, page_number: int, body: str, label: str) -> list[str]:
    return [
        f"## Page {page_number}",
        "",
        f"![{label} {page_number}]({image_path.resolve()})",
        "",
        body.strip() if body.strip() else "[No text extracted from this page.]",
        "",
    ]


def _read_paginated_document_for_compile(source_path: Path) -> str:
    """Read a PDF/PPT/PPTX with page-preserving fallbacks.

    Priority:
    1. Render every page/slide to images, then OCR each image when OCR is usable.
    2. If OCR is unavailable, use configured vision/image analysis per page.
    3. If neither exists, preserve all rendered images and hand the page list to the Agent.

    No page may disappear silently: every rendered page gets a heading, image link, and
    either extracted text or an explicit Agent instruction.
    """
    sections = [
        f"# Document Source: {source_path.name}",
        "",
        f"> **Original**: `{source_path.resolve()}`",
        f"> **Format**: {source_path.suffix.upper().lstrip('.')}",
        f"> **Size**: {source_path.stat().st_size // 1024} KB",
        "> **Page guarantee**: every rendered page/slide is listed below.",
        "",
    ]

    try:
        with _readonly_working_copy(source_path) as work_path:
            page_images, pipeline = _render_paginated_document_to_images(
                work_path,
                storage_source_path=source_path,
            )
    except Exception as render_error:
        markitdown_text = _markitdown_to_markdown(source_path)
        sections.extend(
            [
                "## Rendering Failed",
                "",
                f"Could not render pages/slides to images: {render_error}",
                "",
            ]
        )
        if markitdown_text:
            sections.extend(
                [
                    "## MarkItDown Fallback",
                    "",
                    markitdown_text.strip(),
                    "",
                    "> Agent must verify whether this fallback contains every page/slide. "
                    "If not, ask the user for a page-rendered export.",
                    "",
                ]
            )
        else:
            sections.extend(
                [
                    "## Agent Action Required",
                    "",
                    "No page images could be rendered and MarkItDown did not return content. "
                    "The Agent must inspect the original file directly; if it cannot, ask the user "
                    "for a PDF/image export with every page or slide.",
                    "",
                ]
            )
        return "\n".join(sections).strip() + "\n"

    sections.extend(
        [
            f"> **Render pipeline**: `{pipeline}`",
            f"> **Pages/slides rendered**: {len(page_images)}",
            f"> **Rendered images dir**: `{_document_images_dir(source_path).resolve()}`",
            "",
        ]
    )

    if not page_images:
        sections.extend(
            [
                "## Agent Action Required",
                "",
                "The document rendered zero pages. The Agent must inspect the original file "
                "directly or ask the user for a readable export.",
                "",
            ]
        )
        return "\n".join(sections).strip() + "\n"

    if _ocr_backend_available():
        sections.extend(["## Extraction Mode", "", "OCR on every rendered page/slide.", ""])
        for page_number, image_path in enumerate(page_images, start=1):
            try:
                body = _ocr_image_with_config(image_path)
            except Exception as ocr_error:
                body = (
                    f"[OCR failed on this page: {ocr_error}]\n\n"
                    "Agent must inspect the page image above; if it cannot, ask the user."
                )
            sections.extend(_rendered_page_markdown(image_path, page_number, body, "Page"))
        return "\n".join(sections).strip() + "\n"

    if _image_analysis_available():
        sections.extend(
            [
                "## Extraction Mode",
                "",
                "Configured vision/image analysis on every rendered page/slide.",
                "",
            ]
        )
        image_config = get_image_analysis_config()
        from ocr._ocr_api import create_vision_backend
        vision_backend = create_vision_backend(image_config, IMAGE_ANALYSIS_PROMPT)
        for page_number, image_path in enumerate(page_images, start=1):
            try:
                body = _analyze_page_image_with_vision(image_path, backend=vision_backend)
            except Exception as vision_error:
                body = (
                    f"[Vision analysis failed on this page: {vision_error}]\n\n"
                    "Agent must inspect the page image above; if it cannot, ask the user."
                )
            sections.extend(_rendered_page_markdown(image_path, page_number, body, "Page"))
        return "\n".join(sections).strip() + "\n"

    sections.extend(
        [
            "## Extraction Mode",
            "",
            "OCR and configured vision/image analysis are unavailable. Rendered page images "
            "were preserved so the Agent can inspect every page directly.",
            "",
        ]
    )
    for page_number, image_path in enumerate(page_images, start=1):
        body = (
            "Agent must read this rendered page image and compile its visible content. "
            "If the Agent cannot inspect images in the current environment, ask the user "
            "for OCR text or a text export for this page."
        )
        sections.extend(_rendered_page_markdown(image_path, page_number, body, "Page"))

    return "\n".join(sections).strip() + "\n"


def _markitdown_to_markdown(source_path: Path) -> str:
    """Use MarkItDown for non-paginated document fallback when installed."""
    try:
        from markitdown import MarkItDown

        with _readonly_working_copy(source_path) as work_path:
            result = MarkItDown().convert(str(work_path))
        return (getattr(result, "text_content", "") or "").strip()
    except Exception as exc:
        print(f"  WARNING: MarkItDown failed for {source_path}: {exc}", file=sys.stderr)
        return ""


def _preprocess_svg(svg_path: Path) -> str:
    """Extract text and structure from SVG XML for LLM ingestion.

    SVG is vector XML — vision models can't process it. LLMs CAN read the XML,
    but raw SVG is noisy (path data, transforms, defs). This preprocessor extracts
    meaningful content: text elements, structural groups, metadata, and shape labels.
    """
    import xml.etree.ElementTree as ET

    try:
        # Parse SVG XML, stripping namespaces for simplicity
        raw = svg_path.read_text(encoding="utf-8")
        # Remove namespace prefixes so ElementTree can find tags
        cleaned = re.sub(r'<(\/?)(\w+):(\w+)', r'<\1\3', raw)
        cleaned = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', '', cleaned)
        root = ET.fromstring(cleaned)
    except Exception:
        # If parsing fails, return raw text — LLM can still extract info
        return raw

    ns = "{http://www.w3.org/2000/svg}"
    lines: list[str] = [
        f"# SVG Source: {svg_path.name}",
        "",
        "> **Format**: SVG (vector graphic — text extracted from XML)",
        f"> **Size**: {svg_path.stat().st_size // 1024} KB",
        "",
    ]

    # ── Metadata ──
    title = root.find(f".//{ns}title")
    desc = root.find(f".//{ns}desc")
    if title is not None and title.text:
        lines.append(f"**Title**: {title.text.strip()}")
    if desc is not None and desc.text:
        lines.append(f"**Description**: {desc.text.strip()}")
    if title is not None or desc is not None:
        lines.append("")

    # ── Extract text elements (the actual readable content) ──
    text_elements: list[str] = []
    for elem in root.iter():
        tag = elem.tag.replace(ns, "")
        if tag in ("text", "tspan") and elem.text:
            text = elem.text.strip()
            if text:
                text_elements.append(text)

    # ── Extract groups with IDs/labels (structure) ──
    groups: list[dict] = []
    for elem in root.iter():
        tag = elem.tag.replace(ns, "")
        if tag == "g":
            gid = elem.get("id", "")
            label = elem.get("aria-label", "") or elem.get("data-name", "")
            if gid or label:
                group_texts: list[str] = []
                for sub in elem.iter():
                    subtag = sub.tag.replace(ns, "")
                    if subtag in ("text", "tspan") and sub.text:
                        group_texts.append(sub.text.strip())
                groups.append({
                    "id": gid,
                    "label": label,
                    "texts": group_texts[:10],
                })

    # ── Build clean output ──
    if text_elements:
        lines.append("## Extracted Text")
        lines.append("")
        for t in text_elements[:100]:  # cap at 100 text elements
            lines.append(f"- {t}")
        lines.append("")

    if groups:
        lines.append("## Structure (Groups)")
        lines.append("")
        for g in groups[:30]:
            label = g["label"] or g["id"]
            if label:
                lines.append(f"### {label}")
                if g["texts"]:
                    for t in g["texts"][:5]:
                        lines.append(f"  - {t}")
                lines.append("")

    # ── Raw XML (truncated, for LLM reference) ──
    lines.append("## Raw SVG XML (reference)")
    lines.append("")
    lines.append("```xml")
    # Strip long path data for readability
    compact = re.sub(r'\s+d="[^"]{100,}"', ' d="[...]"', raw)
    lines.append(compact[:5000])
    lines.append("```")
    lines.append("")

    result = "\n".join(lines)
    if len(result) < 200:
        # Fallback: nothing useful extracted, return full raw
        return raw
    return result


def read_source_content(source_path: str | Path) -> tuple[str, str]:
    """Read a compile source and return (content, display_name)."""
    path = Path(source_path)
    if is_paginated_document_source(path):
        return _read_paginated_document_for_compile(path), path.name

    if is_document_source(path):
        content = _markitdown_to_markdown(path)
        if not content:
            raise RuntimeError(
                f"Document compile requires MarkItDown or direct Agent inspection: {path}"
            )
        return content, path.name

    if is_image_source(path):
        return analyze_image_for_compile(path), path.name

    # SVG: preprocess XML before sending to LLM
    if path.suffix.lower() == ".svg":
        return _preprocess_svg(path), path.name

    with open(path, encoding="utf-8") as f:
        return f.read(), path.name


def _read_agent_visible_source(source_path: Path) -> tuple[str, bool]:
    """Read source content for Agent mode without configured text LLM calls."""
    try:
        if is_paginated_document_source(source_path):
            return _read_paginated_document_for_compile(source_path), True
        if is_image_source(source_path):
            # Reuses the full image pipeline: vision-skill (preferred) with
            # OCR fallback pre-extracted, and the Agent's own capability as a
            # last resort.
            return analyze_image_for_compile(source_path, for_agent=True), True
        if is_document_source(source_path):
            content = _markitdown_to_markdown(source_path)
            return (content, True) if content else ("", False)
        if source_path.suffix.lower() == ".svg":
            return _preprocess_svg(source_path), True
        if is_text_source(source_path):
            size_bytes = source_path.stat().st_size
            if size_bytes > 50 * 1024 * 1024:
                return (
                    f"[File too large ({size_bytes // 1024 // 1024} MB). "
                    f"Agent should read the file directly.]",
                    False,
                )
            return source_path.read_text(encoding="utf-8"), True
        return "", False
    except (OSError, UnicodeDecodeError):
        return "", False


def infer_source_type(path: Path) -> str:
    """Return a lightweight hint only; final source type belongs to the Agent."""
    name_lower = path.name.lower()
    if "chat" in name_lower or "conversation" in name_lower:
        return "conversation"
    suffix = path.suffix.lower()
    if suffix in {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".sql"}:
        return "code"
    if suffix in {".md", ".markdown", ".rst", ".adoc", ".html", ".htm"}:
        return "article"
    return "doc"


def create_agent_compile_task(
    source_path: str,
    source_type: str = "auto",
    force: bool = False,
    dry_run: bool = False,
    depth: int | None = None,
) -> dict:
    """Create an Agent-readable compile task without calling configured models.

    The current Agent is expected to read the source when possible, classify the
    document type, and write wiki pages according to schema.md and compile rules.
    """
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    task_dir = WIKI_DIR / "agent_tasks"
    task_dir.mkdir(parents=True, exist_ok=True)

    if path.is_dir():
        try:
            sources = iter_source_files(path, max_depth=depth)
        except PermissionError as e:
            raise PermissionError(
                f"Cannot read source directory: {e}. Check directory permissions."
            ) from e
        max_entries = 500
        displayed = sources[:max_entries]
        remaining = sources[max_entries:]
        suffix = ""
        if remaining:
            suffix = f"\n\n... and {len(remaining)} more files:\n"
            suffix += "\n".join(f"- `{src}`" for src in remaining[:10])
            if len(remaining) > 10:
                suffix += f"\n- ... ({len(remaining) - 10} additional files omitted)"
        source_entries = "\n".join(f"- `{src}`" for src in displayed) + suffix or "- No supported files found"
        readable_content = ""
        readable = False  # Directory: individual file readability is unknown without per-file extraction
        source_name = path.name
        source_hint = "directory"
    else:
        content, readable = _read_agent_visible_source(path)
        readable_content = strip_sensitive(content) if readable else ""
        source_entries = f"- `{path}`"
        source_name = path.name
        source_hint = infer_source_type(path)

    selected_type = source_type if source_type != "auto" else "Agent must decide"
    expert_guidance = build_domain_expert_guidance(readable_content, source_name)
    schema_text = ""
    if SCHEMA_PATH.is_file():
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")[:12000]
    else:
        template_schema = Path(__file__).resolve().parent.parent / "templates" / "schema.md"
        if template_schema.is_file():
            schema_text = template_schema.read_text(encoding="utf-8")[:12000]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", source_name).strip("-") or "source"
    task_path = task_dir / f"compile-{timestamp}-{safe_name}.md"

    content_block = ""
    if path.is_file() and readable:
        if is_paginated_document_source(path) or is_image_source(path):
            # Raw markdown (not code-fenced) so embedded image links render
            # for the Agent — pages and image sources both rely on this.
            max_preview_chars = 200_000
            preview = readable_content[:max_preview_chars]
            if len(readable_content) > len(preview):
                omitted = len(readable_content) - max_preview_chars
                if is_paginated_document_source(path):
                    truncated = (
                        f"\n\n[TRUNCATED: {omitted:,} additional characters omitted. "
                        "Agent should inspect the rendered page images under "
                        f"{_document_images_dir(path).resolve()}.]"
                    )
                else:
                    truncated = (
                        f"\n\n[TRUNCATED: {omitted:,} additional characters omitted. "
                        "Agent should read the source image directly.]"
                    )
            else:
                truncated = ""
            content_block = f"""## Source Content Preview

{preview}
{truncated}
"""
        else:
            preview = readable_content[:50000]
            truncated = (
                "\n\n[TRUNCATED: Agent should read the source file directly.]"
                if len(readable_content) > len(preview)
                else ""
            )
            content_block = f"""## Source Content Preview

```text
{preview}
```
{truncated}
"""
    elif path.is_file():
        content_block = """## Source Readability

The script did not extract text from this source without OCR/vision/model calls.
The Agent should try to inspect/read the file with available capabilities. If the
Agent cannot read it, ask the user to provide a text export or summary.
"""

    task = f"""# Agent Compile Task

This task was generated in Agent mode. Do not call the configured LLM API.

## Source

{source_entries}

- Requested type: `{selected_type}`
- Source type hint: `{source_hint}`
- Force overwrite: `{force}`
- Dry run: `{dry_run}`
- Wiki dir: `{WIKI_DIR}`
- Compile timestamp (set as frontmatter `timestamp`): `{datetime.now(timezone.utc).isoformat()}`

## Agent Responsibilities

1. Read the source directly if possible.
2. Decide the document's actual domain and purpose; `doc`, `article`, `code`, or
   `conversation` is only a storage hint, not the compilation strategy.
3. Apply the matched expert lens below, then compile according to `.wiki/schema.md`.
4. Treat `.wiki/pages/` as the native OKF v0.1 bundle. Write concept documents
   under meaningful subdirectories and use their relative paths as Concept IDs.
5. Update `.wiki/pages/index.md`, `.wiki/pages/log.md`, graph files, and audit files.
6. If the source cannot be read, stop and ask the user for readable content.

{expert_guidance}

## Required OKF v0.1 Concept Standard

- Every non-reserved Markdown file starts with YAML frontmatter containing a
  non-empty `type` field.
- Use OKF fields directly: `type`, `title`, `description`, optional `resource`,
  `tags`, and ISO 8601 `timestamp`. Use `provenance` only for the source identity.
- Do not store legacy `id`, `name`, `summary`, `keywords`, `created_at`, or
  `published_at` fields. Concept ID is the bundle-relative file path without `.md`.
- Use structural Markdown suited to the matched domain. `# Schema`, `# Examples`,
  and `# Citations` have their OKF conventional meanings when applicable.
- Cross-concept relationships use standard Markdown links, preferably absolute
  bundle-relative links such as `[Orders](/tables/orders.md)`. Do not use wikilinks.
- Prefer high-quality compiled pages over raw chunks. This is not a RAG ingestion step.

## Data Fidelity (数据保真 — non-negotiable)

- Preserve ALL data verbatim: numbers, dates, amounts, percentages, thresholds,
  config parameters, table cells, statistics, units, and names. No tampering,
  omission, rewriting, rounding, unit conversion, or "inferred completion".
- Never fabricate data not present in the source. If a value is uncertain, keep
  the original wording verbatim and quote it under Source Context — do not guess.
- Reproduce tables with their original rows/columns intact; do not merge, drop,
  reorder, or summarize cells.

## Schema Context

```markdown
{schema_text}
```

{content_block}
"""
    if not dry_run:
        atomic_write(task_path, task)
    return {
        "source": str(path),
        "mode": "agent",
        "agent_task": str(task_path) if not dry_run else "(dry-run — task not written)",
        "needs_agent": True,
        "readable": readable,
        "pages_created": 0,
        "pages_updated": 0,
        "dry_run": dry_run,
        "message": (
            "Agent compile task created. The current Agent should execute this task; "
            "no configured LLM was called."
        ),
    }


def extract_edge_type(line: str) -> str:
    lowered = line.lower()
    prose_rules = [
        (("依赖", "取决于", "depends on", "requires"), "depends_on"),
        (("使用", "采用", "uses", "employs"), "uses"),
        (("扩展", "基于", "extends", "based on"), "extends"),
        (("改进", "优化", "improves", "enhances"), "improves_upon"),
        (("矛盾", "冲突", "contradicts", "conflicts"), "contradicts"),
        (("取代", "替代", "supersedes", "replaces"), "supersedes"),
        (("导致", "引起", "caused by", "triggered by"), "caused_by"),
        (("修复", "解决", "fixed by", "resolved by"), "fixed_by"),
        (("属于", "组成部分", "part of", "component of"), "part_of"),
        (("负责", "实现", "implemented by", "executed by"), "implemented_by"),
    ]
    for keywords, relationship in prose_rules:
        if any(keyword in lowered for keyword in keywords):
            return relationship
    for pattern, rel_type in KEYWORD_RELATION_MAP:
        if re.search(pattern, line):
            return rel_type
    return "relates_to"


def _parse_schema_table(section_title: str) -> list[list[str]]:
    """Parse a backtick-based markdown table from schema.md."""
    if not SCHEMA_PATH.exists():
        return []

    rows: list[list[str]] = []
    in_section = False
    for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip() == section_title:
            in_section = True
            continue
        if in_section and line.startswith("## ") and line.strip() != section_title:
            break
        if in_section and line.startswith("| `"):
            parts = [part.strip().strip("`").strip() for part in line.split("|")[1:-1]]
            if parts:
                rows.append(parts)
    return rows


def load_entity_types_from_schema() -> tuple[list[str], str, str]:
    """Load entity and relationship type prompt context from .wiki/schema.md."""
    entity_rows = _parse_schema_table("## Entity Types")
    rel_rows = _parse_schema_table("## Relationship Types")

    entity_types: list[str] = []
    entity_lines: list[str] = []
    for row in entity_rows:
        if len(row) >= 3 and row[0] and row[0] != "type":
            entity_types.append(row[0])
            entity_lines.append(f"- **{row[0]}**: {row[2]}")

    rel_types: list[str] = []
    rel_lines: list[str] = []
    for row in rel_rows:
        if row and row[0] and row[0].lower() != "type":
            rel_types.append(row[0])
            meaning = row[2] if len(row) >= 3 else f"entity A {row[0]} entity B"
            rel_lines.append(f"- **{row[0]}**: {meaning}")

    for entity_type in DEFAULT_ENTITY_TYPES:
        if entity_type not in entity_types:
            entity_types.append(entity_type)
            entity_lines.append(f"- **{entity_type}**: {entity_type} page")

    for rel_type in DEFAULT_RELATIONSHIP_TYPES:
        if rel_type not in rel_types:
            rel_lines.append(f"- **{rel_type}**: entity A {rel_type} entity B")

    return entity_types, "\n".join(entity_lines), "\n".join(rel_lines)


def load_ingest_rules_from_schema(source_type: str) -> tuple[list[str], str]:
    """Return source-type focus rules for compile prompts."""
    return INGEST_RULES.get(source_type, INGEST_RULES["doc"])

def load_config():
    return get_config()


def get_paths():
    wiki_dir = get_wiki_dir()
    return {
        "wiki_dir": wiki_dir,
        "pages_dir": wiki_dir / "pages",
        "entities_dir": wiki_dir / "pages" / "entities",
        "concepts_dir": wiki_dir / "pages" / "concepts",
        "index_file": wiki_dir / "pages" / "index.md",
        "schema_path": wiki_dir / "schema.md",
        "graph_dir": wiki_dir / "graph",
    }

WIKI_DIR = get_wiki_dir()
PAGES_DIR = WIKI_DIR / "pages"
ENTITIES_DIR = PAGES_DIR / "entities"
CONCEPTS_DIR = PAGES_DIR / "concepts"
INDEX_FILE = PAGES_DIR / "index.md"
SCHEMA_PATH = WIKI_DIR / "schema.md"
GRAPH_DIR = WIKI_DIR / "graph"
SOURCE_IMAGES_DIR = WIKI_DIR / "source" / "images"


def _slugify_okf_title(value: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip().lower()).strip("-.")
    return slug or "concept"


def _okf_page_from_model(
    page_content: str, source_name: str
) -> tuple[str, dict, str, Path] | None:
    """Normalize model output to native OKF metadata and derive its Concept ID."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", page_content, re.DOTALL)
    if not match:
        return None
    try:
        raw = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    page_type = str(raw.get("type") or "Reference").strip()
    title = str(raw.get("title") or raw.get("name") or raw.get("id") or "").strip()
    if not title:
        return None
    slug = _slugify_okf_title(str(raw.get("slug") or raw.get("id") or title))
    directory = "concepts" if page_type.lower() in CONCEPT_LIKE_TYPES else "entities"
    concept_identifier = f"{directory}/{slug}"
    metadata: dict = {
        "type": page_type,
        "title": title,
        "description": str(raw.get("description") or raw.get("summary") or "").strip(),
        "tags": raw.get("tags") or raw.get("keywords") or [],
        "timestamp": raw.get("timestamp")
        or raw.get("published_at")
        or datetime.now(timezone.utc).isoformat(),
        "provenance": source_name,
    }
    if raw.get("resource"):
        metadata["resource"] = raw["resource"]
    metadata = {key: value for key, value in metadata.items() if value not in (None, "", [])}
    body = match.group(2).lstrip()
    normalized = (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n"
        + body
    )
    return normalized, metadata, concept_identifier, PAGES_DIR / f"{concept_identifier}.md"


def atomic_write(path: Path, content: str):
    """Atomic file write (temp + rename, safe against partial writes)."""
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def write_audit(operation: str, details: dict):
    audit_file = WIKI_DIR / "audit.json"
    audit_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **details,
    }

    entries = []
    if audit_file.exists():
        try:
            entries = json.loads(audit_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(entry)
    audit_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_contradictions(page_id: str, new_content: str, existing_content: str) -> list:
    system_prompt = """You are a contradiction detector for wiki pages.
Compare existing content with new content and identify contradictions.

Output JSON array of contradictions found:
[
  {
    "existing_claim": "Old claim text",
    "new_claim": "New claim text",
    "contradiction_type": "factual|temporal|numerical|opinion",
    "severity": "high|medium|low",
    "resolution_suggestion": "Which is more likely correct and why"
  }
]

If no contradictions, output: []

Be strict - only flag actual contradictions, not additions or clarifications."""

    user_prompt = f"""Page ID: {page_id}

EXISTING CONTENT:
{existing_content[:2000]}

NEW CONTENT:
{new_content[:2000]}

Find contradictions between existing and new content."""

    try:
        response = call_llm(system_prompt, user_prompt)
        return json.loads(response)
    except Exception:
        _log_exc("contradiction detection failed")
        return []


def auto_resolve_contradictions(page_id: str, contradictions: list[dict]) -> list[dict]:
    """Return conservative contradiction resolutions without overwriting claims.

    Compile should never abort because a reinforcement conflicts with an
    existing page. The safe default is to flag each contradiction for review
    and preserve both claims in the page history.
    """
    resolutions: list[dict] = []
    for contradiction in contradictions:
        suggestion = str(contradiction.get("resolution_suggestion", "")).strip()
        severity = str(contradiction.get("severity", "medium")).lower()
        confidence = 0.35 if severity == "high" else 0.5
        resolutions.append({
            "page_id": page_id,
            "winner": "manual_review",
            "confidence": confidence,
            "reasoning": suggestion or "Contradiction detected during compile; preserved for manual review.",
            "action": "flag",
        })
    return resolutions


def detect_language(text: str) -> str:
    """Detect if text is predominantly Chinese or English.

    Returns 'zh' if Chinese characters exceed threshold, 'en' otherwise.
    """
    if not text:
        return "en"
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    total = len(text)
    if total > 0 and cjk_count / total > 0.08:
        return "zh"
    return "en"
def _count_facts(page_content: str) -> tuple[int, int]:
    """Count facts and relationships in a compiled page."""
    fact_count = 0
    rel_count = 0

    # Count facts in Key Facts table rows: | attr | value |
    in_facts_section = False
    for line in page_content.split("\n"):
        stripped = line.strip()

        # Track section
        if stripped.startswith("## 关键事实") or stripped.startswith("## Key Facts"):
            in_facts_section = True
            continue
        elif stripped.startswith("## ") and in_facts_section:
            in_facts_section = False
            continue

        # Count fact table rows
        if in_facts_section and stripped.startswith("|") and not stripped.startswith("|---") and "|" in stripped[1:]:
            parts = [p.strip() for p in stripped.split("|")[1:-1]]
            if len(parts) >= 2 and parts[0] and parts[0] not in ("属性", "Attribute", "------"):
                fact_count += 1

        # Also count **key**: value facts
        if stripped.startswith("**") and "**:" in stripped:
            fact_count += 1

        # Count relationships
        if stripped.startswith("- ") and "[[" in stripped:
            rel_count += 1

    return fact_count, rel_count


def _print_dry_run_preview(source_name: str, all_pages: list, created_pages: list, updated_pages: list):
    """Print a structured preview of what would be compiled — no files written."""
    divider = "=" * 70
    print(f"\n{divider}", file=sys.stderr)
    print(f"  DRY-RUN PREVIEW: {source_name}", file=sys.stderr)
    print(f"  {len(created_pages)} new pages, {len(updated_pages)} updated, {len(all_pages)} total", file=sys.stderr)
    print(divider, file=sys.stderr)

    if not all_pages:
        print("  (no pages would be created)", file=sys.stderr)
        print(divider, file=sys.stderr)
        return

    # ── Table header ──
    header = f"  {'#':<4} {'ID':<32} {'Type':<12} {'Title':<22} {'Facts':<6} {'Rels':<5}"
    print(header, file=sys.stderr)
    print(f"  {'-'*4} {'-'*32} {'-'*12} {'-'*22} {'-'*6} {'-'*5}", file=sys.stderr)

    entity_count = 0
    concept_count = 0

    for i, page in enumerate(all_pages):
        pid = page.get("id", "?")[:30]
        ptype = page.get("type", "?")[:10]
        pname = page.get("name", pid)[:20]
        facts_count = str(page.get("facts", "?"))
        rels_count = str(page.get("relationships", "?"))

        if ptype in ("concept", "technique", "model", "framework", "benchmark", "paper"):
            concept_count += 1
        else:
            entity_count += 1

        marker = " +" if page in created_pages else " ~"
        print(f"  {marker:<3} {pid:<32} {ptype:<12} {pname:<22} {facts_count:<6} {rels_count:<5}", file=sys.stderr)

    print(f"  {'-'*4} {'-'*32} {'-'*12} {'-'*22} {'-'*6} {'-'*5}", file=sys.stderr)
    print(f"  Entities: {entity_count}  |  Concepts: {concept_count}  |  Total: {len(all_pages)}", file=sys.stderr)
    print(divider, file=sys.stderr)
    print("  No files were written. Use without --dry-run to compile.", file=sys.stderr)
    print(divider, file=sys.stderr)




# ── Document chunking (model-context-aware) ────────────────────────────

def _estimate_tokens(text: str, lang: str = "en") -> int:
    """Rough token count estimate. ~4 chars/token for EN, ~2 for CJK."""
    if not text:
        return 0
    if lang == "zh":
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
        non_cjk = len(text) - cjk
        return cjk // 2 + non_cjk // 4
    return len(text) // 4


def _split_by_headings(content: str, max_tokens: int, lang: str = "en") -> list[str]:
    """Split document by ``## `` headings, keeping chunks under *max_tokens*.

    Each chunk is a self-contained section group. Headings before the first
    ``## `` form the preamble chunk.
    """
    sections = re.split(r'(\n## .+)', content)
    if not sections:
        return [content] if content else []

    # Recombine: preamble + paired (heading, body) sections
    chunks_raw: list[str] = []
    preamble = sections[0].strip()
    if preamble:
        chunks_raw.append(preamble)

    i = 1
    while i < len(sections):
        heading = sections[i]
        body = sections[i + 1] if i + 1 < len(sections) else ""
        chunks_raw.append((heading + body).strip())
        i += 2

    # Merge chunks under max_tokens
    merged: list[str] = []
    current = ""
    for chunk in chunks_raw:
        combined = current + "\n\n" + chunk if current else chunk
        if _estimate_tokens(combined, lang) <= max_tokens:
            current = combined
        else:
            if current:
                merged.append(current)
            # If single chunk still exceeds max_tokens, split further by paragraphs
            if _estimate_tokens(chunk, lang) > max_tokens:
                sub_chunks = _split_by_paragraphs(chunk, max_tokens, lang)
                merged.extend(sub_chunks)
                current = ""
            else:
                current = chunk
    if current:
        merged.append(current)

    return merged if merged else [content]


def _split_by_paragraphs(text: str, max_tokens: int, lang: str = "en") -> list[str]:
    """Fallback: split an oversized chunk by blank-line-separated paragraphs."""
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = current + "\n\n" + para if current else para
        if _estimate_tokens(candidate, lang) <= max_tokens:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks if chunks else [text]

def _compile_chunked(
    chunks: list[str],
    source_name: str,
    source_type: str,
    force: bool,
    dry_run: bool,
    lang: str,
    entity_types: list[str],
    entity_type_lines: str,
    rel_type_lines: str,
    focus_types: list[str],
    focus_desc: str,
    entity_type_str: str,
) -> dict:
    """Compile a large document in chunks, then merge with dedup."""
    all_created: list[dict] = []
    all_updated: list[dict] = []
    seen_ids: set[str] = set()

    for i, chunk in enumerate(chunks):
        chunk_name = f"{source_name} [part {i+1}/{len(chunks)}]"
        print(f"  Compiling chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...", file=sys.stderr)

        try:
            result = _compile_single_chunk(
                chunk, chunk_name, source_type, force, dry_run,
                lang, entity_types, entity_type_lines, rel_type_lines,
                focus_types, focus_desc, entity_type_str,
            )
        except Exception as e:
            print(f"  ERROR: chunk {i+1}/{len(chunks)} failed: {e}", file=sys.stderr)
            continue

        # Dedup: skip pages already seen from earlier chunks
        for page in result.get("created_pages", []):
            if page["id"] not in seen_ids:
                seen_ids.add(page["id"])
                all_created.append(page)
        for page in result.get("updated_pages", []):
            if page["id"] not in seen_ids:
                seen_ids.add(page["id"])
                all_updated.append(page)
            # else: update confidence/reinforcement for already-seen entity

    all_pages = all_created + all_updated
    if not all_pages:
        print("  WARNING: No pages extracted from any chunk!", file=sys.stderr)
        return {"source": source_name, "pages_created": 0, "pages_updated": 0, "pages": []}

    # Post-processing: write pages (unless dry_run), update index/graph
    if not dry_run:
        ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
        CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)
        for page in all_pages:
            atomic_write(Path(page["path"]), _ensure_created_at(page.get("_content", "")))

        update_index(all_pages, source_name)
        update_log(source_name, len(all_created), "compile")
        update_graph(all_pages, source_name)
        write_audit("compile", {
            "source": source_name,
            "chunked": True,
            "chunks": len(chunks),
            "pages_created": len(all_created),
            "pages_updated": len(all_updated),
        })

    if dry_run:
        _print_dry_run_preview(source_name, all_pages, all_created, all_updated)

    return {
        "source": source_name,
        "pages_created": len(all_created),
        "pages_updated": len(all_updated),
        "pages": all_pages,
        "chunked": True,
        "chunks": len(chunks),
    }


def _compile_single_chunk(
    chunk_content: str,
    chunk_name: str,
    source_type: str,
    force: bool,
    dry_run: bool,
    lang: str,
    entity_types: list[str],
    entity_type_lines: str,
    rel_type_lines: str,
    focus_types: list[str],
    focus_desc: str,
    entity_type_str: str,
) -> dict:
    """Compile a single document chunk — same LLM call as compile_source but
    returns parsed pages without writing files (writing is handled by the
    chunked-compile orchestrator)."""
    import re as _re
    source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', chunk_name)[:8].lower() or "doc"
    domain_guidance = build_domain_expert_guidance(chunk_content, chunk_name)

    # Build prompts (abbreviated — reuse the same structure as compile_source)
    if lang == "zh":
        system_prompt = f"""你是 Wiki 知识编译引擎。你必须用中文撰写所有内容。

{domain_guidance}

## 数据保真（最高优先级，不可妥协）
内容中涉及的任何数据——数字、日期、金额、百分比、阈值、配置参数、表格单元格、统计值、单位、名称——必须**逐字原样保留**，不得有任何篡改、省略、改写、四舍五入、单位换算或"联想补全"。
- 原文没有的数据**绝不编造**；拿不准的数字**保留原文表述**，不要猜测或推断。
- 表格必须按原行列结构完整复现，不得合并、删除、重排序或概括单元格。
- 在"来源上下文"附上原文摘录，便于核实。

## OKF 概念标识
不要输出 `id` 字段。系统根据 `type` 和 `title` 生成 bundle 相对路径作为
Concept ID。关系必须使用标准 Markdown 链接，不使用双中括号 wikilink。

## 实体 vs 概念（这是最重要的分类！）
- **实体 (entity/role/rule/process/event/tool/system/product)**:
  文档中具体出现的东西。某个特定组织、某个具体角色、某条明确规则、某个特定流程步骤。
  特征：可以指向"一个具体实例"。

- **概念 (concept/technique/model/framework/benchmark/paper)**:
  跨文档的抽象知识。通用思想、方法论、技术模式、评估标准。
  特征：可以在多个文档中讨论，不依附于单一来源。

## 提取策略（逐段扫描，不要遗漏！）
1. **从头到尾扫描文档的每个章节**——不要只提取开头部分
2. 先找实体：组织名、人名、角色、规则条目、流程步骤、工具/系统名
3. 再找概念：本文档揭示的通用模式、方法论、技术方案
4. 对每个提取的内容问自己："这是具体实例还是通用概念？"——答案决定 ID 和存放位置

## 内容质量要求
- **关键事实表（🔴 必须输出！这是用户查询时获取精确答案的唯一来源）**:
  从文档中提取可查询的结构化事实，格式为表格。每个页面至少 3-5 条事实。
  必须包含文档中的精确数值、日期、名称。**没有关键事实表的页面会被查询系统忽略！**
- **概述**: 2-4句，说清楚"是什么 + 为什么重要 + 在本文档中的角色"
- **可回答的问题**: 列出 2-3 个该页面能精确回答的具体问题（用问句形式），帮助判断检索匹配
- **关键细节**: 提取具体事实——数字、日期、名称、判定标准、配置参数、步骤说明
- **关联关系**: 每个页面至少列出 2-4 个关联，用指定的关系关键词
- **来源上下文**: 原文摘录，便于人工核实

## 关键事实表撰写规范（★决定检索质量）
从文档原文中提取"属性 → 值"对。这些是用户查询时需要的精确答案。

正确示例:
  facts:
    审计日志保留期: 7年（亚太区企业客户）
    速率限制: 1000 req/s（Premium Partner）
    SOC 2 证据保留: 事件响应报告保留 3 年
    回滚审批人: 运维经理 + 部门总监双签
    GPU 配置建议: 7B→1×A100, 70B→4×A100

错误示例（太模糊，无法回答查询）:
  facts:
    保留期: 按规定执行
    速率: 有限制

规则:
- 每个属性必须能从文档中找到明确数值/名称/日期作为证据
- 优先提取: 数字、阈值、日期、人名、百分比、配置参数
- 如果文档提到多个值（如不同套餐），每个值单独一条
- 属性名用中文，值保留原文中的精确表述

## 关系关键词（每条关系必须用以下关键词之一开头）
关系关键词 -> 对应类型:
- 使用/采用 [X](/path/to/x.md) -> uses
- 依赖/取决于 [X](/path/to/x.md) -> depends_on
- 扩展/基于 [X](/path/to/x.md) -> extends
- 改进/优化 [X](/path/to/x.md) -> improves_upon
- 关联/属于/负责/导致/修复/取代/矛盾 [X](/path/to/x.md) -> 对应关系类型

## Output Format
用 ===PAGE_END=== 分隔每个页面。

每个页面必须包含 YAML frontmatter：
---
type: {entity_type_str}
title: 中文名称
description: 一句话摘要
tags: [关键词1, 关键词2]
timestamp: {datetime.now(timezone.utc).isoformat()}
provenance: source-name
---

> `timestamp` 使用 ISO 8601，表示该概念最后一次有意义的更新；原文发布日期应保留在正文来源上下文中，不得编造。

然后按以下结构撰写（⚠️ 必须严格遵循此顺序！）：
# [中文标题]

## 关键事实
🔴 **必须输出！这是页面最重要的部分——用户查询时从这里获取精确答案。**
| 属性 | 值 |
|------|-----|
| 属性名1 | 精确值1 |
| 属性名2 | 精确值2 |
（至少 3-5 行，每行是一个可查询的精确事实。没有此节的页面将被视为无效！）

## 概述
[2-4 句中文描述：这是什么，为什么重要，在文档中的角色]

## 可回答的问题
- 问题1？（该页面能精确回答的具体问题）
- 问题2？
（2-3 个具体问句，帮助判断此页面是否匹配用户的查询意图）

## 关键细节
- [具体事实1：包含数字、日期或名称]
- [具体事实2]
- [具体事实3]
...

## 关联关系
- 关键词 [[目标实体]] — 关系说明
...

## 来源上下文
> [文档原文摘录，便于核实]

## 质量规则
- 🔴 **关键事实表是强制要求！没有此节的页面 = 无效页面。**
- 扫描文档的每个章节，不要遗漏后半部分内容
- 实体（entity/role/rule/process/event/tool/system/product）→ ID 带 {source_abbr} 前缀
- 概念（concept/technique/model/framework/benchmark/paper）→ ID 不带前缀
- 实体:概念比例约 65:35
- 每个页面至少 150 字实质性内容
- 每个页面至少 2-4 条关联关系
- 目标: 与本段内容匹配的适当数量页面

## 实体类型参考
{entity_type_lines}

## ⚠️ 注意：这是一篇长文档的一个片段（chunk）。只提取本片段中出现的内容。
## 不要编造不在原文中的事实、数字或关系。"""

        user_prompt = f"""文档片段: {chunk_name}

内容:
{chunk_content}

请逐段扫描该文档片段，提取所有重要实体和概念，撰写 Wiki 页面。所有内容必须用中文。

## 提取步骤
1. 扫描片段中的每个章节标题，确保不遗漏任何部分
2. 提取所有具名实体（组织、角色、规则、流程、工具、系统）
3. 识别跨文档通用概念（方法论、技术模式、评估框架）
4. 为每个实体/概念建立关联关系链接

## OKF 链接规则
关系使用 bundle 相对的标准 Markdown 链接；不要输出 `id` 字段或 wikilink。

## 关注点
{focus_desc}。核心概念、组织结构、流程机制、评估标准、具体规则。

## 目标
与本段内容匹配的适当数量中文页面，内容详实，每页至少 2-4 条关系。
用 ===PAGE_END=== 分隔每个页面。"""
    else:
        system_prompt = f"""You are a wiki knowledge compiler. Your job is to read a document chunk and write high-quality wiki pages.

{domain_guidance}

## Data Fidelity (highest priority — non-negotiable)
Any data in the source — numbers, dates, amounts, percentages, thresholds, config
parameters, table cells, statistics, units, and names — must be preserved
**verbatim**. No tampering, omission, rewriting, rounding, unit conversion, or
"inferred completion".
- Never fabricate data not present in the source. If a value is uncertain, keep
  the original wording verbatim and quote it under Source Context — do not guess.
- Reproduce tables with their original rows/columns intact; do not merge, drop,
  reorder, or summarize cells.

## Entity vs Concept (CRITICAL — get this right!)
Karpathy's wiki design distinguishes two page types:
- **entity** (entity/role/rule/process/event/tool/system/product):
  Concrete instances in the document.
- **concept** (concept/technique/model/framework/benchmark/paper):
  Abstract knowledge reusable across documents.

## Extraction Strategy
1. Scan EVERY section of this chunk — don't stop after the first few sections
2. Extract all named entities (orgs, people, rules, processes, tools, systems)
3. Identify cross-cutting concepts (methods, patterns, frameworks)

## Content Quality
- **Fact Table (🔴 REQUIRED — the ONLY source of precise answers!)**: At least 3-5 facts per page. Include exact numbers, dates, names. **Pages without Key Facts are INVALID.**
- **Overview**: 2-4 sentences: what + why + role
- **Questions This Page Answers**: 2-3 specific questions this page can answer
- **Key Details**: Extract specific facts — numbers, dates, names, criteria, parameters
- **Relationships**: Minimum 2-4 per page, use exact keywords below

## Relationship Keywords
- uses/employs [X](/path/to/x.md) → uses
- depends on/requires [X](/path/to/x.md) → depends_on
- extends/based on [X](/path/to/x.md) → extends
- improves/relates to/part of/implemented by/caused by/fixed by/supersedes/contradicts
  [X](/path/to/x.md) → the corresponding relationship type

## Output Format
===PAGE_END=== separated. YAML frontmatter required.

Page structure (⚠️ MUST follow this order!):
# [Title]

## Key Facts
🔴 **REQUIRED! Most important section.**
| Attribute | Value |
|-----------|-------|
| attr1 | precise value1 |
(3-5 rows minimum)

## Overview
[2-4 sentences]

## Questions This Page Answers
- Question 1?
(2-3 specific questions)

## Key Details
- [Specific fact with numbers/dates/names]
...

## Relationships
- keyword [[target]] — explanation
...

## Source Context
> [Verbatim excerpt]

## Quality Rules
- 🔴 **Key Facts table is MANDATORY! Pages without it = INVALID.**
- Scan EVERY section
- Concept IDs are derived from bundle-relative paths; do not emit an `id` field
- Min 150 words per page, 2-4 relationships
- Target: appropriate number for this chunk's content

## Entity Types
{entity_type_lines}

## ⚠️ This is a chunk of a larger document. Only extract content present in this chunk.
## Do NOT fabricate facts, numbers, or relationships not in the source text."""

        user_prompt = f"""Document chunk: {chunk_name}

Content:
{chunk_content}

Scan this chunk and extract all important entities and concepts into wiki pages.

## Extraction Steps
1. Scan each section heading — ensure no content is missed
2. Extract all named entities (orgs, roles, rules, processes, tools, systems)
3. Identify cross-document concepts (methods, techniques, patterns, frameworks)
4. Establish typed relationships between related entities

## Focus Areas
{focus_desc}. Architecture innovations, model variants, techniques, benchmarks, key findings.

## Target
Appropriate number of pages for this chunk with substantive content, min 2-4 relationships each.
Output pages separated by ===PAGE_END==="""

    print("    Calling LLM for chunk...", file=sys.stderr)
    response = call_llm(system_prompt, user_prompt)

    # Parse pages from response (same logic as compile_source)
    pages = response.split("===PAGE_END===")
    created_pages: list[dict] = []
    updated_pages: list[dict] = []

    for page_content in pages:
        page_content = page_content.strip()
        if not page_content or not page_content.startswith("---"):
            continue

        parsed = _okf_page_from_model(page_content, chunk_name)
        if parsed is None:
            continue
        page_content, frontmatter, entity_id, page_path = parsed
        entity_type = frontmatter["type"]
        f_count, r_count = _count_facts(page_content)

        created_pages.append({
            "id": entity_id,
            "type": entity_type,
            "name": frontmatter["title"],
            "path": str(page_path),
            "facts": f_count,
            "relationships": r_count,
            "_content": page_content,
        })

    return {
        "created_pages": created_pages,
        "updated_pages": updated_pages,
    }


import hashlib as _hashlib


def _content_hash(text: str) -> str:
    """Stable hash of page body (excluding YAML frontmatter)."""
    # Strip frontmatter for comparison — metadata may change without content change
    if text.startswith("---"):
        parts = text.split("---", 2)
        body = parts[2] if len(parts) > 2 else text
    else:
        body = text
    return _hashlib.md5(body.strip().encode("utf-8")).hexdigest()


def _ensure_created_at(page_content: str, compile_date: str | None = None) -> str:
    """Ensure a compiled OKF concept has an ISO ``timestamp``.

    Fills in ``compile_date`` (YYYY-MM-DD, defaulting to today) only when the
    field is missing or empty — existing values are preserved, so updates never
    overwrite the original creation date. Uses minimal string insertion so the
    rest of the frontmatter formatting stays intact.
    """
    if not page_content or not page_content.startswith("---"):
        return page_content
    lines = page_content.split("\n")
    fm_end = 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_end = i
            break
    if fm_end == 0:
        return page_content
    try:
        fm = yaml.safe_load("\n".join(lines[1:fm_end])) or {}
    except Exception:
        return page_content
    if not isinstance(fm, dict):
        return page_content
    if fm.get("timestamp"):
        return page_content

    date_str = compile_date or datetime.now().strftime("%Y-%m-%d")
    # Keep the historical function name because it is used by the compile pipeline.
    for i in range(1, fm_end):
        if lines[i].startswith("timestamp:"):
            lines[i] = f"timestamp: {date_str}T00:00:00Z"
            return "\n".join(lines)
    lines.insert(1, f"timestamp: {date_str}T00:00:00Z")
    return "\n".join(lines)


def _get_source_pages(source_name: str) -> dict[str, dict]:
    """Return all wiki pages previously created by *source_name*.

    Returns dict of {page_id: {path, content_hash, source}} by scanning
    the native OKF bundle for pages with matching provenance.
    """
    result: dict[str, dict] = {}
    from okf import concept_id, iter_concepts

    for md_file in iter_concepts(PAGES_DIR):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        source_match = re.search(r"^provenance:\s*(.+)$", text, re.MULTILINE)
        if not source_match:
            continue
        page_source = source_match.group(1).strip()
        if page_source != source_name:
            continue
        is_manual = page_source == "manual"
        page_id = concept_id(md_file, PAGES_DIR)
        result[page_id] = {
            "path": md_file,
            "content_hash": _content_hash(text),
            "source": page_source,
            "manual": is_manual,
        }
    return result


def _prune_stale_pages(
    new_page_ids: set[str], source_name: str, dry_run: bool = False
) -> list[str]:
    """Remove pages from *source_name* that no longer appear in new compilation.

    Only removes pages whose source field matches *source_name* exactly.
    Manual pages (source: manual) are never pruned.
    Returns list of removed page IDs.
    """
    existing = _get_source_pages(source_name)
    removed: list[str] = []
    for page_id, info in existing.items():
        if page_id in new_page_ids:
            continue
        if info.get("manual"):
            continue
        if dry_run:
            print(f"  [DRY-RUN] Would prune: {info['path'].name}", file=sys.stderr)
        else:
            try:
                info["path"].unlink()
                print(f"  Pruned: {info['path'].name}", file=sys.stderr)
            except OSError as e:
                print(f"  WARNING: failed to prune {info['path'].name}: {e}", file=sys.stderr)
        removed.append(page_id)
    return removed


def compile_source(source_path: str, source_type: str = "doc", force: bool = False, dry_run: bool = False) -> dict:

    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source not found: {source_path}")

    source_file = Path(source_path)
    if source_file.is_dir():
        return compile_path(source_path, source_type=source_type, force=force)

    content, source_name = read_source_content(source_file)

    content = strip_sensitive(content)

    lang = detect_language(content)
    domain_guidance = build_domain_expert_guidance(content, source_name)
    entity_types, entity_type_lines, rel_type_lines = load_entity_types_from_schema()
    focus_types, focus_desc = load_ingest_rules_from_schema(source_type)
    entity_type_str = "|".join(entity_types)

    print(f"Compiling {source_name} ({len(content)} chars, {lang}, {source_type})...", file=sys.stderr)
    print(f"  Focus: {', '.join(focus_types)} — {focus_desc}", file=sys.stderr)

    # ── Large document chunking (model-context-aware) ──
    chunk_threshold = get_chunk_threshold()
    est_tokens = _estimate_tokens(content, lang)
    if est_tokens > chunk_threshold:
        chunks = _split_by_headings(content, chunk_threshold, lang)
        if len(chunks) > 1:
            get_chunk_threshold()  # will return model max without override
            print(
                f"  Document exceeds model context threshold "
                f"({est_tokens} > {chunk_threshold} tokens), "
                f"splitting into {len(chunks)} chunks...",
                file=sys.stderr,
            )
            return _compile_chunked(
                chunks, source_name, source_type, force, dry_run,
                lang, entity_types, entity_type_lines, rel_type_lines,
                focus_types, focus_desc, entity_type_str,
            )

    if lang == "zh":
        # Derive a short source abbreviation for ID prefix
        import re as _re
        source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', source_name)[:8].lower() or "doc"
        system_prompt = f"""你是 Wiki 知识编译引擎。你必须用中文撰写所有内容。

{domain_guidance}

## 数据保真（最高优先级，不可妥协）
内容中涉及的任何数据——数字、日期、金额、百分比、阈值、配置参数、表格单元格、统计值、单位、名称——必须**逐字原样保留**，不得有任何篡改、省略、改写、四舍五入、单位换算或"联想补全"。
- 原文没有的数据**绝不编造**；拿不准的数字**保留原文表述**，不要猜测或推断。
- 表格必须按原行列结构完整复现，不得合并、删除、重排序或概括单元格。
- 在"来源上下文"附上原文摘录，便于核实。

## OKF 概念标识
不要输出 `id` 字段。系统根据 `type` 和 `title` 生成 bundle 相对路径作为
Concept ID。关系必须使用标准 Markdown 链接，不使用双中括号 wikilink。

## 实体 vs 概念（这是最重要的分类！）
- **实体 (entity/role/rule/process/event/tool/system/product)**:
  文档中具体出现的东西。某个特定组织、某个具体角色、某条明确规则、某个特定流程步骤。
  特征：可以指向"一个具体实例"。
  例: "XX公司的评审委员会"是 entity，"XX项目2025年预算"是 entity

- **概念 (concept/technique/model/framework/benchmark/paper)**:
  跨文档的抽象知识。通用思想、方法论、技术模式、评估标准。
  特征：可以在多个文档中讨论，不依附于单一来源。
  例: "MoE架构"是 concept，"数字化转型方法论"是 concept

## 提取策略（逐段扫描，不要遗漏！）
1. **从头到尾扫描文档的每个章节**——不要只提取开头部分
2. 先找实体：组织名、人名、角色、规则条目、流程步骤、工具/系统名
3. 再找概念：本文档揭示的通用模式、方法论、技术方案
4. 对每个提取的内容问自己："这是具体实例还是通用概念？"——答案决定 ID 和存放位置

## 内容质量要求
- **关键事实表（🔴 必须输出！这是用户查询时获取精确答案的唯一来源）**:
  从文档中提取可查询的结构化事实，格式为表格。每个页面至少 3-5 条事实。
  必须包含文档中的精确数值、日期、名称。**没有关键事实表的页面会被查询系统忽略！**
- **概述**: 2-4句，说清楚"是什么 + 为什么重要 + 在本文档中的角色"
- **可回答的问题**: 列出 2-3 个该页面能精确回答的具体问题（用问句形式），帮助判断检索匹配
- **关键细节**: 提取具体事实——数字、日期、名称、判定标准、配置参数、步骤说明
- **关联关系**: 每个页面至少列出 2-4 个关联，用指定的关系关键词
- **来源上下文**: 原文摘录，便于人工核实

## 关键事实表撰写规范（★决定检索质量）
从文档原文中提取"属性 → 值"对。这些是用户查询时需要的精确答案。

正确示例:
  facts:
    审计日志保留期: 7年（亚太区企业客户）
    速率限制: 1000 req/s（Premium Partner）
    SOC 2 证据保留: 事件响应报告保留 3 年
    回滚审批人: 运维经理 + 部门总监双签
    GPU 配置建议: 7B→1×A100, 70B→4×A100

错误示例（太模糊，无法回答查询）:
  facts:
    保留期: 按规定执行
    速率: 有限制

规则:
- 每个属性必须能从文档中找到明确数值/名称/日期作为证据
- 优先提取: 数字、阈值、日期、人名、百分比、配置参数
- 如果文档提到多个值（如不同套餐），每个值单独一条
- 属性名用中文，值保留原文中的精确表述

## 关系关键词（每条关系必须用以下关键词之一开头）
关系关键词 -> 对应类型:
- 使用/采用 [X](/path/to/x.md) -> uses
- 依赖/取决于 [X](/path/to/x.md) -> depends_on
- 扩展/基于 [X](/path/to/x.md) -> extends
- 改进/关联/属于/负责/导致/修复/取代/矛盾 [X](/path/to/x.md) -> 对应关系类型

## Output Format
用 ===PAGE_END=== 分隔每个页面。

每个页面必须包含 YAML frontmatter：
---
type: {entity_type_str}
title: 中文名称
description: 一句话摘要
tags: [关键词1, 关键词2]
timestamp: {datetime.now(timezone.utc).isoformat()}
provenance: source-name
---

> `timestamp` 使用 ISO 8601，表示该概念最后一次有意义的更新；原文发布日期应保留在正文来源上下文中，不得编造。

然后按以下结构撰写（⚠️ 必须严格遵循此顺序！）：
# [中文标题]

## 关键事实
🔴 **必须输出！这是页面最重要的部分——用户查询时从这里获取精确答案。**
| 属性 | 值 |
|------|-----|
| 属性名1 | 精确值1 |
| 属性名2 | 精确值2 |
（至少 3-5 行，每行是一个可查询的精确事实。没有此节的页面将被视为无效！）

## 概述
[2-4 句中文描述：这是什么，为什么重要，在文档中的角色]

## 可回答的问题
- 问题1？（该页面能精确回答的具体问题）
- 问题2？
（2-3 个具体问句，帮助判断此页面是否匹配用户的查询意图）

## 关键细节
- [具体事实1：包含数字、日期或名称]
- [具体事实2]
- [具体事实3]
...

## 关联关系
- 关键词 [[目标实体]] — 关系说明
...

## 来源上下文
> [文档原文摘录，便于核实]

## 质量规则
- 🔴 **关键事实表是强制要求！没有此节的页面 = 无效页面。**
- 扫描文档的每个章节，不要遗漏后半部分内容
- 实体（entity/role/rule/process/event/tool/system/product）→ ID 带 {source_abbr} 前缀
- 概念（concept/technique/model/framework/benchmark/paper）→ ID 不带前缀
- 实体:概念比例约 65:35
- 每个页面至少 150 字实质性内容
- 每个页面至少 2-4 条关联关系
- 页面数量由文档内容和后续查询任务决定

## 实体类型参考
{entity_type_lines}"""
    else:
        system_prompt = f"""You are a wiki knowledge compiler. Your job is to read a document and write high-quality wiki pages.

{domain_guidance}

## Data Fidelity (highest priority — non-negotiable)
Any data in the source — numbers, dates, amounts, percentages, thresholds, config
parameters, table cells, statistics, units, and names — must be preserved
**verbatim**. No tampering, omission, rewriting, rounding, unit conversion, or
"inferred completion".
- Never fabricate data not present in the source. If a value is uncertain, keep
  the original wording verbatim and quote it under Source Context — do not guess.
- Reproduce tables with their original rows/columns intact; do not merge, drop,
  reorder, or summarize cells.

## Entity vs Concept (CRITICAL — get this right!)
Karpathy's wiki design distinguishes two page types:
- **entity** (entity/role/rule/process/event/tool/system/product):
  Concrete instances in the document. A specific organization, person, rule, or process step.
  Think: "Can I point to this as one specific instance?" → entity.
- **concept** (concept/technique/model/framework/benchmark/paper):
  Abstract knowledge reusable across documents. Methodologies, patterns, evaluation criteria.
  Think: "Could this be discussed in multiple independent documents?" → concept.

**Default bias**: If unsure, prefer entity. Most document content is concrete, not abstract.

## Extraction Strategy (scan exhaustively!)
1. Scan EVERY section of the document — don't stop after the first few sections
2. First pass: extract all named entities (orgs, people, rules, processes, tools, systems)
3. Second pass: identify cross-cutting concepts (methods, patterns, frameworks)
4. For each extraction, ask: "Specific instance or general idea?" — this determines ID and placement

## Content Quality
- **Fact Table (🔴 REQUIRED — the ONLY source of precise answers for user queries!)**:
  Extract structured queryable facts as a markdown table. At least 3-5 facts per page.
  Include exact numbers, dates, names from the source. **Pages without a Key Facts table will be ignored by the query system!**
- **Overview**: 2-4 substantive sentences: what it is + why it matters + role in this document
- **Questions This Page Answers**: List 2-3 specific questions this page can answer precisely (as interrogative sentences), helping match user queries
- **Key Details**: Extract specific facts — numbers, dates, names, criteria, parameters, steps
- **Relationships**: Minimum 2-4 per page, using the exact keywords below
- **Source Context**: Include verbatim excerpts for human verification

## Fact Table Guidelines (★ determines retrieval quality)
Extract "attribute → value" pairs from the document. These are the precise answers users will search for.

Good examples:
  facts:
    audit log retention: 7 years (APAC enterprise)
    rate limit: 1000 req/s (Premium tier)
    SOC 2 evidence retention: 3 years for incident reports
    model params: 671B total, 37B active per token
    GPU requirement: 8×A100 80GB for FP16 inference

Bad examples (too vague, can't answer queries):
  facts:
    retention: per policy
    limit: varies

Rules:
- Every attribute must have an explicit number/date/name from the document
- Prioritize: numbers, thresholds, dates, names, percentages, config params
- If the document mentions multiple values (e.g., different tiers), each gets its own fact
- For Chinese documents, use Chinese attribute names

## Relationship Keywords (every relationship MUST start with one of these)
- uses/employs [X](/path/to/x.md) → uses
- depends on/requires [X](/path/to/x.md) → depends_on
- extends/based on [X](/path/to/x.md) → extends
- improves/relates to/part of/implemented by/caused by/fixed by/supersedes/contradicts
  [X](/path/to/x.md) → the corresponding relationship type

## Output Format
Write pages separated by exactly this marker: ===PAGE_END===

Each page must start with YAML frontmatter:
---
type: {entity_type_str}
title: Display Name
description: One-sentence summary
tags: [keyword1, keyword2]
timestamp: {datetime.now(timezone.utc).isoformat()}
provenance: source-name
---

> `timestamp` is the ISO 8601 time of the last meaningful concept update. Preserve the
> source publication date in Source Context when present; never fabricate it.

Then the page content (⚠️ MUST follow this exact order!):
# [Title]

## Key Facts
🔴 **REQUIRED! This is the most important section — users get precise answers from here.**
| Attribute | Value |
|-----------|-------|
| attribute1 | precise value1 |
| attribute2 | precise value2 |
(at least 3-5 rows, each a queryable precise fact. Pages without this section are INVALID!)

## Overview
[2-4 sentences: what it is, why it matters, role in this document]

## Questions This Page Answers
- Question 1? (a specific question this page can answer precisely)
- Question 2?
(2-3 specific interrogative sentences)

## Key Details
- [Specific fact 1: include numbers, dates, or names]
- [Specific fact 2]
- [Specific fact 3]
...

## Relationships
- keyword [[target-entity]] — explanation of the relationship
...

## Source Context
> [Verbatim excerpt from the document]

## Quality Rules
- 🔴 **Key Facts table is MANDATORY! Pages without it = INVALID.**
- Scan EVERY section — don't miss content in later parts of the document
- Concept IDs are derived from bundle-relative paths; do not emit an `id` field
- Minimum 150 words of substantive content per page
- At least 2-4 typed relationships per page
- Merge obvious variants: "DeepSeek-V3.2" and "DeepSeek-V3-2" → single page "deepseek-v3.2"
- Title Case names: "Muon Optimizer", "KV Cache"
- Page count is determined by the source and downstream retrieval tasks

## Entity Types
{entity_type_lines}"""

    if lang == "zh":
        user_prompt = f"""文档: {source_name}

内容:
{content}

请逐段扫描该文档，提取所有重要实体和概念，撰写 Wiki 页面。所有内容必须用中文。

## 提取步骤
1. 扫描每个章节标题，确保不遗漏任何部分
2. 提取所有具名实体（组织、角色、规则、流程、工具、系统）
3. 识别跨文档通用概念（方法论、技术模式、评估框架）
4. 为每个实体/概念建立关联关系链接

## OKF 链接规则
关系使用 bundle 相对的标准 Markdown 链接；不要输出 `id` 字段或 wikilink。

## 关注点
{focus_desc}。核心概念、组织结构、流程机制、评估标准、具体规则。

## 目标
生成与内容复杂度匹配的高质量中文概念文档。
用 ===PAGE_END=== 分隔每个页面。"""
    else:
        user_prompt = f"""Document: {source_name}

Content:
{content}

Scan this document section by section and extract all important entities and concepts into wiki pages.

## Extraction Steps
1. Scan each section heading — ensure no content is missed
2. Extract all named entities (orgs, roles, rules, processes, tools, systems)
3. Identify cross-document concepts (methods, techniques, patterns, frameworks)
4. Establish typed relationships between every pair of related entities

## Focus Areas
{focus_desc}. Architecture innovations, model variants, techniques, benchmarks, key findings.

## Target
Generate the number of high-quality concepts justified by the source.
Output pages separated by ===PAGE_END==="""
    print("Calling LLM...", file=sys.stderr)
    response = call_llm(system_prompt, user_prompt)

    pages = response.split("===PAGE_END===")

    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)

    created_pages = []
    updated_pages = []
    contradictions_found = []

    # Derive source abbreviation for entity ID prefix
    import re as _re
    src_stem = Path(source_name).stem
    source_abbr = _re.sub(r'[^\u4e00-\u9fff\w]', '', src_stem)[:8].lower() or "doc"
    concept_types = CONCEPT_LIKE_TYPES
    # Track which entity IDs need concept pages (base name → list of instance IDs)
    concept_groups: dict[str, list[dict]] = {}
    _skipped: list[int] = [0]  # mutable counter for unchanged pages
    existing_source_pages = _get_source_pages(source_name)  # for incremental hash comparison

    for page_content in pages:
        page_content = page_content.strip()
        if not page_content or not page_content.startswith("---"):
            continue

        parsed = _okf_page_from_model(page_content, source_name)
        if parsed is None:
            print("  WARNING: page is missing valid OKF metadata", file=sys.stderr)
            continue
        page_content, frontmatter, entity_id, page_path = parsed
        entity_type = frontmatter["type"]

        # Persist regular Markdown tables as queryable DuckDB data. Key Facts
        # remains in the page because the retrieval pipeline reads it directly.
        if not dry_run:
            page_content, stored_tables = persist_page_tables(
                page_content, source_name, str(entity_id)
            )
            if stored_tables:
                print(f"  Extracted tables: {', '.join(stored_tables)}", file=sys.stderr)

        page_path.parent.mkdir(parents=True, exist_ok=True)

        # ── 同名异实保护：如果已存在同名实体页（非 concept 类型），自动加前缀 ──
        # 即使 force 模式也检测——force 只允许覆盖同源页面，不能覆盖跨源实体
        if entity_type not in concept_types and page_path.exists():
            existing_content = page_path.read_text(encoding="utf-8")
            existing_source = ""
            for line in existing_content.split("\n"):
                if line.startswith("provenance:"):
                    existing_source = line.replace("provenance:", "").strip()
                    break
            # If existing page is from a DIFFERENT source, prefix the new one
            if existing_source and existing_source != source_name:
                slug = Path(entity_id).name
                prefixed_id = f"entities/{source_abbr}-{slug}"
                page_path = PAGES_DIR / f"{prefixed_id}.md"
                entity_id = prefixed_id

                # Register for concept aggregation
                base_name = slug
                if base_name not in concept_groups:
                    concept_groups[base_name] = []
                concept_groups[base_name].append(
                    {"id": prefixed_id, "type": entity_type, "name": frontmatter["title"]}
                )
                print(f"  Conflict → prefixed: {prefixed_id}.md", file=sys.stderr)

        if page_path.exists() and not force:
            existing_content = page_path.read_text(encoding="utf-8")
            contradictions = detect_contradictions(entity_id, page_content, existing_content)

            if contradictions:
                contradictions_found.extend(contradictions)
                resolutions = auto_resolve_contradictions(entity_id, contradictions)

                page_content = existing_content + "\n\n## Contradictions Detected\n\n"
                for c in contradictions:
                    ctype = c.get('contradiction_type', 'unknown')
                    sev = c.get('severity', 'medium')
                    existing = c.get('existing_claim', 'N/A')
                    new = c.get('new_claim', 'N/A')
                    page_content += f"- **{ctype}** ({sev}): {existing} → {new}\n"

                if resolutions:
                    page_content += "\n## Resolution\n\n"
                    for i, r in enumerate(resolutions):
                        winner = r.get("winner", "unknown")
                        conf = r.get("confidence", 0.5)
                        reasoning = r.get("reasoning", "")
                        action = r.get("action", "flag")
                        page_content += f"- **Resolved #{i+1}**: {winner} claim accepted ({action}) — confidence {conf:.0%}\n"
                        page_content += f"  - Reasoning: {reasoning}\n"
                        if action == "supersede":
                            page_content += "  - [SUPERSEDED] Old claim marked as superseded.\n"

                if not dry_run:
                    # Incremental: skip if content unchanged
                    new_hash = _content_hash(page_content)
                    old_hash = existing_source_pages.get(entity_id, {}).get("content_hash", "")
                    if new_hash == old_hash:
                        _skipped[0] += 1
                        print(f"  Unchanged: {Path(page_path).name}", file=sys.stderr)
                        continue
                    atomic_write(page_path, _ensure_created_at(page_content))
                f_count, r_count = _count_facts(page_content)
                updated_pages.append({
                    "id": entity_id,
                    "type": entity_type,
                    "name": frontmatter["title"],
                    "path": str(page_path),
                    "contradictions": len(contradictions),
                    "resolutions": len(resolutions),
                    "facts": f_count,
                    "relationships": r_count,
                })
                print(f"  Updated: {Path(page_path).name} ({len(contradictions)} contradictions, {len(resolutions)} resolved)", file=sys.stderr)
            else:
                # No contradictions — semantically fuse new content into
                # existing page instead of overwriting (which would lose the
                # knowledge from previously compiled sources).
                exist_body_match = re.match(
                    r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
                    existing_content, flags=re.DOTALL,
                )
                new_body_match = re.match(
                    r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
                    page_content, flags=re.DOTALL,
                )
                if exist_body_match and new_body_match:
                    exist_body = exist_body_match.group(2)
                    new_body = new_body_match.group(2)
                    fused = llm_fuse_pages(exist_body, new_body, entity_id)
                    if fused is not None:
                        # Reconstruct: use new frontmatter + fused body
                        new_fm = new_body_match.group(1)
                        page_content = "---\n" + new_fm + "\n---\n\n" + fused
                        print(
                            f"  Fused: {Path(page_path).name} "
                            f"(LLM semantic merge, {len(fused)} chars)",
                            file=sys.stderr,
                        )

                if not dry_run:
                    # Incremental: skip if content unchanged
                    new_hash = _content_hash(page_content)
                    old_hash = existing_source_pages.get(entity_id, {}).get("content_hash", "")
                    if new_hash == old_hash:
                        _skipped[0] += 1
                        print(f"  Unchanged: {Path(page_path).name}", file=sys.stderr)
                        continue
                    atomic_write(page_path, _ensure_created_at(page_content))
                f_count, r_count = _count_facts(page_content)
                updated_pages.append({
                    "id": entity_id,
                    "type": entity_type,
                    "name": frontmatter["title"],
                    "path": str(page_path),
                    "facts": f_count,
                    "relationships": r_count,
                })
                print(f"  Updated: {Path(page_path).name} (reinforced)", file=sys.stderr)
        else:
            if not dry_run:
                atomic_write(page_path, _ensure_created_at(page_content))
            f_count, r_count = _count_facts(page_content)
            created_pages.append({
                "id": entity_id,
                "type": entity_type,
                "name": frontmatter["title"],
                "path": str(page_path),
                "facts": f_count,
                "relationships": r_count,
            })
            print(f"  Created: {Path(page_path).name} ({entity_type})", file=sys.stderr)

    all_pages = created_pages + updated_pages
    if not all_pages:
        print("  WARNING: No pages parsed from LLM response! Raw output (500 chars):",
              file=sys.stderr)
        print(f"    {response[:500]}", file=sys.stderr)
        return {"source": source_name, "pages_created": 0, "pages_updated": 0, "pages": []}

    # ── Incremental: track unchanged pages ──
    new_page_ids: set[str] = {p["id"] for p in all_pages}
    skipped_pages = _skipped[0]
    pruned_pages: list[str] = []

    if dry_run:
        # ── Dry-run preview ──
        _print_dry_run_preview(source_name, all_pages, created_pages, updated_pages)
        return {
            "source": source_name,
            "pages_created": len(created_pages),
            "pages_updated": len(updated_pages),
            "pages_skipped": skipped_pages,
            "pages": all_pages,
            "dry_run": True,
        }

    # ── 概念聚合：为每个实体组创建/更新概念页（同名异实保护） ──
    for base_name, instances in concept_groups.items():
        concept_path = CONCEPTS_DIR / f"{base_name}.md"
        instance_links = "\n".join(
            f"- [{inst.get('name', inst['id'])}](/{inst['id']}.md)（来源: {source_name}）"
            for inst in instances
        )
        # Also find existing non-prefixed entities with the same base name
        existing_entity = ENTITIES_DIR / f"{base_name}.md"
        if existing_entity.exists():
            existing_source = ""
            for line in existing_entity.read_text(encoding="utf-8").split("\n"):
                if line.startswith("provenance:"):
                    existing_source = line.replace("provenance:", "").strip()
                    break
            existing_link = (
                f"- [{base_name}](/entities/{base_name}.md)（来源: {existing_source}）"
            )
            if existing_link not in instance_links:
                instance_links = existing_link + "\n" + instance_links

        if concept_path.exists():
            existing = concept_path.read_text(encoding="utf-8")
            new_links = [li for li in instance_links.split("\n") if li not in existing]
            if new_links:
                # Append new instances
                updated_content = existing.rstrip() + "\n\n## 新增实例\n\n" + "\n".join(new_links) + "\n"
                if not dry_run:
                    atomic_write(concept_path, _ensure_created_at(updated_content))
                print(f"  Concept updated: {base_name}.md (+{len(new_links)} instances)", file=sys.stderr)
        else:
            # Use LLM to synthesize a concept page from entity instances
            entity_summaries = []
            for inst in instances:
                ep_path = PAGES_DIR / f"{inst['id']}.md"
                if ep_path.exists():
                    ep_content = ep_path.read_text(encoding="utf-8")
                    overview_lines = []
                    capture = False
                    for line in ep_content.split("\n"):
                        if line.startswith("## 概述") or line.startswith("## Overview"):
                            capture = True
                            continue
                        if capture and line.startswith("## "):
                            break
                        if capture and line.strip():
                            overview_lines.append(line.strip())
                    entity_summaries.append(f"### {inst['name']}\n{' '.join(overview_lines[:3])}")

            synthesis_prompt = f"""综合以下实体实例，生成一个跨文档概念页。

概念: {base_name}
实例列表:
{instance_links}

实例详情:
{chr(10).join(entity_summaries[:3])}

输出原生 OKF v0.1 概念文档（YAML frontmatter + 中文内容）：
---
type: concept
title: {base_name}
description: 跨文档聚合概念
tags: [跨文档聚合]
timestamp: {datetime.now(timezone.utc).isoformat()}
provenance: 跨文档聚合
---

# {base_name}

## 概述
[综合所有实例，提炼通用模式和核心特征，2-4句中文]

## 已知实例
{instance_links}

## 关键特征
[从各实例提炼的共同点和差异性，3-5条中文]

直接输出，不要额外说明。"""
            try:
                concept_content = call_llm(
                    "你是 Wiki 知识聚合助手，综合多个来源的同类实体，生成概念页。",
                    synthesis_prompt,
                )
                normalized = _okf_page_from_model(concept_content.strip(), "跨文档聚合")
                if normalized is not None:
                    concept_content = normalized[0]
                if not dry_run:
                    atomic_write(concept_path, _ensure_created_at(concept_content.strip()))
                print(f"  Concept created: {base_name}.md ({len(instances)} instances)", file=sys.stderr)
            except Exception:
                _log_exc(f"concept synthesis failed for {base_name}")
                fallback = f"""---
type: concept
title: {base_name}
description: 跨文档聚合概念
tags: [跨文档聚合]
timestamp: {datetime.now(timezone.utc).isoformat()}
provenance: 跨文档聚合
---

# {base_name}

## 概述
跨文档概念，聚合自 {source_name}。

## 已知实例
{instance_links}
"""
                if not dry_run:
                    atomic_write(concept_path, _ensure_created_at(fallback))
                print(f"  Concept created (fallback): {base_name}.md", file=sys.stderr)

    # ── Prune stale pages (from this source but not in new compilation) ──
    pruned_pages = _prune_stale_pages(new_page_ids, source_name, dry_run=False)

    update_index(all_pages, source_name)
    update_log(source_name, len(created_pages), "compile")
    update_graph(all_pages, source_name)

    write_audit("compile", {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "pages_skipped": skipped_pages,
        "pages_pruned": len(pruned_pages),
        "contradictions": len(contradictions_found),
        "contradiction_details": contradictions_found[:10],
    })

    if skipped_pages > 0:
        print(f"  ⏭ Skipped: {skipped_pages} pages unchanged", file=sys.stderr)
    if pruned_pages:
        print(f"  🗑 Pruned: {len(pruned_pages)} stale pages", file=sys.stderr)

    return {
        "source": source_name,
        "pages_created": len(created_pages),
        "pages_updated": len(updated_pages),
        "pages_skipped": skipped_pages,
        "pages_pruned": len(pruned_pages),
        "pages": all_pages,
        "contradictions_found": contradictions_found,
    }

def _get_compile_workers() -> int:
    """Get max concurrent compile workers from config, env, or safe default.

    Resolution: CLI --jobs > env LLM_WIKI_COMPILE_WORKERS > config > default 1.
    Caps at 4 to avoid API rate limits unless explicitly overridden.
    """
    import os as _os
    env_val = _os.environ.get("LLM_WIKI_COMPILE_WORKERS", "").strip()
    if env_val:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass

    try:
        from config import get_config
        cfg = get_config()
        compile_cfg = cfg.get("compile", {}) if isinstance(cfg, dict) else {}
        cfg_workers = compile_cfg.get("max_workers", 1)
        if cfg_workers and int(cfg_workers) > 1:
            return min(int(cfg_workers), 8)  # config can go up to 8
    except Exception:
        pass

    return 1  # safe default: serial


def compile_path(
    source_path: str,
    source_type: str = "doc",
    force: bool = False,
    depth: int | None = None,
    dry_run: bool = False,
    mode: str = "llm",
) -> dict:
    """Compile a single source file or every supported file under a directory."""
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if (mode or "").lower() == "agent":
        return create_agent_compile_task(
            source_path,
            source_type=source_type,
            force=force,
            dry_run=dry_run,
            depth=depth,
        )

    if source_type == "auto":
        source_type = infer_source_type(path)

    if path.is_file():
        return compile_source(str(path), source_type=source_type, force=force, dry_run=dry_run)

    if depth is not None and depth < 0:
        raise ValueError("--depth must be >= 0")

    sources = iter_source_files(path, max_depth=depth)
    if not sources:
        return {
            "source": str(path),
            "directory": True,
            "files_found": 0,
            "compiled": [],
            "failed": [],
            "pages_created": 0,
            "pages_updated": 0,
        }

    compiled = []
    failed = []
    pages_created = 0
    pages_updated = 0

    # ── Concurrent workers (default 1 = serial, configurable) ──
    workers = _get_compile_workers()

    if workers > 1 and len(sources) > 1:
        print(
            f"Compiling directory {path} ({len(sources)} files, {workers} workers)...",
            file=sys.stderr,
        )
        print(
            "  WARNING: concurrent workers may cause data loss in index/graph/audit. "
            "Use --jobs 1 for safe compilation.",
            file=sys.stderr,
        )
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    compile_source, str(s), source_type=source_type,
                    force=force, dry_run=dry_run,
                ): s for s in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    result = future.result()
                    compiled.append(result)
                    pages_created += result.get("pages_created", 0)
                    pages_updated += result.get("pages_updated", 0)
                    name = Path(source).name
                    print(
                        f"  ✓ {name}: {result.get('pages_created', 0)} created, "
                        f"{result.get('pages_updated', 0)} updated",
                        file=sys.stderr,
                    )
                except Exception as e:
                    failed.append({"source": str(source), "error": str(e)})
                    print(f"  ✗ {Path(source).name}: {e}", file=sys.stderr)
                    traceback.print_exc()
    else:
        print(f"Compiling directory {path} ({len(sources)} files)...", file=sys.stderr)
        for source in sources:
            try:
                result = compile_source(str(source), source_type=source_type, force=force, dry_run=dry_run)
                compiled.append(result)
                pages_created += result.get("pages_created", 0)
                pages_updated += result.get("pages_updated", 0)
            except Exception as e:
                failed.append({"source": str(source), "error": str(e)})
                print(f"  ERROR: failed to compile {source}: {e}", file=sys.stderr)
                traceback.print_exc()

    return {
        "source": str(path),
        "directory": True,
        "files_found": len(sources),
        "compiled": compiled,
        "failed": failed,
        "pages_created": pages_created,
        "pages_updated": pages_updated,
        "workers": workers if workers > 1 else 1,
    }


def update_log(source_name: str, pages_count: int, operation: str = "compile"):
    """Update the OKF bundle log with a newest-first ISO date entry."""
    log_file = PAGES_DIR / "log.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"## {now}\n* **{operation.title()}**: {source_name}; {pages_count} concepts changed.\n\n"

    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
    else:
        content = "# Wiki Log\n\n"
    heading, _, rest = content.partition("\n\n")
    content = f"{heading}\n\n{entry}{rest}"
    log_file.write_text(content, encoding="utf-8")


def update_graph(pages: list, source_name: str):
    graph_dir = WIKI_DIR / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    entities_file = graph_dir / "entities.json"
    edges_file = graph_dir / "edges.json"

    if entities_file.exists():
        entities = json.loads(entities_file.read_text(encoding="utf-8"))
    else:
        entities = {}

    if edges_file.exists():
        edges_data = json.loads(edges_file.read_text(encoding="utf-8"))
        edges = edges_data.get("edges", edges_data) if isinstance(edges_data, dict) else edges_data
    else:
        edges = []

    now = datetime.now(timezone.utc).isoformat()

    for page in pages:
        eid = page["id"]
        if eid not in entities:
            entities[eid] = {
                "id": eid,
                "type": page["type"],
                "name": page["name"],
                "path": page.get("path", ""),
                "sources": [source_name],
                "confidence": 0.85,
                "created": now,
                "last_confirmed": now,
                "reinforcement_count": 1,
            }
        else:
            if source_name not in entities[eid]["sources"]:
                entities[eid]["sources"].append(source_name)

            entities[eid]["reinforcement_count"] = entities[eid].get("reinforcement_count", 1) + 1
            entities[eid]["confidence"] = min(1.0, 0.85 + 0.05 * entities[eid]["reinforcement_count"])
            entities[eid]["last_confirmed"] = now

    for page in pages:
        page_path = Path(page.get("path", ""))
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            markdown_links = re.findall(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)", content)

            for target in markdown_links:
                target = target.strip().lower().replace(" ", "-")
                if target.endswith(".md"):
                    target = target.lstrip("/")[:-3]
                if target and target != page["id"]:
                    line_context = ""
                    for line in content.split("\n"):
                        line_lower = line.lower()
                        line_normalized = line_lower.replace('-', ' ')
                        if (f"[[{target}" in line_normalized or
                            f"[[{target.replace('-', ' ')}" in line_normalized):
                            line_context = line
                            break

                    edge_type = extract_edge_type(line_context) if line_context else "relates_to"

                    edge = {
                        "source": page["id"],
                        "target": target,
                        "type": edge_type,
                        "weight": 1.0,
                        "source_file": source_name,
                    }

                    existing = [e for e in edges if e["source"] == page["id"] and e["target"] == target]
                    if not existing:
                        edges.append(edge)

    entities_file.write_text(json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8")
    edges_file.write_text(json.dumps({"edges": edges}, indent=2, ensure_ascii=False), encoding="utf-8")


def update_index(pages: list, source_name: str):
    """Regenerate the OKF progressive-disclosure root index."""
    from okf import concept_id, iter_concepts, read_markdown

    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[tuple[str, str, str]]] = {}
    for path in iter_concepts(PAGES_DIR):
        metadata, _, error = read_markdown(path)
        if error:
            continue
        page_type = str(metadata.get("type") or "Reference")
        grouped.setdefault(page_type, []).append(
            (
                concept_id(path, PAGES_DIR),
                str(metadata.get("title") or path.stem),
                str(metadata.get("description") or ""),
            )
        )
    lines = ['---', 'okf_version: "0.1"', '---', '# Wiki Index', '']
    for page_type in sorted(grouped):
        lines.extend([f"## {page_type}", ""])
        for identifier, title, description in sorted(grouped[page_type]):
            suffix = f" - {description}" if description else ""
            lines.append(f"* [{title}](/{identifier}.md){suffix}")
        lines.append("")
    atomic_write(INDEX_FILE, "\n".join(lines))


def _materialize_text_source(text: str, name: str | None = None) -> str:
    """Write raw text to ``.wiki/source/`` as an immutable source file.

    Direct text/stdin input has no source file, so we persist it under the
    wiki's immutable source dir (matching the "Raw Sources — immutable"
    architecture) and return the path. The existing compile pipeline then
    reads it like any other ``.md`` source.
    """
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    source_dir = WIKI_DIR / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = name or f"text-{timestamp}"
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", base).strip("-") or f"text-{timestamp}"
    path = source_dir / f"{safe}.md"
    if path.exists():
        path = source_dir / f"{safe}-{timestamp}.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Wiki compilation')
    parser.add_argument('source', nargs='?', default=None,
                        help='Source file/dir to compile, or "-" to read text from stdin')
    parser.add_argument('--text', dest='text', default=None,
                        help='Compile raw text directly (no source file needed)')
    parser.add_argument('--name', dest='source_name', default=None,
                        help='Name for --text / stdin source (default: text-<timestamp>)')
    parser.add_argument('--type', dest='source_type', default='doc',
                        choices=['auto', 'doc', 'article', 'code', 'conversation'],
                        help='Source type; "auto" infers from file extension (Agent mode recommended)')
    parser.add_argument('--mode', choices=['agent', 'llm'], default=None,
                        help='Compile mode; defaults to configured mode or agent')
    parser.add_argument('--force', action='store_true', help='Force re-compile (overwrite existing pages)')
    parser.add_argument('--dry-run', action='store_true', help='Preview LLM output without writing any files')
    parser.add_argument('--depth', type=int, default=None,
                        help='Directory recursion depth: 0 = direct files only, omit = all subdirectories')
    parser.add_argument('-j', '--jobs', type=int, default=None,
                        help='Max concurrent LLM calls (default: 1, cap: 4)')
    args = parser.parse_args()

    if args.jobs is not None:
        import os as _os
        _os.environ["LLM_WIKI_COMPILE_WORKERS"] = str(max(1, args.jobs))
    config_mode = get_config().get("compile", {}).get("mode", "agent")
    mode = args.mode or config_mode or "agent"

    # Resolve the source: raw --text, stdin ("-"), or an existing file/dir.
    if args.text is not None:
        source_path = _materialize_text_source(args.text, args.source_name)
    elif args.source == "-":
        source_path = _materialize_text_source(sys.stdin.read(), args.source_name)
    elif args.source is None:
        parser.error("provide a source file/dir, --text TEXT, or - (stdin)")
    else:
        source_path = args.source

    result = compile_path(
        source_path,
        source_type=args.source_type,
        force=args.force,
        depth=args.depth,
        dry_run=args.dry_run,
        mode=mode,
    )

    pages_created = result.get('pages_created', 0)
    pages_updated = result.get('pages_updated', 0)
    if result.get("mode") == "agent":
        print(f"\nAgent compile task created for {result['source']}")
        print(f"  → {result['agent_task']}")
        print("  → No configured LLM was called. The Agent should execute this task.")
        if not result.get("readable", True):
            print("  → Source text was not extracted; Agent must inspect it or ask for readable content.")
        return
    if result.get("directory"):
        failed = len(result.get("failed", []))
        prefix = "[Dry-run] " if args.dry_run else ""
        print(
            f"\n{prefix}Compiled {result['source']}: {len(result.get('compiled', []))}/"
            f"{result.get('files_found', 0)} files, {pages_created} pages created, "
            f"{pages_updated} pages updated, {failed} failed"
        )
    else:
        if result.get("dry_run"):
            print(f"\n[Dry-run] {result['source']}: {pages_created} pages would be created, {pages_updated} pages would be updated")
        else:
            print(f"\nCompiled {result['source']}: {pages_created} pages created, {pages_updated} pages updated")
    if not result.get("dry_run"):
        print("  → Updated log.md and graph/entities.json")


if __name__ == "__main__":
    main()
