"""Tests for consolidate.py — memory lifecycle and retention decay."""

import json
import math
import os
from pathlib import Path

import pytest

import consolidate


class TestRetentionDecay:
    def test_decay_formula_correct(self):
        days = 30
        s = 130  # project half-life
        retention = math.exp(-days / s)
        assert 0.7 < retention < 0.85  # roughly e^(-0.23)

    def test_fast_decay_for_bugs(self):
        days = 14
        s = 20  # bug half-life
        retention = math.exp(-days / s)
        assert retention < 0.5  # bugs decay fast

    def test_slow_decay_for_architecture(self):
        days = 30
        s = 260  # architecture half-life
        retention = math.exp(-days / s)
        assert retention > 0.85  # architecture decays slowly

    def test_decay_constants_match_spec(self):
        assert consolidate.DECAY_S_VALUES["architecture"] == 260
        assert consolidate.DECAY_S_VALUES["bug"] == 20
        assert consolidate.DECAY_S_VALUES["preference"] == 527


class TestPromoteWorkingToEpisodic:
    def test_requires_minimum_observations(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            result = consolidate.promote_working_to_episodic()
            assert result == 0
        finally:
            os.chdir(old)

    def test_promotes_when_enough_observations(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            obs = []
            for i in range(5):
                obs.append({
                    "id": f"obs-{i}",
                    "content": f"Observation {i}",
                    "source": "test",
                    "entity_ids": ["test-entity"],
                    "timestamp": "2024-04-01T10:00:00Z",
                    "confidence": 0.5,
                })
            working_path = Path(".wiki") / "memory" / "working.json"
            working_path.write_text(json.dumps(obs))

            result = consolidate.promote_working_to_episodic()
            assert result >= 5

            episodic_path = Path(".wiki") / "memory" / "episodic.json"
            assert episodic_path.exists()
            episodes = json.loads(episodic_path.read_text())
            assert len(episodes) >= 1
        finally:
            os.chdir(old)


class TestApplyRetentionDecay:
    def test_archives_deeply_decayed_facts(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            semantic = [{
                "id": "fact-old",
                "claim": "Old claim",
                "entity_id": "old-bug",
                "confidence": 0.3,
                "sources": ["ep-1"],
                "last_confirmed": "2020-01-01T00:00:00Z",
                "reinforcements": 0,
                "contradictions": [],
                "status": "active",
            }]
            sem_path = Path(".wiki") / "memory" / "semantic.json"
            sem_path.write_text(json.dumps(semantic))

            result = consolidate.apply_retention_decay()
            assert result["archived"] >= 1
        finally:
            os.chdir(old)

    def test_preserves_recent_facts(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            from datetime import datetime, timezone
            recent = datetime.now(timezone.utc).isoformat()
            semantic = [{
                "id": "fact-recent",
                "claim": "Recent claim",
                "entity_id": "recent-arch",
                "confidence": 0.9,
                "sources": ["ep-2"],
                "last_confirmed": recent,
                "reinforcements": 0,
                "contradictions": [],
                "status": "active",
            }]
            sem_path = Path(".wiki") / "memory" / "semantic.json"
            sem_path.write_text(json.dumps(semantic))

            result = consolidate.apply_retention_decay()
            assert result["archived"] == 0
        finally:
            os.chdir(old)


class TestDetectProceduralPatterns:
    def test_requires_minimum_facts(self, wiki_dir):
        old = os.getcwd()
        os.chdir(wiki_dir)
        try:
            patterns = consolidate.detect_procedural_patterns()
            assert patterns == []
        finally:
            os.chdir(old)
