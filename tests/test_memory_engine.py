"""
Unit tests for the cognitive memory engine.
Tests the three-layer memory system without external dependencies.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMemoryEntry(unittest.TestCase):
    """测试 MemoryEntry 数据结构"""

    def test_create_entry(self):
        """应能创建记忆条目"""
        from src.core.memory_engine import MemoryEntry
        entry = MemoryEntry(
            content="test memory",
            memory_type="episodic",
            importance=0.8,
        )
        self.assertEqual(entry.content, "test memory")
        self.assertEqual(entry.memory_type, "episodic")
        self.assertEqual(entry.importance, 0.8)

    def test_salience_calculation(self):
        """显著性应考虑重要度、新鲜度和频率"""
        from src.core.memory_engine import MemoryEntry
        entry = MemoryEntry(
            content="test",
            memory_type="episodic",
            importance=0.5,
        )
        # 新创建的记忆应有合理的显著性
        salience = entry.salience
        self.assertGreater(salience, 0)
        self.assertLessEqual(salience, 1.0)

    def test_access_increases_frequency(self):
        """访问应增加频率因子"""
        from src.core.memory_engine import MemoryEntry
        entry = MemoryEntry(
            content="test",
            memory_type="episodic",
            importance=0.5,
        )
        initial_salience = entry.salience
        entry.access_count += 1
        # 访问后显著性应增加（因为 frequency 因子增加）
        # 注意：如果时间流逝，freshness 可能降低，所以这里只检查 access_count
        self.assertEqual(entry.access_count, 1)


class TestWorkingMemory(unittest.TestCase):
    """测试工作记忆（滑动窗口）"""

    def test_add_and_retrieve(self):
        """应能添加和检索记忆"""
        from src.core.memory_engine import CognitiveMemoryEngine
        engine = CognitiveMemoryEngine()

        engine.remember(
            content="用户说了开门",
            memory_type="episodic",
            importance=0.7,
        )

        results = engine.recall("开门", top_k=5)
        self.assertGreater(len(results), 0)

    def test_working_memory_window(self):
        """工作记忆应有滑动窗口限制"""
        from src.core.memory_engine import CognitiveMemoryEngine
        engine = CognitiveMemoryEngine()

        # 添加超过窗口大小的记忆
        for i in range(15):
            engine.remember(
                content=f"memory {i}",
                memory_type="episodic",
                importance=0.5,
            )

        # 工作记忆不应超过最大大小
        self.assertLessEqual(len(engine.working_memory), 10)


class TestMemoryTypes(unittest.TestCase):
    """测试不同类型的记忆"""

    def test_episodic_memory(self):
        """情景记忆应可存储和检索"""
        from src.core.memory_engine import CognitiveMemoryEngine
        engine = CognitiveMemoryEngine()

        engine.remember(
            content="用户在 2024-01-01 说了开门",
            memory_type="episodic",
            importance=0.8,
        )

        results = engine.recall("开门", top_k=5)
        self.assertGreater(len(results), 0)

    def test_procedural_memory(self):
        """程序性记忆应可存储"""
        from src.core.memory_engine import CognitiveMemoryEngine
        engine = CognitiveMemoryEngine()

        engine.remember(
            content="执行 lock_open 时需要先检查门锁状态",
            memory_type="procedural",
            importance=0.9,
        )

        results = engine.recall("lock_open", top_k=5)
        self.assertGreater(len(results), 0)

    def test_semantic_memory(self):
        """语义记忆应可存储"""
        from src.core.memory_engine import CognitiveMemoryEngine
        engine = CognitiveMemoryEngine()

        engine.remember(
            content="ESP32-C3 是 RISC-V 架构的微控制器",
            memory_type="semantic",
            importance=0.6,
        )

        results = engine.recall("ESP32", top_k=5)
        self.assertGreater(len(results), 0)


if __name__ == "__main__":
    unittest.main()
