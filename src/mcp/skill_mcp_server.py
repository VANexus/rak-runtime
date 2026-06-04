"""
MCP 技能服务器 — 让 LLM 能发现和调用每一个技能神经元

MCP（Model Context Protocol）是 LLM 与外部工具交互的标准协议。
在 Rak OS 中，MCP 是"神经系统"——让大脑（LLM）能发现和调用
全身每一个"神经元"（技能节点）。

核心功能：
1. 工具发现：LLM 可以列出所有可用技能
2. 工具调用：LLM 可以激活任意技能
3. 资源访问：LLM 可以读取设备状态、记忆等
4. 通知推送：技能执行结果实时推送给 LLM

类比：
- MCP 工具 = 运动皮层的技能神经元
- MCP 资源 = 感觉神经的输入信号
- MCP 通知 = 反馈回路

实现：
- 轻量级 JSON-RPC 服务器
- 兼容 MCP 规范
- 可嵌入现有 gRPC/HTTP 服务
"""

import json
import logging
import time
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger(__name__)


# ========== MCP 协议类型 ==========

class MCPTool:
    """MCP 工具定义（对应一个技能神经元）"""

    def __init__(self, name: str, description: str,
                 input_schema: Dict, handler: Callable = None):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class MCPResource:
    """MCP 资源定义（对应一个数据源）"""

    def __init__(self, uri: str, name: str, description: str,
                 mime_type: str = "application/json"):
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type

    def to_dict(self) -> Dict:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


class MCPRequest:
    """MCP JSON-RPC 请求"""

    def __init__(self, method: str, params: Dict = None, id: int = None):
        self.method = method
        self.params = params or {}
        self.id = id

    @classmethod
    def from_dict(cls, data: Dict) -> 'MCPRequest':
        return cls(
            method=data.get("method", ""),
            params=data.get("params", {}),
            id=data.get("id"),
        )


class MCPResponse:
    """MCP JSON-RPC 响应"""

    def __init__(self, result: Any = None, error: Dict = None, id: int = None):
        self.result = result
        self.error = error
        self.id = id

    def to_dict(self) -> Dict:
        resp = {"jsonrpc": "2.0", "id": self.id}
        if self.error:
            resp["error"] = self.error
        else:
            resp["result"] = self.result
        return resp


# ========== MCP 技能服务器 ==========

