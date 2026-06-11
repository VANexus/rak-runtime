"""
MCP 技能服务器 — 神经系统的接口层

MCP（Model Context Protocol）让 LLM 能发现和调用每一个"神经元"。

集成模块：
- WorldModel：设备状态查询和预测
- LearningLoop：执行反馈记录
- PromptEngine：洞察注入
- CognitiveMemoryEngine：记忆搜索
- DecisionEngine：动作执行
- UserModel：用户画像查询
- MetaCognition：置信度评估和自我反思
- ProactiveEngine：主动告警

与 go-kernel SkillNet 的关系：
- go-kernel SkillNet 做技能向量检索（ANN + Hebbian 学习）
- rak-runtime MCP 做认知层接口（LLM 工具发现 + 资源访问）
- 两者互补，不重复
"""

import json
import logging
import time
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger(__name__)


class MCPTool:
    """MCP 工具定义"""
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
    """MCP 资源定义"""
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


class SkillMCPServer:
    """
    MCP 技能服务器 — 认知层的接口。

    暴露 17 个工具 + 11 个资源，让 LLM 能：
    1. 查询和预测设备状态（WorldModel）
    2. 搜索记忆（MemoryEngine）
    3. 执行动作（DecisionEngine）
    4. 记录反馈（LearningLoop）
    5. 获取洞察（PromptEngine）
    6. 查询用户画像（UserModel）
    7. 评估置信度（MetaCognition）
    8. 触发自我反思（MetaCognition）
    9. 查询自我认知（SelfModel）
    10. 查询内部需求（NeedEngine）
    11. 查询情绪状态（EmotionEngine）
    12. 查询联想洞察（MemoryStream）
    """

    def __init__(self, skill_registry=None, device_manager=None,
                 memory_engine=None, decision_engine=None,
                 world_model=None, learning_loop=None,
                 prompt_engine=None):
        self.skill_registry = skill_registry
        self.device_manager = device_manager
        self.memory_engine = memory_engine
        self.decision_engine = decision_engine
        self.world_model = world_model
        self.learning_loop = learning_loop
        self.prompt_engine = prompt_engine

        self.tools: Dict[str, MCPTool] = {}
        self.resources: Dict[str, MCPResource] = {}
        self.notifications: List[Dict] = []

        self._register_builtin_tools()
        self._register_builtin_resources()

        logger.info(f"[MCPServer] 初始化完成: {len(self.tools)} 工具, {len(self.resources)} 资源")

    def _register_builtin_tools(self):
        """注册内置 MCP 工具"""

        # 1. 执行动作
        self.tools["execute_action"] = MCPTool(
            name="execute_action",
            description="执行一个原子动作。直接指定动作名和参数。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "动作名"},
                    "device_id": {"type": "string", "description": "目标设备 ID"},
                    "params": {"type": "object", "description": "动作参数"},
                },
                "required": ["action"],
            },
            handler=self._handle_execute_action,
        )

        # 2. 搜索记忆
        self.tools["search_memory"] = MCPTool(
            name="search_memory",
            description="搜索记忆系统，查找相关的经验、知识或历史事件。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "procedural", "semantic"],
                        "description": "记忆类型",
                    },
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            handler=self._handle_search_memory,
        )

        # 3. 查询设备状态
        self.tools["query_device"] = MCPTool(
            name="query_device",
            description="查询设备的当前状态和能力。",
            input_schema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 ID"},
                },
                "required": ["device_id"],
            },
            handler=self._handle_query_device,
        )

        # 4. 预测动作结果（WorldModel）
        self.tools["predict_outcome"] = MCPTool(
            name="predict_outcome",
            description="预测执行某个动作后的结果状态。用于动作规划前的'想象'。",
            input_schema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 ID"},
                    "action": {"type": "string", "description": "要预测的动作"},
                    "params": {"type": "object", "description": "动作参数"},
                },
                "required": ["device_id", "action"],
            },
            handler=self._handle_predict_outcome,
        )

        # 5. 报告执行反馈（LearningLoop）
        self.tools["report_feedback"] = MCPTool(
            name="report_feedback",
            description="报告动作执行的反馈结果。用于学习闭环。",
            input_schema={
                "type": "object",
                "properties": {
                    "trace_id": {"type": "string", "description": "追踪 ID"},
                    "action": {"type": "string", "description": "执行的动作"},
                    "success": {"type": "boolean", "description": "是否成功"},
                    "latency_ms": {"type": "number", "description": "执行延迟(ms)"},
                    "context": {"type": "string", "description": "上下文信息"},
                },
                "required": ["action", "success"],
            },
            handler=self._handle_report_feedback,
        )

        # 6. 获取学习洞察
        self.tools["get_insights"] = MCPTool(
            name="get_insights",
            description="获取系统从执行经验中提取的洞察。用于优化决策。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_insights,
        )

        # 7. 获取动作统计
        self.tools["get_action_stats"] = MCPTool(
            name="get_action_stats",
            description="获取各动作的成功率和延迟统计。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_action_stats,
        )

        # 8. 注册新技能
        self.tools["register_skill"] = MCPTool(
            name="register_skill",
            description="注册一个新的技能到技能网络。",
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
                                "priority": {"type": "integer"},
                            },
                        },
                    },
                },
                "required": ["name", "description", "actions"],
            },
            handler=self._handle_register_skill,
        )

        # 9. 获取用户画像（UserModel）
        self.tools["get_user_profile"] = MCPTool(
            name="get_user_profile",
            description="获取用户画像摘要，包括专业水平、沟通风格、行为模式、历史教训。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_user_profile,
        )

        # 10. 评估置信度（MetaCognition）
        self.tools["evaluate_confidence"] = MCPTool(
            name="evaluate_confidence",
            description="评估某个查询的决策置信度。用于判断是否需要用户确认。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要评估的查询"},
                    "available_actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可用动作列表",
                    },
                },
                "required": ["query"],
            },
            handler=self._handle_evaluate_confidence,
        )

        # 11. 触发自我反思（MetaCognition）
        self.tools["trigger_reflection"] = MCPTool(
            name="trigger_reflection",
            description="触发元认知自我反思，分析最近的决策质量并提取教训。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_trigger_reflection,
        )

        # 12. 记录用户纠正（UserModel）
        self.tools["record_correction"] = MCPTool(
            name="record_correction",
            description="记录用户对决策的纠正。这是最强的学习信号。",
            input_schema={
                "type": "object",
                "properties": {
                    "original_query": {"type": "string", "description": "原始查询"},
                    "wrong_action": {"type": "string", "description": "错误的动作"},
                    "correct_action": {"type": "string", "description": "正确的动作"},
                },
                "required": ["original_query", "wrong_action", "correct_action"],
            },
            handler=self._handle_record_correction,
        )

        # 13. 获取认知系统全量统计
        self.tools["get_cognitive_stats"] = MCPTool(
            name="get_cognitive_stats",
            description="获取认知系统的全量统计：世界模型、缓存、学习、元认知、用户模型、主动性。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_cognitive_stats,
        )

        # 14. 获取自我认知（SelfModel）
        self.tools["get_self_info"] = MCPTool(
            name="get_self_info",
            description="获取 Agent 的自我认知：我是谁、我会什么、我的性格、当前状态。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_self_info,
        )

        # 15. 获取内部需求（NeedEngine）
        self.tools["get_needs"] = MCPTool(
            name="get_needs",
            description="获取 Agent 的内部需求：学习、稳定、探索、休息、社交、安全。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_needs,
        )

        # 16. 获取情绪状态（EmotionEngine）
        self.tools["get_emotion"] = MCPTool(
            name="get_emotion",
            description="获取 Agent 的当前情绪状态：喜悦、恐惧、信任、惊讶、愤怒、悲伤。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_emotion,
        )

        # 17. 获取联想洞察（MemoryStream）
        self.tools["get_stream_insights"] = MCPTool(
            name="get_stream_insights",
            description="获取记忆联想流产生的洞察。这些是 Agent 在空闲时自动联想产生的。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_stream_insights,
        )

        # 18. 扩散激活记忆（LivingGraph）
        self.tools["diffuse_memory"] = MCPTool(
            name="diffuse_memory",
            description="从一个概念开始扩散激活记忆网络。返回联想链路上的所有激活节点。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "起始概念或查询文本"},
                },
                "required": ["query"],
            },
            handler=self._handle_diffuse_memory,
        )

        # 19. 获取图谱统计（LivingGraph）
        self.tools["get_graph_stats"] = MCPTool(
            name="get_graph_stats",
            description="获取活体知识图谱的统计：节点数、边数、最活跃节点、连接强度。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_graph_stats,
        )

        # 20. 获取内心独白（InnerLoop）
        self.tools["get_inner_thoughts"] = MCPTool(
            name="get_inner_thoughts",
            description="获取 Agent 最近的内心独白——即使没有用户输入也在产生的想法。",
            input_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "default": 10, "description": "返回数量"},
                },
            },
            handler=self._handle_get_inner_thoughts,
        )

        # 21. 获取自我叙事（InnerLoop）
        self.tools["get_narrative"] = MCPTool(
            name="get_narrative",
            description="获取 Agent 的自我叙事——'我最近在想什么'。",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_get_narrative,
        )

    def _register_builtin_resources(self):
        """注册内置 MCP 资源"""
        self.resources["devices"] = MCPResource(
            uri="rak://devices", name="设备列表",
            description="所有已注册设备的状态和能力",
        )
        self.resources["skills"] = MCPResource(
            uri="rak://skills", name="技能列表",
            description="所有已注册技能的元数据",
        )
        self.resources["memory_stats"] = MCPResource(
            uri="rak://memory/stats", name="记忆统计",
            description="记忆系统的统计信息",
        )
        self.resources["world_state"] = MCPResource(
            uri="rak://world/state", name="世界状态",
            description="所有设备的实时状态地图",
        )
        self.resources["learning_stats"] = MCPResource(
            uri="rak://learning/stats", name="学习统计",
            description="学习闭环的统计信息",
        )
        self.resources["user_profile"] = MCPResource(
            uri="rak://user/profile", name="用户画像",
            description="当前用户的行为画像和偏好",
        )
        self.resources["meta_stats"] = MCPResource(
            uri="rak://meta/stats", name="元认知统计",
            description="元认知引擎的置信度评估和策略选择统计",
        )
        self.resources["self_model"] = MCPResource(
            uri="rak://self/model", name="自我认知",
            description="Agent 的自我认知：身份、能力、性格、关系",
        )
        self.resources["needs"] = MCPResource(
            uri="rak://needs", name="内部需求",
            description="Agent 的内部需求向量：学习、稳定、探索、休息、社交、安全",
        )
        self.resources["emotion"] = MCPResource(
            uri="rak://emotion", name="情绪状态",
            description="Agent 的情绪状态：喜悦、恐惧、信任、惊讶、愤怒、悲伤",
        )
        self.resources["stream_insights"] = MCPResource(
            uri="rak://stream/insights", name="联想洞察",
            description="记忆联想流产生的洞察",
        )
        self.resources["living_graph"] = MCPResource(
            uri="rak://graph", name="活体图谱",
            description="活体知识图谱的统计和最活跃节点",
        )
        self.resources["inner_loop"] = MCPResource(
            uri="rak://inner", name="内心独白",
            description="Agent 的内心循环状态和最近想法",
        )
        self.resources["narrative"] = MCPResource(
            uri="rak://narrative", name="自我叙事",
            description="Agent 的自我叙事——我最近在想什么",
        )

    # ========== 请求处理 ==========

    def handle_request(self, request: MCPRequest) -> MCPResponse:
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
        return MCPResponse(
            result={
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": True},
                },
                "serverInfo": {
                    "name": "rak-skill-mcp",
                    "version": "0.3.0",
                },
            },
            id=request.id,
        )

    def _handle_list_tools(self, request: MCPRequest) -> MCPResponse:
        tools = [tool.to_dict() for tool in self.tools.values()]
        return MCPResponse(result={"tools": tools}, id=request.id)

    def _handle_call_tool(self, request: MCPRequest) -> MCPResponse:
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
        resources = [r.to_dict() for r in self.resources.values()]
        return MCPResponse(result={"resources": resources}, id=request.id)

    def _handle_read_resource(self, request: MCPRequest) -> MCPResponse:
        uri = request.params.get("uri", "")

        if uri == "rak://devices":
            data = self._get_devices_resource()
        elif uri == "rak://skills":
            data = self._get_skills_resource()
        elif uri == "rak://memory/stats":
            data = self._get_memory_stats_resource()
        elif uri == "rak://world/state":
            data = self._get_world_state_resource()
        elif uri == "rak://learning/stats":
            data = self._get_learning_stats_resource()
        elif uri == "rak://user/profile":
            data = self._get_user_profile_resource()
        elif uri == "rak://meta/stats":
            data = self._get_meta_stats_resource()
        elif uri == "rak://self/model":
            data = self._get_self_model_resource()
        elif uri == "rak://needs":
            data = self._get_needs_resource()
        elif uri == "rak://emotion":
            data = self._get_emotion_resource()
        elif uri == "rak://stream/insights":
            data = self._get_stream_insights_resource()
        elif uri == "rak://graph":
            data = self._get_living_graph_resource()
        elif uri == "rak://inner":
            data = self._get_inner_loop_resource()
        elif uri == "rak://narrative":
            data = self._get_narrative_resource()
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

    def _handle_execute_action(self, args: Dict) -> Dict:
        action = args.get("action", "")
        device_id = args.get("device_id", "")
        params = args.get("params", {})

        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}

        class MockRequest:
            def __init__(self):
                self.trace_id = f"mcp_{int(time.time())}"
                self.state = "mcp_direct_call"
                self.available_actions = [action]
                self.action = action
                self.params_json = json.dumps(params)

        result = self.decision_engine.decide(MockRequest())
        return {"action": action, "device_id": device_id, "decision": result}

    def _handle_search_memory(self, args: Dict) -> Dict:
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

    def _handle_query_device(self, args: Dict) -> Dict:
        device_id = args.get("device_id", "")

        if self.world_model:
            device = self.world_model.get_device(device_id)
            if device:
                return {
                    "device_id": device.device_id,
                    "online": device.online,
                    "last_seen": device.last_seen,
                    "capabilities": device.capabilities,
                    "current_action": device.current_action,
                    "sensors": device.sensors,
                }

        if self.device_manager:
            device = self.device_manager.GetDevice(device_id)
            if device:
                return {
                    "device_id": device.DeviceID,
                    "online": device.Online,
                    "last_seen": device.LastSeen,
                }

        return {"error": f"设备不存在: {device_id}"}

    def _handle_predict_outcome(self, args: Dict) -> Dict:
        if not self.world_model:
            return {"error": "世界模型未初始化"}

        prediction = self.world_model.predict_next_state(
            device_id=args.get("device_id", ""),
            action=args.get("action", ""),
            params=args.get("params", {}),
        )

        if prediction:
            return {
                "device_id": prediction.device_id,
                "action": prediction.action,
                "predicted_state": prediction.predicted_state,
                "confidence": round(prediction.confidence, 3),
            }
        return {"error": "无法预测"}

    def _handle_report_feedback(self, args: Dict) -> Dict:
        if not self.learning_loop:
            return {"error": "学习闭环未初始化"}

        self.learning_loop.on_execution_result(
            trace_id=args.get("trace_id", ""),
            action=args.get("action", ""),
            success=args.get("success", False),
            latency_ms=args.get("latency_ms", 0),
            context=args.get("context", ""),
        )

        return {"status": "recorded"}

    def _handle_get_insights(self, args: Dict) -> Dict:
        if not self.prompt_engine:
            return {"error": "提示词引擎未初始化"}

        return {
            "insights": self.prompt_engine._insights,
            "count": len(self.prompt_engine._insights),
        }

    def _handle_get_action_stats(self, args: Dict) -> Dict:
        if not self.learning_loop:
            return {"error": "学习闭环未初始化"}

        return self.learning_loop.get_action_stats()

    def _handle_register_skill(self, args: Dict) -> Dict:
        if not self.skill_registry:
            return {"error": "技能网络未初始化"}

        try:
            from src.core.skillnet_types import SkillNode, ActionTemplate
        except ImportError:
            return {"error": "技能类型模块不可用"}

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
        return {"status": "registered", "skill_id": node.ID, "name": node.Name}

    # ── 新增认知工具 ─────────────────────────────────────

    def _handle_get_user_profile(self, args: Dict) -> Dict:
        """获取用户画像摘要"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}

        return self.decision_engine.get_user_model_stats()

    def _handle_evaluate_confidence(self, args: Dict) -> Dict:
        """评估查询的决策置信度"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}

        query = args.get("query", "")
        available_actions = args.get("available_actions", [])

        return self.decision_engine.get_confidence_assessment(query, available_actions)

    def _handle_trigger_reflection(self, args: Dict) -> Dict:
        """触发元认知自我反思"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}

        return self.decision_engine.reflect()

    def _handle_record_correction(self, args: Dict) -> Dict:
        """记录用户纠正"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}

        self.decision_engine.record_user_correction(
            original_query=args.get("original_query", ""),
            wrong_action=args.get("wrong_action", ""),
            correct_action=args.get("correct_action", ""),
        )

        return {"status": "recorded", "message": "纠正已记录，下次会避免同样的错误"}

    def _handle_get_cognitive_stats(self, args: Dict) -> Dict:
        """获取认知系统全量统计"""
        stats = {}

        if self.world_model:
            stats["world_model"] = self.world_model.get_stats()
        if self.semantic_cache:
            stats["semantic_cache"] = self.semantic_cache.get_stats()
        if self.learning_loop:
            stats["learning_loop"] = self.learning_loop.get_stats()
        if self.prompt_engine:
            stats["prompt_engine"] = self.prompt_engine.get_stats()
        if self.decision_engine:
            stats["user_model"] = self.decision_engine.get_user_model_stats()
            stats["meta_cognition"] = self.decision_engine.get_meta_cognition_stats()
            stats["self_model"] = self.decision_engine.get_self_model_stats()
            stats["need_engine"] = self.decision_engine.get_need_engine_stats()
            stats["emotion"] = self.decision_engine.get_emotion_stats()
            stats["memory_stream"] = self.decision_engine.get_memory_stream_stats()
            stats["living_graph"] = self.decision_engine.get_living_graph_stats()

        return stats

    # ── 新增生命体工具 ───────────────────────────────────

    def _handle_get_self_info(self, args: Dict) -> Dict:
        """获取自我认知"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_self_model_stats()

    def _handle_get_needs(self, args: Dict) -> Dict:
        """获取内部需求"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_need_engine_stats()

    def _handle_get_emotion(self, args: Dict) -> Dict:
        """获取情绪状态"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_emotion_stats()

    def _handle_get_stream_insights(self, args: Dict) -> Dict:
        """获取联想洞察"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_memory_stream_stats()

    def _handle_diffuse_memory(self, args: Dict) -> Dict:
        """扩散激活记忆"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        query = args.get("query", "")
        results = self.decision_engine.diffuse_memory(query)
        return {"query": query, "activations": results, "count": len(results)}

    def _handle_get_graph_stats(self, args: Dict) -> Dict:
        """获取图谱统计"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_living_graph_stats()

    def _handle_get_inner_thoughts(self, args: Dict) -> Dict:
        """获取内心独白"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        count = args.get("count", 10)
        stats = self.decision_engine.get_inner_loop_stats()
        thoughts = stats.get("recent_thoughts", [])
        return {"thoughts": thoughts[-count:], "count": len(thoughts)}

    def _handle_get_narrative(self, args: Dict) -> Dict:
        """获取自我叙事"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        narrative = self.decision_engine.get_narrative()
        return {"narrative": narrative}

    # ========== 资源处理器 ==========

    def _get_devices_resource(self) -> Dict:
        if self.world_model:
            devices = self.world_model.get_all_devices()
            return {
                "devices": [
                    {
                        "device_id": d.device_id,
                        "online": d.online,
                        "capabilities": d.capabilities,
                        "current_action": d.current_action,
                    }
                    for d in devices.values()
                ]
            }

        if self.device_manager:
            devices = self.device_manager.GetAllDevices()
            return {
                "devices": [
                    {"device_id": d.DeviceID, "online": d.Online, "last_seen": d.LastSeen}
                    for d in devices
                ]
            }

        return {"devices": [], "error": "设备管理器未初始化"}

    def _get_skills_resource(self) -> Dict:
        if not self.skill_registry:
            return {"skills": [], "error": "技能网络未初始化"}

        skills = self.skill_registry.GetAllSkills()
        return {
            "skills": [
                {
                    "id": s.ID, "name": s.Name, "category": s.Category,
                    "description": s.Description, "weight": round(s.Weight, 3),
                    "use_count": s.UseCount,
                }
                for s in skills
            ]
        }

    def _get_memory_stats_resource(self) -> Dict:
        if not self.memory_engine:
            return {"error": "记忆系统未初始化"}
        return self.memory_engine.stats()

    def _get_world_state_resource(self) -> Dict:
        if not self.world_model:
            return {"error": "世界模型未初始化"}
        return self.world_model.stats()

    def _get_learning_stats_resource(self) -> Dict:
        if not self.learning_loop:
            return {"error": "学习闭环未初始化"}
        return self.learning_loop.stats()

    def _get_user_profile_resource(self) -> Dict:
        """用户画像资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_user_model_stats()

    def _get_meta_stats_resource(self) -> Dict:
        """元认知统计资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_meta_cognition_stats()

    def _get_self_model_resource(self) -> Dict:
        """自我认知资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_self_model_stats()

    def _get_needs_resource(self) -> Dict:
        """内部需求资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_need_engine_stats()

    def _get_emotion_resource(self) -> Dict:
        """情绪状态资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_emotion_stats()

    def _get_stream_insights_resource(self) -> Dict:
        """联想洞察资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_memory_stream_stats()

    def _get_living_graph_resource(self) -> Dict:
        """活体图谱资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_living_graph_stats()

    def _get_inner_loop_resource(self) -> Dict:
        """内心循环资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return self.decision_engine.get_inner_loop_stats()

    def _get_narrative_resource(self) -> Dict:
        """自我叙事资源"""
        if not self.decision_engine:
            return {"error": "决策引擎未初始化"}
        return {"narrative": self.decision_engine.get_narrative()}

    def stats(self) -> Dict:
        return {
            "tools_count": len(self.tools),
            "resources_count": len(self.resources),
            "notifications_count": len(self.notifications),
        }
