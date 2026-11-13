"""PG 模式向量恢复测试：恢复后进程内仍可做余弦检索（P3 pgvector 收口）"""

import pytest

from pytest import approx

from src.core.memory_postgres import PostgresMemoryBackend
from src.core.memory_persistence import PrefChainPersistence
from src.core.memory_engine import CognitiveMemoryEngine


MEM = {
    "id": "m1", "content": "用户喜欢把灯调到50%",
    "memory_type": "semantic", "layer": "long_term",
    "importance": 0.9, "metadata": {}, "created_at": 1,
    "last_accessed": 1, "access_count": 0, "decay_rate": 0.01,
}


class TestParseEmbedding:
    def test_pgvector_string(self):
        """pgvector 列以字符串 '[0.1, 0.2]' 返回"""
        backend = PostgresMemoryBackend.__new__(PostgresMemoryBackend)
        assert backend._parse_embedding("[0.1, 0.2, 0.3]") == [0.1, 0.2, 0.3]

    def test_jsonb_list(self):
        """无 pgvector 扩展时 JSONB 列由 psycopg2 解析为列表"""
        backend = PostgresMemoryBackend.__new__(PostgresMemoryBackend)
        assert backend._parse_embedding([0.4, 0.5]) == [0.4, 0.5]

    def test_malformed_returns_none(self):
        """脏数据返回 None，不抛异常"""
        backend = PostgresMemoryBackend.__new__(PostgresMemoryBackend)
        assert backend._parse_embedding("not,a,vector") is None
        assert backend._parse_embedding("") is None
        assert backend._parse_embedding(None) is None


class TestUnavailableBackend:
    def test_load_embeddings_degrades_to_empty(self, monkeypatch):
        """PG 不可用时返回空 dict，不抛异常（自动降级）"""
        monkeypatch.setenv("RAG_POSTGRES_DSN", "postgresql://nobody:nope@127.0.0.1:1/none")
        backend = PostgresMemoryBackend("postgresql://nobody:nope@127.0.0.1:1/none")
        assert not backend.available
        assert backend.load_embeddings() == {}


class TestPrefChainDelegation:
    def test_file_backend_roundtrip(self, monkeypatch, tmp_path):
        """无 PG 配置时向量走文件后端"""
        monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        p = PrefChainPersistence(str(tmp_path))
        p.save_long_term(MEM, [0.1, 0.2])
        # 文件后端以 float32 存储，比较需容差
        assert p.load_embeddings().get("m1") == approx([0.1, 0.2])

    def test_pg_active_delegates(self, monkeypatch, tmp_path):
        """PG 激活时向量应从 PG 加载而非返回空"""
        monkeypatch.delenv("REDIS_URL", raising=False)
        p = PrefChainPersistence(str(tmp_path))

        class FakePg:
            available = True

            @staticmethod
            def load_embeddings():
                return {"m1": [0.3, 0.4]}

        p._pg = FakePg()
        assert p.load_embeddings() == {"m1": [0.3, 0.4]}


class TestRestoredVectorSearch:
    def test_restored_memory_searchable_by_embedding(self, monkeypatch, tmp_path):
        """重启恢复链路：保存 → 新引擎加载 → 向量检索命中（而非只靠关键词兜底）"""
        monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

        p = PrefChainPersistence(str(tmp_path))
        p.save_long_term(MEM, [0.1, 0.2, 0.3, 0.4])

        # 模拟重启：全新引擎实例从持久化恢复
        engine = CognitiveMemoryEngine(persistence=p)
        assert engine.long_term.items["m1"].embedding == approx([0.1, 0.2, 0.3, 0.4])

        results = engine.long_term.search([0.1, 0.2, 0.3, 0.4], top_k=3)
        assert results, "恢复后应能用向量检索命中，而不是退化为关键词兜底"
        assert results[0].entry.id == "m1"
        assert results[0].similarity > 0.99
