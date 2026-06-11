"""情绪引擎测试"""

import time
import pytest

from src.core.emotion_state import EmotionEngine, EmotionState


class TestEmotionState:
    """EmotionState 数据结构测试"""

    def test_default_state(self):
        """默认状态应为中性基线"""
        state = EmotionState()
        # 中性为 0.5，恐惧/悲伤默认低
        assert state.joy == 0.5
        assert state.fear == 0.1
        assert state.trust == 0.5
        assert state.surprise == 0.0
        assert state.anger == 0.0
        assert state.sadness == 0.1

    def test_to_dict(self):
        """to_dict 应包含所有六维情绪 + 派生状态"""
        state = EmotionState()
        d = state.to_dict()
        for dim in ["joy", "fear", "trust", "surprise", "anger", "sadness"]:
            assert dim in d
        for derived in ["stress", "confidence", "engagement"]:
            assert derived in d

    def test_update_derived(self):
        """update_derived 应正确计算派生状态"""
        state = EmotionState(joy=0.8, trust=0.8, fear=0.6, anger=0.4, sadness=0.2)
        state.update_derived()
        assert state.stress == pytest.approx((0.6 + 0.4 + 0.2) / 3, abs=0.01)
        assert state.confidence == pytest.approx((0.8 + 0.8) / 2, abs=0.01)
        assert state.engagement == pytest.approx((0.8 + 0.0) / 2, abs=0.01)


class TestEmotionEngine:
    """EmotionEngine 事件驱动测试"""

    def test_on_success_increases_joy(self):
        """成功事件应增加喜悦"""
        engine = EmotionEngine()
        initial_joy = engine.state.joy
        engine.on_success()
        assert engine.state.joy > initial_joy

    def test_on_failure_increases_sadness(self):
        """失败事件应增加悲伤"""
        engine = EmotionEngine()
        initial_sadness = engine.state.sadness
        engine.on_failure()
        assert engine.state.sadness > initial_sadness

    def test_on_failure_adds_confidence_penalty(self):
        """失败事件应累积置信度惩罚"""
        engine = EmotionEngine()
        engine.on_failure()
        assert engine.state.confidence_penalty > 0

    def test_on_repeated_failure_additive_anger(self):
        """重复失败应累加愤怒（非覆盖）"""
        engine = EmotionEngine()
        engine.on_repeated_failure(count=2)
        anger_after_2 = engine.state.anger
        engine.on_repeated_failure(count=1)
        assert engine.state.anger > anger_after_2

    def test_decay_reduces_emotions(self):
        """时间衰减应降低情绪强度"""
        engine = EmotionEngine()
        engine.on_success()
        joy_before = engine.state.joy

        # 手动推进时间
        engine._last_tick = time.time() - 300  # 5分钟前
        engine.tick()

        assert engine.state.joy < joy_before

    def test_get_response_style_modifier(self):
        """响应风格修改器应返回预期的键"""
        engine = EmotionEngine()
        style = engine.get_response_style_modifier()
        assert "verbosity" in style
        assert "caution" in style
        assert "assertiveness" in style
        assert "detail" in style
        assert "risk_tolerance" in style

    def test_should_ask_confirmation_default(self):
        """默认状态不应触发确认"""
        engine = EmotionEngine()
        assert engine.should_ask_confirmation() is False

    def test_should_ask_confirmation_high_fear(self):
        """高恐惧应触发确认"""
        engine = EmotionEngine()
        engine.state.fear = 0.8
        engine.state.confidence = 0.2
        assert engine.should_ask_confirmation() is True
