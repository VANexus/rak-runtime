"""大脑 MCP 服务器测试"""

import asyncio

from src.mcp.fastmcp_server import create_mcp_server


def _list_tools(mcp):
    async def _run():
        return await mcp.list_tools()
    return asyncio.run(_run())


def _call_tool(mcp, name, args=None):
    async def _run():
        return await mcp.call_tool(name, args or {})
    return asyncio.run(_run())


def _text(res) -> str:
    return res.content[0].text if res and res.content else ""


class TestFastMCPServer:
    def test_tools_registered(self):
        """应注册完整的大脑工具集"""
        mcp = create_mcp_server()
        tools = _list_tools(mcp)
        names = {t.name for t in tools}
        for expected in ["execute_action", "search_memory", "query_device",
                         "get_emotion", "get_needs", "get_self_info",
                         "reflect", "diffuse_memory", "get_narrative"]:
            assert expected in names, f"缺少工具 {expected}"
        assert len(names) >= 14

    def test_get_emotion_tool(self):
        """get_emotion 应返回六维情绪"""
        mcp = create_mcp_server()
        text = _text(_call_tool(mcp, "get_emotion"))
        assert "joy" in text

    def test_get_needs_tool(self):
        """get_needs 应返回需求向量"""
        mcp = create_mcp_server()
        text = _text(_call_tool(mcp, "get_needs"))
        assert "learning" in text or "error" in text

    def test_search_memory_tool(self):
        """search_memory 应调用记忆引擎"""
        mcp = create_mcp_server()
        text = _text(_call_tool(mcp, "search_memory", {"query": "开门"}))
        assert "results" in text or "error" in text

    def test_execute_action_deny(self, monkeypatch):
        """权限 deny 的动作不执行，返回 denied"""
        from src.core.permissions import PermissionPolicy
        p = PermissionPolicy({"actions": {"light_on": "deny"}})
        monkeypatch.setattr("src.mcp.fastmcp_server.get_permission_policy", lambda: p)
        mcp = create_mcp_server()
        text = _text(_call_tool(mcp, "execute_action", {"action": "light_on"}))
        assert '"status": "denied"' in text

    def test_execute_action_ask(self, monkeypatch):
        """权限 ask 的动作返回需确认"""
        from src.core.permissions import PermissionPolicy
        p = PermissionPolicy({"actions": {"light_on": "ask"}})
        monkeypatch.setattr("src.mcp.fastmcp_server.get_permission_policy", lambda: p)
        mcp = create_mcp_server()
        text = _text(_call_tool(mcp, "execute_action", {"action": "light_on"}))
        assert '"status": "needs_confirmation"' in text

    def test_execute_action_emergency_stop_always_allowed(self, monkeypatch):
        """emergency_stop 永远放行（即使配置 deny）"""
        from src.core.permissions import PermissionPolicy
        p = PermissionPolicy({"actions": {"emergency_stop": "deny"}})
        monkeypatch.setattr("src.mcp.fastmcp_server.get_permission_policy", lambda: p)
        mcp = create_mcp_server()
        text = _text(_call_tool(mcp, "execute_action", {"action": "emergency_stop"}))
        assert "decision" in text  # 走正常执行路径
