"""记忆压缩测试：向量聚类合并 + 前缀兜底 + 索引清理（P3-3）"""

import pytest

from src.core.memory_engine import CognitiveMemoryEngine
from src.core.sleep_consolidation import SleepConsolidation


def _engine_with_memories():
    engine = CognitiveMemoryEngine()
    # 近重复：向量路径应合并（importance ≥0.8 才路由进长期层）
    engine.remember("用户喜欢把灯调到50%亮度", memory_type="semantic", importance=0.90)
    engine.remember("用户喜欢把灯调到50%", memory_type="semantic", importance=0.82)
    engine.remember("用户喜欢把灯调到50%亮", memory_type="semantic", importance=0.81)
    # 不相似：必须保留
    engine.remember("今天天气很好适合散步", memory_type="episodic", importance=0.85)
    return engine


class TestVectorCompression:
    def test_near_duplicates_merged(self):
        """近重复记忆应被合并，且只保留最重要的一条"""
        engine = _engine_with_memories()
        assert len(engine.long_term.items) == 4

        sc = SleepConsolidation(memory_engine=engine)
        compressed = sc._compress_memories()

        assert compressed >= 1
        assert len(engine.long_term.items) <= 3
        # 保留下来的应是组内重要度最高的一条
        survivors = [e.content for e in engine.long_term.items.values()
                     if "灯" in e.content]
        assert survivors == ["用户喜欢把灯调到50%亮度"]

    def test_dissimilar_memory_kept(self):
        """不相似记忆不得被误删"""
        engine = _engine_with_memories()
        sc = SleepConsolidation(memory_engine=engine)
        sc._compress_memories()
        assert any("天气" in e.content for e in engine.long_term.items.values())

    def test_metadata_and_access_count_merged(self):
        """合并时应保留 keeper 缺失的元数据"""
        engine = CognitiveMemoryEngine()
        engine.remember("项目例会定在每周一上午", memory_type="semantic",
                        importance=0.82, metadata={"source": "对话"})
        engine.remember("项目例会定在每周一上午十点", memory_type="semantic",
                        importance=0.85, metadata={"channel": "语音"})
        sc = SleepConsolidation(memory_engine=engine)
        sc._compress_memories()

        keeper = next(e for e in engine.long_term.items.values()
                      if "项目例会" in e.content)
        assert keeper.metadata.get("source") == "对话"
        assert keeper.metadata.get("channel") == "语音"

    def test_stale_embeddings_cleaned(self):
        """合并后向量索引不应残留已删条目"""
        engine = _engine_with_memories()
        sc = SleepConsolidation(memory_engine=engine)
        sc._compress_memories()
        indexed_ids = {i for i, _ in engine.long_term._embeddings}
        assert indexed_ids == set(engine.long_term.items.keys())


class TestFallbackCompression:
    def test_no_embedding_uses_prefix_jaccard(self):
        """无向量记忆走原前缀 + Jaccard 兜底（前缀 = 内容前 20 字符）"""
        engine = CognitiveMemoryEngine()
        from src.core.memory_engine import MemoryEntry
        e1 = MemoryEntry(id="m1", content="用户偏好简洁的回复风格，不喜欢冗长的解释",
                         memory_type="semantic", layer="long_term", importance=0.9)
        e2 = MemoryEntry(id="m2", content="用户偏好简洁的回复风格，不喜欢冗长的解释说明",
                         memory_type="semantic", layer="long_term", importance=0.5)
        engine.long_term.add(e1)
        engine.long_term.add(e2)

        sc = SleepConsolidation(memory_engine=engine)
        compressed = sc._compress_memories()
        assert compressed == 1
        assert set(engine.long_term.items.keys()) == {"m1"}

    def test_empty_memory_no_crash(self):
        engine = CognitiveMemoryEngine()
        sc = SleepConsolidation(memory_engine=engine)
        assert sc._compress_memories() == 0

    def test_no_memory_engine(self):
        sc = SleepConsolidation(memory_engine=None)
        assert sc._compress_memories() == 0
