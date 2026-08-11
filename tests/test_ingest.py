"""Tests for compile_v2.py — source compilation and sensitive data filtering."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import compile_v2 as ingest
import pytest


class TestFilterSensitive:
    def test_redacts_api_keys(self):
        content = "My API key is sk-abc123def456ghi789jkl012mno345pqr678stu"
        filtered = ingest.strip_sensitive(content)
        assert "sk-" not in filtered
        assert "REDACTED" in filtered

    def test_redacts_github_tokens(self):
        content = "Token: ghp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        filtered = ingest.strip_sensitive(content)
        assert "ghp_" not in filtered
        assert "REDACTED" in filtered

    def test_redacts_passwords(self):
        content = "database password=supersecret123 connection"
        filtered = ingest.strip_sensitive(content)
        assert "supersecret123" not in filtered

    def test_redacts_emails(self):
        content = "Contact alice@example.com or bob@company.co.uk"
        filtered = ingest.strip_sensitive(content)
        assert "alice@example.com" not in filtered
        assert "bob@company.co.uk" not in filtered

    def test_redacts_private_keys(self):
        content = (
            "-----BEGIN RSA PRIVATE KEY-----\nMIICXAIBAAKBgQC...\n-----END RSA PRIVATE KEY-----"
        )
        filtered = ingest.strip_sensitive(content)
        assert "PRIVATE KEY" not in filtered

    def test_preserves_harmless_content(self):
        content = "The Redis version is 7.0 and runs on port 6379."
        filtered = ingest.strip_sensitive(content)
        assert "Redis" in filtered
        assert "7.0" in filtered


class TestIngestSource:
    def test_domain_expert_routing_is_content_driven(self):
        legal = ingest.match_domain_experts(
            "第一条 本条例适用于本行政区域。经营者不得违反本规定，处罚如下。"
        )
        assert legal[0]["id"] == "legal"

        mixed = ingest.match_domain_experts(
            "课程大纲：学员完成模块与考核。研究方法包括实验、公式和变量定义。"
        )
        assert {item["id"] for item in mixed} >= {"curriculum", "academic"}

    @pytest.mark.parametrize(
        ("source_name", "content"),
        [
            (
                "七年级数学课本.pdf",
                "本章知识点包括一元一次方程的定义、例题、习题和易错点。",
            ),
            (
                "2026期末试卷.pdf",
                "选择题第1题，题干与选项如下。答案A，解析考查函数的知识点。",
            ),
            (
                "physics-textbook.pdf",
                "Each chapter contains worked examples, prerequisite knowledge points, "
                "exercises, and common mistakes.",
            ),
            (
                "初中语文学习资料.md",
                "# 目录\n\n## 文言文\n\n包含原文、注解、通假字、特殊句式和逐句翻译。",
            ),
            (
                "英语复习资料.md",
                "# Unit 3\n\n## 单词表\n\n单词、音标、词性、释义、固定搭配和例句。",
            ),
        ],
    )
    def test_study_material_expert_routes_textbooks_and_exams(self, source_name, content):
        matches = ingest.match_domain_experts(content, source_name)

        assert "study_material" in {item["id"] for item in matches}

    def test_study_material_strong_filename_signal_routes_without_preview_text(self):
        matches = ingest.match_domain_experts("", "七年级生物课本.pdf")

        assert matches[0]["id"] == "study_material"

    def test_study_material_filename_signal_survives_other_high_frequency_signals(self):
        content = "数据 指标 统计 样本 数据源 " * 200

        matches = ingest.match_domain_experts(content, "七年级地理电子课本.md")

        assert "study_material" in {item["id"] for item in matches}

    def test_study_material_guidance_builds_question_knowledge_mapping(self):
        guidance = ingest.build_domain_expert_guidance(
            "试卷包含题号、题干、选项、答案、解析、考点和易错点。",
            "九年级数学期末试卷.pdf",
        )

        assert "知识学习与课本试卷解析专家" in guidance
        assert "题目页链接知识点" in guidance
        assert "知识点页反向汇总例题/真题" in guidance
        assert "来源追溯" in guidance
        assert "一个或多个页码" in guidance
        assert "禁止机械地一页一知识点" in guidance
        assert "待核验" in guidance
        assert "对应原图" in guidance
        assert "不得伪造官方解析" in guidance

    def test_study_material_guidance_preserves_whole_blocks_and_search_tags(self):
        guidance = ingest.build_domain_expert_guidance(
            "# 目录\n\n第一章 力\n\n## 牛顿第二定律\nF=ma，例题与推导如下。",
            "八年级物理学习资料.md",
        )

        assert "目录导航页" in guidance
        assert "目录项→知识块" in guidance
        assert "完整知识块" in guidance
        assert "跨标题、跨相邻页" in guidance
        assert "成立条件、符号/变量、单位、适用范围" in guidance
        assert "不得只摘公式而丢掉条件" in guidance
        assert "4–8 个去重 tags" in guidance
        assert "内容类型/知识点" in guidance
        assert "主题/一元一次方程" in guidance
        assert "无区分度标签" in guidance

    def test_study_material_guidance_handles_vocabulary_and_classical_chinese(self):
        guidance = ingest.build_domain_expert_guidance(
            "单词表包含音标、词性、释义和例句。文言文包含通假字和古今异义。",
            "语文英语知识清单.md",
        )

        assert "不要默认一词一页" in guidance
        assert "可整体复习和筛选的词表知识块" in guidance
        assert "逐句对齐原文、断句、读音、注解和译文" in guidance
        assert "通假字、古今异义、一词多义、词类活用、特殊句式" in guidance
        assert "注解必须绑定具体原句" in guidance

    @pytest.mark.parametrize(
        "line",
        [
            "- 先修知识：[一元一次方程](/concepts/linear-equation.md)",
            "- 前置知识：[整式运算](/concepts/algebra.md)",
            "- prerequisite: [fractions](/concepts/fractions.md)",
        ],
    )
    def test_study_prerequisite_links_become_dependency_edges(self, line):
        assert ingest.extract_edge_type(line) == "depends_on"

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("财务预算按科目核算成本，利润表披露毛利和净利润。", "finance"),
            ("运营SOP规定工单履约、排班、服务水平和异常处理。", "operations"),
            ("PRD包含用户故事、功能优先级、版本和验收标准。", "product"),
            ("采购订单连接供应商、库存、仓储、物流和交期。", "supply_chain"),
            ("临床指南说明药物剂量、适应症、禁忌症和不良反应。", "healthcare"),
            ("指标口径包含公式、维度、数据源、时间窗和数据质量。", "data"),
        ],
    )
    def test_major_business_domain_routes(self, content, expected):
        matches = ingest.match_domain_experts(content)
        assert expected in {item["id"] for item in matches}

    def test_agent_mode_creates_task_without_llm_call(self, wiki_dir, monkeypatch):
        def fail_call_llm(*_args, **_kwargs):
            raise AssertionError("Agent mode must not call configured LLM")

        monkeypatch.setattr(ingest, "call_llm", fail_call_llm)
        monkeypatch.setattr(ingest, "WIKI_DIR", Path(wiki_dir) / ".wiki")
        monkeypatch.setattr(ingest, "PAGES_DIR", Path(wiki_dir) / ".wiki" / "pages")
        monkeypatch.setattr(ingest, "ENTITIES_DIR", Path(wiki_dir) / ".wiki" / "pages" / "entities")
        monkeypatch.setattr(ingest, "CONCEPTS_DIR", Path(wiki_dir) / ".wiki" / "pages" / "concepts")
        monkeypatch.setattr(ingest, "INDEX_FILE", Path(wiki_dir) / ".wiki" / "pages" / "index.md")
        monkeypatch.setattr(ingest, "SCHEMA_PATH", Path(wiki_dir) / ".wiki" / "schema.md")

        src = Path(wiki_dir) / "source.txt"
        src.write_text("Project uses Redis for caching.", encoding="utf-8")

        result = ingest.compile_path(str(src), source_type="auto", mode="agent")

        task_path = Path(result["agent_task"])
        assert result["mode"] == "agent"
        assert result["needs_agent"] is True
        assert task_path.exists()
        task = task_path.read_text(encoding="utf-8")
        assert "Do not call the configured LLM API" in task
        assert "领域专家路由" in task
        assert "固定页数" in task

    @patch("compile_v2.call_llm")
    def test_ingests_text_file(self, mock_call_llm, wiki_dir):
        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "source.txt"
        src.write_text("Project uses Redis for caching. File at src/auth.py.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            # Need to update paths in compile_v2 temporarily for the test to use wiki_dir
            ingest.WIKI_DIR = Path(wiki_dir) / ".wiki"
            ingest.PAGES_DIR = ingest.WIKI_DIR / "pages"
            ingest.ENTITIES_DIR = ingest.PAGES_DIR / "entities"
            ingest.CONCEPTS_DIR = ingest.PAGES_DIR / "concepts"
            ingest.INDEX_FILE = ingest.PAGES_DIR / "index.md"

            result = ingest.compile_source(str(src))
            assert result["source"] == "source.txt"
            assert result["pages_created"] >= 0
        finally:
            os.chdir(old_cwd)

    def test_handles_missing_file(self, wiki_dir):
        with pytest.raises(FileNotFoundError):
            ingest.compile_source("/nonexistent/path.txt")

    @patch("compile_v2.call_llm")
    def test_updates_entities_json(self, mock_call_llm, wiki_dir):
        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "readme.md"
        src.write_text("# Auth Service\n")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            ingest.WIKI_DIR = Path(wiki_dir) / ".wiki"
            ingest.PAGES_DIR = ingest.WIKI_DIR / "pages"
            ingest.ENTITIES_DIR = ingest.PAGES_DIR / "entities"
            ingest.CONCEPTS_DIR = ingest.PAGES_DIR / "concepts"
            ingest.INDEX_FILE = ingest.PAGES_DIR / "index.md"

            ingest.compile_source(str(src))

            entities_path = Path(wiki_dir) / ".wiki" / "graph" / "entities.json"
            data = json.loads(entities_path.read_text())
            assert isinstance(data, dict)
            assert len(data) > 0
        finally:
            os.chdir(old_cwd)

    @patch("compile_v2.call_llm")
    def test_logs_to_audit_trail(self, mock_call_llm, wiki_dir):
        mock_call_llm.return_value = "---\nid: auth-service\ntype: project\nname: Auth Service\n---\n\n# Auth Service\n===PAGE_END==="

        src = Path(wiki_dir) / "notes.txt"
        src.write_text("Important: Redis config for auth service.")

        old_cwd = os.getcwd()
        os.chdir(wiki_dir)
        try:
            ingest.WIKI_DIR = Path(wiki_dir) / ".wiki"
            ingest.PAGES_DIR = ingest.WIKI_DIR / "pages"
            ingest.ENTITIES_DIR = ingest.PAGES_DIR / "entities"
            ingest.CONCEPTS_DIR = ingest.PAGES_DIR / "concepts"
            ingest.INDEX_FILE = ingest.PAGES_DIR / "index.md"

            ingest.compile_source(str(src))

            audit_path = Path(wiki_dir) / ".wiki" / "audit.json"
            assert audit_path.exists()
            entries = json.loads(audit_path.read_text())
            assert len(entries) > 0
            assert entries[-1]["operation"] == "compile"
        finally:
            os.chdir(old_cwd)
