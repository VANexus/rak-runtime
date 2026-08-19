"""
大脑 MCP 客户端（G6/G19）— 让大脑连接并调用【外部 MCP 工具】。

现有 fastmcp_server 是大脑对外暴露工具（MCP server 端）；本模块是**客户端端**：
大脑作为 MCP client 连接外部工具服务器（如 Claude Code 的 MCP server、自定义
技能服务器），把外部工具的 list_tools / call_tool 能力暴露给 Agent 内核。

连接方式：
1. stdio —— `RAK_MCP_SERVERS` env 配置 JSON 列表，spawn 子进程 MCP server：
   [{"name":"skill-server","command":"python","args":["-m","skill_server"]}]
2. in-process —— 直接传一个 FastMCP 实例（测试 / 嵌入式服务器，零网络）。

设计原则：
- 降级：无配置 / 连接失败 → 标记不可用，永不阻断 Agent 决策。
- 短连接：每次调用建临时 session（async with），避免长连接状态管理。
- 窄腰：只暴露 list_tools/call_tool，不绑定具体协议细节到上层。
"""

import asyncio
import json
import logging
import os
import threading
from typing import Dict, List, Optional

logger = logging.getLogger("rak.mcp_client")


class MCPExternalTool:
    """一个来自外部 MCP 服务器的工具（供上层物化/选择）。"""
    __slots__ = ("server", "name", "description", "input_schema")

    def __init__(self, server: str, name: str, description: str = "",
                 input_schema: Optional[Dict] = None):
        self.server = server
        self.name = name
        self.description = description or ""
        self.input_schema = input_schema or {}

    def to_dict(self) -> dict:
        return {
            "server": self.server, "name": self.name,
            "description": self.description, "input_schema": self.input_schema,
        }

    def __repr__(self):  # 调试友好
        return f"<MCPTool {self.server}/{self.name}>"


def _server_configs() -> List[dict]:
    """从 RAK_MCP_SERVERS 读取外部 MCP server 配置（stdlib spawn）。"""
    raw = os.getenv("RAK_MCP_SERVERS", "")
    if not raw or not raw.strip():
        return []
    try:
        cfg = json.loads(raw)
        return cfg if isinstance(cfg, list) else []
    except json.JSONDecodeError as e:
        logger.warning("[MCPClient] RAK_MCP_SERVERS 解析失败: %s", e)
        return []


def _make_transport(server_cfg: dict):
    """为 stdio server 配置构建 (async) transport，供 fastmcp.Client 使用。

    返回 (description, transport_factory)：
    - description：人类可读说明
    - transport_factory：调用后得到可进入 async with 的 transport
    """
    command = server_cfg.get("command")
    args = server_cfg.get("args") or []
    name = server_cfg.get("name") or command or "mcp-server"

    if not command:
        return name, None

    def _factory():
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=command, args=list(args), env=None)
        return stdio_client(params)

    return name, _factory


