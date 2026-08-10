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
