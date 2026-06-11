"""SafetyGovernance 测试"""

import pytest
from unittest.mock import MagicMock, patch
from src.core.safety_governance import SafetyGovernance


class TestSafetyGovernance:
    """LLM 驱动的安全治理测试"""

    def test_emergency_stop_always_allowed(self):
        """emergency_stop 应永远允许（唯一的硬约束）"""
        sg = SafetyGovernance()
        allowed, _ = sg.check("emergency_stop")
        assert allowed is True

    def test_no_llm_allows_by_default(self):
        """LLM 不可用时应默认允许（不阻塞）"""
        sg = SafetyGovernance()
        sg._llm_client = None
        allowed, _ = sg.check("light_on")
        assert allowed is True

    def test_device_state_update(self):
        """设备状态应能更新"""
        sg = SafetyGovernance()
        sg.update_device_state("lock-01", {"locked": True, "online": True})
        assert "lock-01" in sg._device_states
        assert sg._device_states["lock-01"]["locked"] is True

    def test_action_recording(self):
        """操作应被记录"""
        sg = SafetyGovernance()
        sg.record_action("light_on", "light-01")
        sg.record_action("lock_open", "lock-01")
        assert len(sg._action_history) == 2

    def test_context_building(self):
        """应能构建安全评估上下文"""
        sg = SafetyGovernance()
        sg.update_device_state("lock-01", {"locked": False})
        sg.record_action("lock_open", "lock-01")
        context = sg._build_context("lock_close", "锁门", "lock-01", {})
        assert "lock_close" in context
        assert "锁门" in context
        assert "lock-01" in context
        assert "最近操作历史" in context

    def test_stats(self):
        """统计应包含必要字段"""
        sg = SafetyGovernance()
        sg.check("light_on")
        stats = sg.get_stats()
        assert "total_checks" in stats
        assert "total_blocks" in stats
        assert stats["total_checks"] == 1

    def test_violation_recording(self):
        """违规应被记录"""
        sg = SafetyGovernance()
        sg.learn_from_violation("lock_close", "重复锁定")
        stats = sg.get_stats()
        assert len(stats["recent_violations"]) == 1
