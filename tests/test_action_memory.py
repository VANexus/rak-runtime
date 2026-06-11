"""ActionMemory 测试"""

import pytest
from unittest.mock import MagicMock, patch
from src.core.action_memory import ActionMemory, ActionTrajectory


class TestActionTrajectory:
    """轨迹数据结构测试"""

    def test_success_rate_default(self):
        """未重放时成功率应为 1.0"""
        t = ActionTrajectory(query="test", action="nod", params_json="{}",
                             context={}, result={})
        assert t.success_rate() == 1.0

    def test_success_rate_with_replays(self):
        """重放后成功率应正确计算"""
        t = ActionTrajectory(query="test", action="nod", params_json="{}",
                             context={}, result={})
        t.replay_count = 10
        t.success_after_replay = 8
        assert t.success_rate() == 0.8


class TestActionMemory:
    """动作记忆测试"""

    def test_replay_empty(self):
        """空记忆应返回 None"""
        mem = ActionMemory()
        assert mem.replay("开灯", ["light_on"]) is None

    def test_exact_match_replays_without_llm(self):
        """精确匹配应直接重放（不需要 LLM）"""
        mem = ActionMemory()
        mem.record("开灯", "light_on", "{}", {}, {"status": "ok"})
        result = mem.replay("开灯", ["light_on"])
        assert result is not None
        assert result["action"] == "light_on"
        assert result["source"] == "action_memory_exact"

    def test_replay_action_unavailable(self):
        """动作不可用时应返回 None"""
        mem = ActionMemory()
        mem.record("开灯", "light_on", "{}", {}, {"status": "ok"})
        result = mem.replay("开灯", ["lock_open"])
        assert result is None

    def test_record_and_stats(self):
        """记录后统计应正确"""
        mem = ActionMemory()
        mem.record("test", "nod", "{}", {}, {})
        stats = mem.get_stats()
        assert stats["total_trajectories"] == 1

    def test_context_building(self):
        """应能构建评估上下文"""
        mem = ActionMemory()
        mem.record("开灯", "light_on", "{}", {"device_id": "light-01"}, {})
        # 候选筛选应能找到
        candidates = [
            (mem._query_similarity("开灯", t.query), t)
            for t in mem._trajectories
            if mem._query_similarity("开灯", t.query) > 0.5
        ]
        assert len(candidates) > 0
