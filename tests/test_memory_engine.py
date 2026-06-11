"""三层记忆引擎测试"""

import time
import pytest

from src.core.memory_engine import (
    CognitiveMemoryEngine,
    WorkingMemory,
    ShortTermMemory,
    LongTermMemory,
    MemoryEntry,
)


class TestWorkingMemory:
    """工作记忆（滑动窗口）测试"""

    def test_add_and_access(self):
        """添加后应能通过 items 访问"""
        wm = WorkingMemory(max_items=10)
        entry = MemoryEntry(
            id="test-1", content="打开灯", memory_type="action",
            layer="working", importance=0.8,
        )
        wm.add(entry)
        assert "test-1" in wm.items
        assert wm.items["test-1"].content == "打开灯"

    def test_max_items_eviction(self):
        """超过最大条目数应淘汰最旧的"""
        wm = WorkingMemory(max_items=3)
        for i in range(5):
            wm.add(MemoryEntry(
                id=f"m-{i}", content=f"item {i}", memory_type="test",
                layer="working", importance=0.5,
            ))
        assert len(wm.items) == 3
        assert "m-0" not in wm.items
        assert "m-1" not in wm.items
        assert "m-4" in wm.items

    def test_clear(self):
        """clear 应清空所有条目"""
        wm = WorkingMemory(max_items=10)
        wm.add(MemoryEntry(id="a", content="a", memory_type="test", layer="working"))
        wm.clear()
        assert len(wm.items) == 0


class TestShortTermMemory:
    """短期记忆（LRU）测试"""

    def test_lru_eviction(self):
        """LRU 淘汰最久未访问的条目"""
        stm = ShortTermMemory(max_items=3)
        for i in range(5):
            stm.add(MemoryEntry(
                id=f"s-{i}", content=f"short {i}", memory_type="test",
                layer="short_term", importance=0.5,
            ))
        assert len(stm.items) == 3
        assert "s-0" not in stm.items
        assert "s-4" in stm.items

    def test_get_recent(self):
        """get_recent 应返回最近 N 条"""
        stm = ShortTermMemory(max_items=10)
        for i in range(5):
            stm.add(MemoryEntry(
                id=f"s-{i}", content=f"item {i}", memory_type="test",
                layer="short_term",
            ))
        recent = stm.get_recent(3)
        assert len(recent) == 3
        assert recent[-1].id == "s-4"


class TestMemoryEntry:
    """MemoryEntry 数据结构测试"""

    def test_salience_decreases_with_age(self):
        """显著性应随时间降低"""
        entry = MemoryEntry(
            id="old", content="old memory", memory_type="test",
            layer="long_term", importance=0.8, created_at=time.time() - 7200,
        )
        fresh = MemoryEntry(
            id="new", content="new memory", memory_type="test",
            layer="long_term", importance=0.8,
        )
        assert fresh.salience > entry.salience

    def test_salience_increases_with_access(self):
        """访问应增加显著性"""
        entry = MemoryEntry(
            id="t", content="test", memory_type="test", layer="long_term", importance=0.5,
        )
        initial = entry.salience
        for _ in range(10):
            entry.touch()
        assert entry.salience > initial


class TestCognitiveMemoryEngine:
    """统一记忆引擎测试"""

    def test_remember_and_recall(self):
        """记住后应能召回"""
        engine = CognitiveMemoryEngine()
        engine.remember(
            content="用户喜欢简洁回复",
            memory_type="preference",
            importance=0.9,
        )
        results = engine.recall("简洁")
        assert len(results) > 0

    def test_remember_with_metadata(self):
        """记住时应支持元数据"""
        engine = CognitiveMemoryEngine()
        engine.remember(
            content="灯已打开",
            memory_type="episodic",
            importance=0.7,
            metadata={"device": "light-01", "action": "light_on"},
        )
        results = engine.recall("灯")
        assert len(results) > 0

    def test_working_memory_is_used(self):
        """新记忆应先进入工作记忆"""
        engine = CognitiveMemoryEngine()
        engine.remember(content="test", memory_type="test")
        assert len(engine.working.items) > 0
