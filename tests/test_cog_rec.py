"""CogRec 引擎测试"""

import pytest
from src.core.cog_rec import CogRecEngine, Rule


class TestCogRec:
    """CogRec 规则引擎测试"""

    def test_match_empty(self):
        """空规则库应返回 None"""
        engine = CogRecEngine()
        assert engine.match("开灯", ["light_on"]) is None

    def test_learn_and_match(self):
        """学习规则后应能匹配"""
        engine = CogRecEngine()
        engine.learn_from_success("开灯", "light_on")
        result = engine.match("开灯", ["light_on"])
        assert result is not None
        assert result["action"] == "light_on"
        assert result["source"] == "cogrec_exact"

    def test_substring_match(self):
        """子串匹配应生效"""
        engine = CogRecEngine()
        engine.learn_from_success("帮我开灯", "light_on")
        result = engine.match("请帮我开灯好吗", ["light_on"])
        assert result is not None
        assert result["action"] == "light_on"

    def test_action_not_in_available(self):
        """动作不在可用列表时应返回 None"""
        engine = CogRecEngine()
        engine.learn_from_success("开灯", "light_on")
        result = engine.match("开灯", ["lock_open", "nod"])
        assert result is None

    def test_correction_higher_confidence(self):
        """纠正规则应有更高置信度"""
        engine = CogRecEngine()
        engine.learn_from_success("开灯", "light_on")
        engine.learn_from_correction("开灯", "light_on", "light_off")
        result = engine.match("开灯", ["light_on", "light_off"])
        assert result["action"] == "light_off"
        assert result["confidence"] > 0.9

    def test_stats(self):
        """统计应包含必要字段"""
        engine = CogRecEngine()
        engine.learn_from_success("test", "nod")
        stats = engine.get_stats()
        assert "total_rules" in stats
        assert "rule_hit_rate" in stats
        assert stats["total_rules"] == 1
