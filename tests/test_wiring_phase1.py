"""Phase 1 接线测试：反射弧 / AgenticRAG / 持久化偏好链"""

import pytest

from src.core import decision_engine as de


class TestPolicyReflex:
    def test_reflex_disabled_by_default(self, monkeypatch):
        """未设 RAK_REFLEX 时反射弧不触发"""
        monkeypatch.delenv("RAK_REFLEX", raising=False)
        engine = de.DecisionEngine()
        assert engine._reflex_path("打开灯", ["light_on", "lock_open"]) is None

    def test_reflex_requires_training(self, monkeypatch):
        """未训练的随机权重不应作反射"""
        monkeypatch.setenv("RAK_REFLEX", "1")
        de._policy_model = None
        engine = de.DecisionEngine()
        model = de._get_policy_model().get_or_create("default")
        model.exploration_rate = 0.0
        assert engine._reflex_path("打开灯", ["light_on", "lock_open"]) is None

    def test_reflex_fires_after_training(self, monkeypatch):
        """反复强化后对已知模式应快速反射（基底神经节形成条件反射）"""
        monkeypatch.setenv("RAK_REFLEX", "1")
        de._policy_model = None
        engine = de.DecisionEngine()
        model = de._get_policy_model().get_or_create("default")
        model.exploration_rate = 0.0
        # 同一模式反复成功（如"打开灯"重复出现），直至形成反射
        for _ in range(300):
            engine._update_policy_model("打开灯", "light_on", 1.0)
        result = engine._reflex_path("打开灯", ["light_on", "lock_open"])
        assert result is not None
        assert result["action"] == "light_on"
        assert result["source"] == "reflex"

    def test_reflex_respects_available_actions(self, monkeypatch):
        """反射动作不在可用列表时应返回 None"""
        monkeypatch.setenv("RAK_REFLEX", "1")
        de._policy_model = None
        engine = de.DecisionEngine()
        model = de._get_policy_model().get_or_create("default")
        model.exploration_rate = 0.0
        for _ in range(300):
            engine._update_policy_model("打开灯", "light_on", 1.0)
        assert engine._reflex_path("打开灯", ["lock_open"]) is None


class TestAgenticRAG:
    def test_is_knowledge_question(self):
        """应识别知识性问题，排除动作指令"""
        engine = de.DecisionEngine()
        assert engine._is_knowledge_question("我家的猫叫什么名字？")
        assert engine._is_knowledge_question("今天天气怎么样")
        assert not engine._is_knowledge_question("帮我开灯")

    def test_agentic_rag_engine_created(self):
        """_get_agentic_rag 应返回带记忆检索的引擎"""
        de._agentic_rag = None
        rag = de._get_agentic_rag()
        assert rag is not None


class TestPrefChain:
    def test_default_backend_sqlite_file(self, monkeypatch, tmp_path):
        """无 Postgres/Redis 配置时走 sqlite+file"""
        monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        from src.core.memory_persistence import PrefChainPersistence
        p = PrefChainPersistence(str(tmp_path))
        assert p.backend_name == "sqlite+file"

    def test_save_load_roundtrip(self, monkeypatch, tmp_path):
        """长期记忆应可保存/加载"""
        monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        from src.core.memory_persistence import PrefChainPersistence
        p = PrefChainPersistence(str(tmp_path))
        p.save_long_term({
            "id": "m1", "content": "用户喜欢把灯调到50%",
            "memory_type": "semantic", "layer": "long_term",
            "importance": 0.9, "metadata": {}, "created_at": 1,
            "last_accessed": 1, "access_count": 0, "decay_rate": 0.01,
        }, [0.1, 0.2])
        loaded = p.load_long_term()
        assert any(m["content"] == "用户喜欢把灯调到50%" for m in loaded)

    def test_memory_engine_uses_pref_chain(self, monkeypatch):
        """决策引擎记忆引擎应使用偏好链持久化"""
        monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        de._memory_engine = None
        mem = de._get_memory_engine()
        assert mem is not None
        assert mem.persistence is not None
        assert mem.persistence.backend_name == "sqlite+file"