class SkillMCPServer:
    """
    MCP 技能服务器 — 技能神经网络的神经系统。

    暴露技能网络为 MCP 工具，让 LLM 可以：
    1. 列出所有技能（工具发现）
    2. 激活技能（工具调用）
    3. 查询设备状态（资源访问）
    4. 查询记忆（资源访问）
    5. 获取执行反馈（通知）

    架构：
    LLM ←→ MCP Server ←→ SkillNetwork
                         ←→ DeviceManager
                         ←→ MemoryEngine
    """

    def __init__(self, skill_registry=None, device_manager=None,
                 memory_engine=None, decision_engine=None):
        self.skill_registry = skill_registry
        self.device_manager = device_manager
        self.memory_engine = memory_engine
        self.decision_engine = decision_engine

        # 工具注册表
        self.tools: Dict[str, MCPTool] = {}
        self.resources: Dict[str, MCPResource] = {}

        # 注册内置工具和资源
        self._register_builtin_tools()
        self._register_builtin_resources()

        # 通知队列
        self.notifications: List[Dict] = []

        logger.info(f"[MCPServer] 初始化完成: {len(self.tools)} 工具, {len(self.resources)} 资源")

    def _register_builtin_tools(self):
        """注册内置 MCP 工具"""

        # 1. 激活技能
        self.tools["activate_skill"] = MCPTool(
            name="activate_skill",
            description="激活一个技能神经元。输入自然语言描述，系统会找到最匹配的技能并返回执行计划。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言描述，如'打开门锁'、'让机器人跳舞'"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回的候选技能数量",
                        "default": 3
                    }
                },
                "required": ["query"]
            },
            handler=self._handle_activate_skill,
        )

        # 2. 执行动作
        self.tools["execute_action"] = MCPTool(
            name="execute_action",
            description="执行一个原子动作。直接指定动作名和参数，绕过技能匹配。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "动作名，如 lock_open, move_forward, dance"
                    },
                    "device_id": {
                        "type": "string",
                        "description": "目标设备 ID"
                    },
                    "params": {
                        "type": "object",
                        "description": "动作参数"
                    }
                },
                "required": ["action"]
            },
            handler=self._handle_execute_action,
        )

        # 3. 查询设备状态
        self.tools["query_device"] = MCPTool(
            name="query_device",
            description="查询设备的当前状态和能力。",
            input_schema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "设备 ID"
                    }
                },
                "required": ["device_id"]
            },
            handler=self._handle_query_device,
        )

        # 4. 搜索记忆
        self.tools["search_memory"] = MCPTool(
            name="search_memory",
            description="搜索记忆系统，查找相关的经验、知识或历史事件。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "procedural", "semantic"],
                        "description": "记忆类型"
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5
                    }
                },
                "required": ["query"]
            },
            handler=self._handle_search_memory,
        )

        # 5. 注册新技能
        self.tools["register_skill"] = MCPTool(
            name="register_skill",
            description="注册一个新的技能神经元到技能网络。",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "params": {"type": "object"},
                                "priority": {"type": "integer"}
                            }
                        }
                    }
                },
                "required": ["name", "description", "actions"]
            },
            handler=self._handle_register_skill,
        )

    def _register_builtin_resources(self):
        """注册内置 MCP 资源"""

        # 设备列表
        self.resources["devices"] = MCPResource(
            uri="rak://devices",
            name="设备列表",
            description="所有已注册设备的状态和能力",
        )

        # 技能列表
        self.resources["skills"] = MCPResource(
            uri="rak://skills",
            name="技能列表",
            description="所有已注册技能的元数据",
        )

        # 记忆统计
        self.resources["memory_stats"] = MCPResource(
            uri="rak://memory/stats",
            name="记忆统计",
            description="记忆系统的统计信息",
        )

    # ========== 请求处理 ==========

    def handle_request(self, request: MCPRequest) -> MCPResponse:
        """处理 MCP 请求"""
        logger.info(f"[MCPServer] 处理请求: {request.method}")

        try:
            if request.method == "initialize":
                return self._handle_initialize(request)
            elif request.method == "tools/list":
                return self._handle_list_tools(request)
            elif request.method == "tools/call":
                return self._handle_call_tool(request)
            elif request.method == "resources/list":
                return self._handle_list_resources(request)
            elif request.method == "resources/read":
                return self._handle_read_resource(request)
            elif request.method == "notifications/initialized":
                return MCPResponse(result={}, id=request.id)
            else:
                return MCPResponse(
                    error={"code": -32601, "message": f"未知方法: {request.method}"},
                    id=request.id,
                )
        except Exception as e:
            logger.error(f"[MCPServer] 处理失败: {e}")
            return MCPResponse(
                error={"code": -32603, "message": str(e)},
                id=request.id,
            )

    def _handle_initialize(self, request: MCPRequest) -> MCPResponse:
        """处理初始化请求"""
        return MCPResponse(
            result={
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": True},
                },
                "serverInfo": {
                    "name": "rak-skill-mcp",
                    "version": "0.1.0",
                },
            },
            id=request.id,
        )

    def _handle_list_tools(self, request: MCPRequest) -> MCPResponse:
        """列出所有工具"""
        tools = [tool.to_dict() for tool in self.tools.values()]
        return MCPResponse(result={"tools": tools}, id=request.id)

    def _handle_call_tool(self, request: MCPRequest) -> MCPResponse:
        """调用工具"""
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments", {})

        if tool_name not in self.tools:
            return MCPResponse(
                error={"code": -32602, "message": f"未知工具: {tool_name}"},
                id=request.id,
            )

        tool = self.tools[tool_name]
        if tool.handler is None:
            return MCPResponse(
                error={"code": -32601, "message": f"工具未实现: {tool_name}"},
                id=request.id,
            )

        result = tool.handler(arguments)

        # 记录通知
        self.notifications.append({
            "type": "tool_call",
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
            "timestamp": time.time(),
        })

        return MCPResponse(
            result={"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
            id=request.id,
        )

    def _handle_list_resources(self, request: MCPRequest) -> MCPResponse:
        """列出所有资源"""
        resources = [r.to_dict() for r in self.resources.values()]
        return MCPResponse(result={"resources": resources}, id=request.id)

    def _handle_read_resource(self, request: MCPRequest) -> MCPResponse:
        """读取资源"""
        uri = request.params.get("uri", "")

        if uri == "rak://devices":
            data = self._get_devices_resource()
        elif uri == "rak://skills":
            data = self._get_skills_resource()
        elif uri == "rak://memory/stats":
            data = self._get_memory_stats_resource()
        else:
            return MCPResponse(
                error={"code": -32602, "message": f"未知资源: {uri}"},
                id=request.id,
            )

        return MCPResponse(
            result={
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(data, ensure_ascii=False),
                }]
            },
            id=request.id,
        )

    # ========== 工具处理器 ==========

    def _handle_activate_skill(self, args: Dict) -> Dict:
        """激活技能"""
        query = args.get("query", "")
        top_k = args.get("top_k", 3)

        if not self.skill_registry:
            return {"error": "技能网络未初始化"}

        # 使用嵌入引擎生成查询向量
        if self.memory_engine and hasattr(self.memory_engine, 'embed_fn') and self.memory_engine.embed_fn:
            query_vec = self.memory_engine.embed_fn(query)
        else:
            # 降级：使用简单哈希
            query_vec = [0.0] * 128
            for i, c in enumerate(query.encode()):
                query_vec[i % 128] += float(c) / 255.0

        result = self.skill_registry.Activate(query_vec, top_k)

        return {
            "query": query,
            "activated_skills": [
                {
                    "id": skill.Node.ID,
                    "name": skill.Node.Name,
                    "category": skill.Node.Category,
                    "similarity": round(skill.Similarity, 4),
                    "score": round(skill.FinalScore, 4),
                    "actions": [a.Action for a in skill.Node.Actions],
                }
                for skill in result.Skills
            ],
            "total_searched": result.TotalSearched,
        }

    def _handle_execute_action(self, args: Dict) -> Dict:
        """执行动作"""
        action = args.get("action", "")
        device_id = args.get("device_id", "")
        params = args.get("params", {})

        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}

        # 创建模拟请求
        class MockRequest:
            def __init__(self):
                self.trace_id = f"mcp_{int(time.time())}"
                self.state = "mcp_direct_call"
                self.available_actions = [action]
                self.action = action
                self.params_json = json.dumps(params)

        result = self.decision_engine.decide(MockRequest())

        return {
            "action": action,
            "device_id": device_id,
            "decision": result,
        }

    def _handle_query_device(self, args: Dict) -> Dict:
        """查询设备"""
        device_id = args.get("device_id", "")

        if not self.device_manager:
            return {"error": "设备管理器未初始化"}

        device = self.device_manager.GetDevice(device_id)
        if device is None:
            return {"error": f"设备不存在: {device_id}"}

        return {
            "device_id": device.DeviceID,
            "online": device.Online,
            "last_seen": device.LastSeen,
        }

    def _handle_search_memory(self, args: Dict) -> Dict:
        """搜索记忆"""
        query = args.get("query", "")
        memory_type = args.get("memory_type")
        top_k = args.get("top_k", 5)

        if not self.memory_engine:
            return {"error": "记忆系统未初始化"}

        types = [memory_type] if memory_type else None
        results = self.memory_engine.recall(query, top_k=top_k, memory_types=types)

        return {
            "query": query,
            "results": [
                {
                    "content": r.entry.content,
                    "memory_type": r.entry.memory_type,
                    "similarity": round(r.similarity, 4),
                    "score": round(r.score, 4),
                }
                for r in results
            ],
        }

    def _handle_register_skill(self, args: Dict) -> Dict:
        """注册技能"""
        if not self.skill_registry:
            return {"error": "技能网络未初始化"}

        # 构建技能节点
        from src.core.skillnet_types import SkillNode, ActionTemplate

        actions = []
        for a in args.get("actions", []):
            actions.append(ActionTemplate(
                action=a.get("action", ""),
                params=a.get("params", {}),
                priority=a.get("priority", 1),
            ))

        node = SkillNode(
            id=f"skill.user.{args['name'].lower().replace(' ', '_')}",
            name=args["name"],
            description=args.get("description", ""),
            category=args.get("category", "custom"),
            actions=actions,
        )

        self.skill_registry.Register(node)

        return {
            "status": "registered",
            "skill_id": node.ID,
            "name": node.Name,
        }

    # ========== 资源处理器 ==========

    def _get_devices_resource(self) -> Dict:
        """获取设备资源"""
        if not self.device_manager:
            return {"devices": [], "error": "设备管理器未初始化"}

        devices = self.device_manager.GetAllDevices()
        return {
            "devices": [
                {
                    "device_id": d.DeviceID,
                    "online": d.Online,
                    "last_seen": d.LastSeen,
                }
                for d in devices
            ]
        }

    def _get_skills_resource(self) -> Dict:
        """获取技能资源"""
        if not self.skill_registry:
            return {"skills": [], "error": "技能网络未初始化"}

        skills = self.skill_registry.GetAllSkills()
        return {
            "skills": [
                {
                    "id": s.ID,
                    "name": s.Name,
                    "category": s.Category,
                    "description": s.Description,
                    "weight": round(s.Weight, 3),
                    "use_count": s.UseCount,
                }
                for s in skills
            ]
        }

    def _get_memory_stats_resource(self) -> Dict:
        """获取记忆统计"""
        if not self.memory_engine:
            return {"error": "记忆系统未初始化"}

        return self.memory_engine.stats()

    # ========== 统计 ==========

    def stats(self) -> Dict:
        """返回服务器统计"""
        return {
            "tools_count": len(self.tools),
            "resources_count": len(self.resources),
            "notifications_count": len(self.notifications),
        }
