"""Agent 会话测试"""

from src.core.agent_session import (
    AgentSession, SessionStore, ToolTraceEvent, get_session_store,
)


class TestAgentSession:
    def test_create_and_append(self):
        """创建 + 追加消息/轨迹"""
        s = AgentSession(session_id="s1", trace_id="t1")
        s.append_message("user", "你好")
        s.append_tool_trace(ToolTraceEvent(
            tool="search_memory", args={"query": "开门"},
            result="[]", duration_ms=12.5, status="ok",
        ))
        assert len(s.messages) == 1
        assert len(s.tool_traces) == 1
        assert s.tool_traces[0].tool == "search_memory"

    def test_roundtrip(self, tmp_path):
        """保存 + 加载 roundtrip 保真"""
        store = SessionStore(str(tmp_path))
        s = AgentSession(session_id="s1", trace_id="t1")
        s.append_message("user", "帮我开灯")
        s.append_tool_trace(ToolTraceEvent(
            tool="finalize", args={"action": "light_on"},
            result="决策已记录", duration_ms=3.0, status="ok",
        ))
        s.mark_completed({"action": "light_on", "params_json": "{}"})
        store.save(s)

        loaded = store.load("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert len(loaded.tool_traces) == 1
        assert loaded.final_decision["action"] == "light_on"
        assert loaded.status == "completed"

    def test_load_missing_returns_none(self, tmp_path):
        """不存在的会话返回 None"""
        store = SessionStore(str(tmp_path))
        assert store.load("nope") is None

    def test_list_recent(self, tmp_path):
        """list_recent 返回摘要"""
        store = SessionStore(str(tmp_path))
        s = AgentSession(session_id="s1", trace_id="t1")
        s.mark_completed({"action": "nod"})
        store.save(s)
        recent = store.list_recent(n=5)
        assert len(recent) >= 1
        assert recent[0]["session_id"] == "s1"
        assert recent[0]["action"] == "nod"

    def test_summary(self):
        """summary 含关键字段"""
        s = AgentSession(session_id="s1", trace_id="t1")
        s.mark_completed({"action": "wave_hand"})
        summ = s.summary()
        assert summ["action"] == "wave_hand"
        assert summ["status"] == "completed"

    def test_singleton(self):
        """单例复用"""
        assert get_session_store() is get_session_store()
