"""元认知引擎测试"""

import pytest

from src.core.meta_cognition import (
    MetaCognition, ConfidenceLevel, Strategy,
    ConfidenceAssessment, StrategyDecision,
)


class TestConfidenceLevel:
    """置信度等级常量测试"""

    def test_levels_are_strings(self):
        """置信度等级应为字符串常量"""
        assert ConfidenceLevel.HIGH == "high"
        assert ConfidenceLevel.MEDIUM == "medium"
        assert ConfidenceLevel.LOW == "low"
        assert ConfidenceLevel.UNCERTAIN == "uncertain"


class TestMetaCognition:
    """置信度评估和策略选择测试"""

    def test_high_confidence_on_cache_hit(self):
        """缓存命中应产生高置信度"""
        mc = MetaCognition()
        assessment = mc.evaluate_confidence(
            query="打开灯",
            cache_hit=True,
            cache_similarity=0.98,
        )
        assert assessment.score > 0.8
        assert assessment.level == ConfidenceLevel.HIGH

    def test_low_confidence_no_context(self):
        """无上下文应产生低置信度"""
        mc = MetaCognition()
        assessment = mc.evaluate_confidence(
            query="完全未知的指令 xyz",
            cache_hit=False,
        )
        assert assessment.score < 0.6

    def test_cache_hit_semantic_match(self):
        """语义匹配缓存命中应产生中高置信度"""
        mc = MetaCognition()
        assessment = mc.evaluate_confidence(
            query="开灯",
            cache_hit=True,
            cache_similarity=0.93,
        )
        assert assessment.score > 0.5

    def test_correction_history_reduces_confidence(self):
        """纠正历史应降低置信度"""
        mc = MetaCognition()
        # 需要有一些基础分数，纠正才能体现差异
        a1 = mc.evaluate_confidence(
            query="test", cache_hit=True, cache_similarity=0.93,
        )
        a2 = mc.evaluate_confidence(
            query="test", cache_hit=True, cache_similarity=0.93,
            has_correction_history=True,
        )
        assert a2.score < a1.score

    def test_select_strategy_high_confidence_cache(self):
        """高置信度 + 缓存命中应选择 CACHE 策略"""
        mc = MetaCognition()
        assessment = ConfidenceAssessment(
            level=ConfidenceLevel.HIGH,
            score=0.95,
            factors={"cache": 0.95},
            reasoning="test",
            should_confirm=False,
        )
        decision = mc.select_strategy(
            query="打开灯",
            confidence=assessment,
            cache_hit=True,
        )
        assert decision.strategy == Strategy.CACHE

    def test_select_strategy_low_confidence(self):
        """低置信度应选择 ASK_USER 策略"""
        mc = MetaCognition()
        assessment = ConfidenceAssessment(
            level=ConfidenceLevel.UNCERTAIN,
            score=0.15,
            factors={},
            reasoning="test",
            should_confirm=True,
        )
        decision = mc.select_strategy(
            query="模糊指令",
            confidence=assessment,
        )
        assert decision.strategy == Strategy.ASK_USER

    def test_select_strategy_returns_decision(self):
        """策略选择应返回 StrategyDecision"""
        mc = MetaCognition()
        assessment = mc.evaluate_confidence(
            query="开灯",
            cache_hit=True,
            cache_similarity=0.98,
        )
        decision = mc.select_strategy(
            query="开灯",
            confidence=assessment,
            cache_hit=True,
        )
        assert isinstance(decision, StrategyDecision)
        assert decision.strategy in [
            Strategy.CACHE, Strategy.RULE, Strategy.LLM,
            Strategy.HYBRID, Strategy.ASK_USER,
        ]
        assert decision.estimated_latency_ms >= 0
