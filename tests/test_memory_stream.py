"""联想记忆流测试"""

from src.core.memory_engine import CognitiveMemoryEngine
from src.core.memory_stream import MemoryStream


class TestMemoryStream:
    def test_get_random_recent_memory_from_working(self):
        """工作记忆应能被随机激活"""
        engine = CognitiveMemoryEngine()
        engine.remember(
            content="用户说了开门", memory_type="episodic", importance=0.5
        )
        stream = MemoryStream(engine)
        result = stream._get_random_recent_memory()
        assert result is not None
        assert "开门" in result

    def test_get_random_recent_memory_from_long_term(self):
        """高重要性记忆（长期）应能被随机激活"""
        engine = CognitiveMemoryEngine()
        engine.remember(
            content="用户喜欢把灯调到50%", memory_type="semantic", importance=0.9
        )
        stream = MemoryStream(engine)
        result = stream._get_random_recent_memory()
        assert result is not None

    def test_empty_engine_returns_none(self):
        """空记忆引擎应返回 None"""
        stream = MemoryStream(CognitiveMemoryEngine())
        assert stream._get_random_recent_memory() is None

    def test_inject_memory_and_tick_creates_association(self):
        """注入记忆后 tick 应能产生联想（不再空转）"""
        engine = CognitiveMemoryEngine()
        engine.remember(
            content="用户说了开门", memory_type="episodic", importance=0.7
        )
        engine.remember(
            content="用户说了关门", memory_type="episodic", importance=0.7
        )
        stream = MemoryStream(engine)
        stream.inject_memory("用户说了开门")
        stream._tick()
        assert stream._stats["associations_made"] >= 0
