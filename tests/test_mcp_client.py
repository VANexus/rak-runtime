"""大脑 MCP 客户端（G6/G19）离线测试 — 连外部工具（in-process + stdio），零网络。"""

import sys

import pytest

from src.tools.mcp_client import MCPToolClient, MCPExternalTool, get_mcp_client, _server_configs


# 复用的 stub 服务器（本地 spawn）
_STUB_PATH = "/tmp/rak_stub_mcp.py"


def _inprocess_stub():
    """建造一个 in-process FastMCP stub 服务器。"""
    from fastmcp import FastMCP
    server = FastMCP("inproc")

    @server.tool()
    def double(n: int) -> int:
        """翻倍"""
        return n * 2

    @server.tool()
    def greet(name: str) -> str:
        """问候"""
        return f"hi {name}"

    return server


class TestInProcessPath:
    def test_list_and_call(self):
        """in-process 服务器：发现工具 + 调用。"""
        client = MCPToolClient(inprocess_servers={"inproc": _inprocess_stub()})
        tools = client.list_external_tools()
        names = {(t.server, t.name) for t in tools}
        assert ("inproc", "double") in names
        assert ("inproc", "greet") in names
        assert client.call_tool("inproc", "double", {"n": 21}) == "42"
        assert client.call_tool("inproc", "greet", {"name": "rak"}) == "hi rak"

    def test_missing_server_degrades(self):
        """未配置服务器 → 返回错误说明而非抛异常。"""
        client = MCPToolClient()  # 无服务器
        client._inprocess["inproc"] = _inprocess_stub()
        assert "未配置" in client.call_tool("ghost", "x", {})
        assert client.call_tool("inproc", "nope", {})  # 工具不存在 → 错误字符串，不抛


class TestStdioPath:
    def test_stdio_list_and_call(self):
        """stdio spawn 子进程服务器：发现 + 调用。"""
        client = MCPToolClient(servers=[
            {"name": "stub", "command": sys.executable, "args": ["-u", _STUB_PATH]},
        ])
        tools = client.list_external_tools()
        names = {(t.server, t.name) for t in tools}
        assert ("stub", "hello") in names
        assert ("stub", "square") in names
        assert client.call_tool("stub", "square", {"n": 7}) == "49"
        assert "rak" in client.call_tool("stub", "hello", {"name": "rak"})

    def test_configured_flag(self):
        client = MCPToolClient()  # 无配置
        assert client.configured is False
        client2 = MCPToolClient(servers=[{"name": "x", "command": "echo", "args": []}])
        assert client2.configured is True


class TestServerConfigEnv:
    def test_server_configs_parse(self, monkeypatch):
        monkeypatch.setenv("RAK_MCP_SERVERS",
                           '[{"name":"s1","command":"python","args":["-m","x"]}]')
        cfg = _server_configs()
        assert len(cfg) == 1 and cfg[0]["name"] == "s1"

    def test_server_configs_empty(self, monkeypatch):
        monkeypatch.delenv("RAK_MCP_SERVERS", raising=False)
        assert _server_configs() == []


class TestSingleton:
    def test_get_mcp_client_singleton(self):
        a = get_mcp_client()
        b = get_mcp_client()
        assert a is b

    def test_external_tool_dict(self):
        t = MCPExternalTool(server="s", name="tool", description="desc")
        d = t.to_dict()
        assert d["server"] == "s" and d["name"] == "tool" and d["description"] == "desc"
