"""PromptEvolution 测试"""

import pytest
from src.core.prompt_evolution import PromptEvolution


class TestPromptEvolution:
    """提示词进化测试"""

    def test_add_tactical(self):
        """战术指南应能添加"""
        pe = PromptEvolution()
        pe.add_tactical("设备离线时不要尝试控制")
        stats = pe.get_stats()
        assert stats["tactical"] == 1

    def test_add_strategic(self):
        """战略指南应能添加"""
        pe = PromptEvolution()
        pe.add_strategic("始终在执行前验证设备状态")
        stats = pe.get_stats()
        assert stats["strategic"] == 1

    def test_tactical_expires(self):
        """战术指南成功后应过期"""
        pe = PromptEvolution()
        pe.add_tactical("test guideline", ttl_hits=3)
        for _ in range(4):
            pe.on_success("test guideline")
        relevant = pe.get_relevant("test guideline")
        assert len(relevant) == 0

    def test_strategic_never_expires(self):
        """战略指南不应过期"""
        pe = PromptEvolution()
        pe.add_strategic("safety first")
        for _ in range(100):
            pe.on_success("safety first")
        relevant = pe.get_relevant("safety")
        assert len(relevant) > 0

    def test_get_relevant(self):
        """应返回相关指南"""
        pe = PromptEvolution()
        pe.add_strategic("开灯时检查亮度")
        pe.add_strategic("锁门时确认状态")
        relevant = pe.get_relevant("帮我开灯")
        assert len(relevant) > 0

    def test_stats(self):
        """统计应包含必要字段"""
        pe = PromptEvolution()
        stats = pe.get_stats()
        assert "total_guidelines" in stats
        assert "tactical" in stats
        assert "strategic" in stats
