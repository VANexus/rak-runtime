"""认知图统一接线测试 — 消除双实例，注入真实依赖"""

from src.core import decision_engine as de


class TestCognitiveGraph:
    def test_inner_loop_has_dependencies(self):
        """InnerLoop 单例应注入真实依赖（不再空依赖）"""
        de._inner_loop = None
        inner = de._get_inner_loop()
        de._wire_cognitive_graph()
        assert inner._emotion_engine is not None
        assert inner._need_engine is not None
        assert inner._living_graph is not None
        assert inner._world_model is not None

    def test_proactive_engine_has_dependencies(self):
        """ProactiveEngine 单例应有世界模型/用户模型/学习闭环依赖"""
        de._proactive_engine = None
        proactive = de._get_proactive_engine()
        de._wire_cognitive_graph()
        assert proactive._world_model is not None
        assert proactive._user_model is not None
        assert proactive._learning_loop is not None

    def test_memory_stream_has_engine(self):
        """MemoryStream 单例应注入记忆引擎"""
        de._memory_stream = None
        stream = de._get_memory_stream()
        de._wire_cognitive_graph()
        assert stream._memory_engine is not None

    def test_singletons_are_shared(self):
        """多次获取应返回同一实例（统一事实源）"""
        a = de._get_emotion_engine()
        b = de._get_emotion_engine()
        assert a is b
        a2 = de._get_inner_loop()
        b2 = de._get_inner_loop()
        assert a2 is b2


class TestSuperMemoryGraphWiring:
    def test_super_memory_and_graph_wired(self):
        """决策引擎应暴露超长期记忆与记忆图谱单例"""
        de._super_memory = None
        de._memory_graph = None
        sm = de._get_super_memory()
        g = de._get_memory_graph()
        assert sm is not None
        assert g is not None

    def test_index_memory_graph_query_finds(self, tmp_path):
        """写超长期记忆 + 索引图谱后，图多跳查询应能召回"""
        from src.core.memory_longterm import SuperMemory
        from src.core.memory_graph import MemoryGraph
        sm = SuperMemory(db_path=str(tmp_path / "sm.db"))
        g = MemoryGraph(super_mem=sm)
        a = sm.remember("客厅的灯", "semantic", scope="default", importance=0.8)
        b = sm.remember("卧室的空调", "semantic", scope="default", importance=0.8)
        g.index(a, "客厅的灯", scope="default")
        g.index(b, "卧室的空调", scope="default")
        g.link(a, b, weight=0.9)
        hits = g.query("客厅", scope="default", top_k=5)
        assert hits, "应从图谱召回节点"
        assert any(h.id == a for h in hits)


class TestGraphInjectsIntoDecisionContext:
    """图→决策集成：_build_memory_context 应把 MemoryGraph 联想注入决策上下文。

    验证架构文档声称的『第四通道』确实到达决策 prompt——图结构记忆对决策的真实贡献。
    """

    def test_decision_context_includes_graph_association(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAK_DATA_DIR", str(tmp_path / "data"))
        import src.core.decision_engine as de
        import src.core.memory_longterm as mlt
        import src.core.memory_graph as mg
        # 重置单例指向隔离数据目录
        mlt._instance = None
        de._super_memory = None
        de._memory_graph = None
        mg._instance = None

        # 注入图联想：同现记忆建边 → 查询应经图扩散浮出
        sm = de._get_super_memory()
        g = de._get_memory_graph()
        a = sm.remember("用户晚上开灯", "semantic", scope="default", importance=0.8)
        b = sm.remember("门口的锁要关上", "semantic", scope="default", importance=0.8)
        g.index(a, "用户晚上开灯", scope="default")
        g.index(b, "门口的锁要关上", scope="default")
        g.link(a, b, weight=0.9)

        eng = de.DecisionEngine()
        ctx = eng._build_memory_context("开灯")
        assert "记忆图谱联想" in ctx, "决策上下文应含记忆图谱联想通道"
        assert "门口的锁" in ctx, "图联想应把关联记忆注入决策上下文"