class MCPToolClient:
    """
    大脑 MCP 客户端 — 连接外部工具服务器。

    - list_external_tools()：发现所有已连接服务器的工具
    - call_tool(server, tool, args)：调用指定外部工具
    - 每次调用建短 session；失败/未配置都降级不抛。
    """

    def __init__(self, servers: Optional[List[dict]] = None,
                 inprocess_servers: Optional[Dict[str, object]] = None):
        # servers: stdio 配置 [{name, command, args}, ...]
        self._servers = servers if servers is not None else \
            _server_configs()
        # inprocess_servers: name -> FastMCP 实例（测试/嵌入式）
        self._inprocess = dict(inprocess_servers or {})
        self._lock = threading.Lock()
        self._stats = {"discover_calls": 0, "tool_calls": 0, "failures": 0}

    @property
    def configured(self) -> bool:
        return bool(self._servers or self._inprocess)

    # ── 发现 ──────────────────────────────────────────────

    def list_external_tools(self) -> List[MCPExternalTool]:
        """连接所有服务器并列出其工具（一次性发现）。
        失败服务器跳过（降级），返回已发现的工具列表。
        """
        self._stats["discover_calls"] += 1
        out: List[MCPExternalTool] = []

        # in-process 服务器
        for name, server in self._inprocess.items():
            try:
                tools = asyncio.run(self._list_from_client(self._mk_client(None, fp=server)))
                for t in tools:
                    out.append(MCPExternalTool(server=name, name=t["name"],
                                               description=t.get("description", ""),
                                               input_schema=t.get("input_schema", {})))
            except Exception as e:
                self._stats["failures"] += 1
                logger.warning("[MCPClient] in-process 服务器 %s 发现失败: %s", name, e)

        # stdio 服务器
        for cfg in self._servers:
            name, factory = _make_transport(cfg)
            if factory is None:
                continue
            try:
                tools = asyncio.run(self._list_from_transport(factory))
                for t in tools:
                    out.append(MCPExternalTool(server=name, name=t["name"],
                                               description=t.get("description", ""),
                                               input_schema=t.get("input_schema", {})))
            except Exception as e:
                self._stats["failures"] += 1
                logger.warning("[MCPClient] stdio 服务器 %s 发现失败: %s", name, e)

        return out

    # ── 调用 ──────────────────────────────────────────────

    def call_tool(self, server: str, tool: str, args: dict) -> str:
        """调用指定服务器的外部工具，返回文本结果。失败返回错误说明（不抛）。"""
        self._stats["tool_calls"] += 1

        # in-process
        if server in self._inprocess:
            try:
                return asyncio.run(self._call_from_client(
                    self._mk_client(None, self._inprocess[server]), tool, args))
            except Exception as e:
                self._stats["failures"] += 1
                return f"（MCP 调用失败: {e}）"

        # stdio
        for cfg in self._servers:
            name, factory = _make_transport(cfg)
            if name == server and factory is not None:
                try:
                    return asyncio.run(self._call_from_transport(factory, tool, args))
                except Exception as e:
                    self._stats["failures"] += 1
                    return f"（MCP 调用失败: {e}）"

        return f"（MCP 服务器 {server} 未配置或不可用）"

    # ── 内部（async 实现） ────────────────────────────────

    @staticmethod
    def _mk_client(transport, fp=None):
        """构建 fastmcp.Client：优先 in-process FastMCP 实例，否则 transport。"""
        from fastmcp import Client
        if fp is not None:
            return Client(fp)
        return Client(transport)

    @staticmethod
    async def _list_from_client(client) -> List[dict]:
        async with client as sess:
            tools = await sess.list_tools()
            return [
                {"name": t.name, "description": getattr(t, "description", ""),
                 "input_schema": getattr(t, "inputSchema", {}) or {}}
                for t in tools
            ]

    @staticmethod
    async def _list_from_transport(factory) -> List[dict]:
        """stdio 连接用 mcp SDK ClientSession（stdio_client 流兼容，fastmcp.Client 不兼容 anyio 流）。"""
        from mcp import ClientSession
        transport = factory()
        async with transport as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [
                    {"name": t.name, "description": getattr(t, "description", "") or "",
                     "input_schema": getattr(t, "inputSchema", {}) or {}}
                    for t in (tools.tools if hasattr(tools, "tools") else tools)
                ]

    @staticmethod
    async def _call_from_client(client, tool: str, args: dict) -> str:
        async with client as sess:
            res = await sess.call_tool(tool, args)
            text = ""
            if hasattr(res, "content"):
                for part in res.content:
                    if getattr(part, "type", None) == "text":
                        text += getattr(part, "text", "") or ""
            return text or str(res)[:500]

    @staticmethod
    async def _call_from_transport(factory, tool: str, args: dict) -> str:
        """stdio 调用：mcp SDK ClientSession。"""
        from mcp import ClientSession
        transport = factory()
        async with transport as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                text = ""
                if hasattr(res, "content"):
                    for part in res.content:
                        if getattr(part, "type", None) == "text":
                            text += getattr(part, "text", "") or ""
                return text or str(res)[:500]

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "configured": self.configured,
            "stdio_servers": len(self._servers),
            "inprocess_servers": len(self._inprocess),
            **self._stats,
        }


_client = None
_client_lock = threading.Lock()


def get_mcp_client() -> Optional[MCPToolClient]:
    """懒加载全局单例（无配置时仍创建但 configured=False，or 返回实例）。"""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = MCPToolClient()
    return _client
