"""生命周期钩子测试"""

from src.core.hooks import (
    HookRegistry, get_hooks,
    SESSION_START, PRE_TOOL_USE, POST_TOOL_USE, MEMORY_UPDATE,
)


class TestHookRegistry:
    def test_register_and_fire(self):
        """注册 + 触发应收到调用"""
        registry = HookRegistry()
        seen = []
        registry.register(PRE_TOOL_USE, lambda tool, **kw: seen.append(tool))
        registry.fire(PRE_TOOL_USE, tool="search_memory")
        assert seen == ["search_memory"]

    def test_handler_exception_does_not_block(self):
        """单个 handler 异常不应阻断其余"""
        registry = HookRegistry()
        seen = []

        def bad(**kw):
            raise RuntimeError("boom")

        def good(**kw):
            seen.append(1)

        registry.register(POST_TOOL_USE, bad)
        registry.register(POST_TOOL_USE, good)
        registry.fire(POST_TOOL_USE, tool="x")
        assert seen == [1]  # good 仍被调用

    def test_unknown_event_returns_empty(self):
        """未注册事件触发返回空"""
        registry = HookRegistry()
        assert registry.fire("no_such_event", x=1) == []

    def test_unregister(self):
        """注销后不再触发"""
        registry = HookRegistry()
        def h(**kw): pass
        registry.register(SESSION_START, h)
        registry.unregister(SESSION_START, h)
        assert registry.handlers(SESSION_START) == []

    def test_singleton(self):
        """全局单例复用"""
        assert get_hooks() is get_hooks()

    def test_memory_update_hook(self):
        """memory_update 事件可注册触发"""
        registry = HookRegistry()
        captured = []
        registry.register(MEMORY_UPDATE, lambda content, **kw: captured.append(content))
        registry.fire(MEMORY_UPDATE, content="用户偏好")
        assert captured == ["用户偏好"]


class TestAgentToolHooks:
    def test_tool_execution_fires_hooks(self):
        """agent 工具执行应 fire PRE/POST_TOOL_USE 钩子"""
        from src.core.agent_loop import _build_tools
        from src.core.hooks import get_hooks, PRE_TOOL_USE, POST_TOOL_USE

        events = []

        def pre(tool, **kw):
            events.append(("pre", tool))

        def post(tool, status, **kw):
            events.append(("post", tool, status))

        get_hooks().register(PRE_TOOL_USE, pre)
        get_hooks().register(POST_TOOL_USE, post)
        try:
            tools, _ = _build_tools(["nod"], "")
            sm = next(t for t in tools if t.name == "search_memory")
            sm.invoke({"query": "开门"})
        finally:
            get_hooks().unregister(PRE_TOOL_USE, pre)
            get_hooks().unregister(POST_TOOL_USE, post)

        assert ("pre", "search_memory") in events
        assert any(e[0] == "post" and e[1] == "search_memory" and e[2] == "ok"
                   for e in events)
