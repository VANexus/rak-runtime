"""
大脑 MCP 服务器 — 让外部 Agent（Claude Code 等）能发现和调用大脑的"神经元"。

基于官方 fastmcp（mcp 协议 SDK），把认知模块的能力暴露为标准 MCP 工具：
- 执行动作 / 查记忆 / 查设备 / 预测结果
- 情绪 / 需求 / 自我认知 / 内心独白
- 反思 / 纠正 / 图谱扩散 / 认知统计

用法：
    python -m src.mcp.fastmcp_server                # stdio 传输
    python -m src.mcp.fastmcp_server --http 8001    # streamable HTTP
"""

import argparse
import json
import logging

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rak.mcp")

from src.core import decision_engine as de


def _safe(fn, default=None):
    """调用认知模块，失败返回 default（降级原则）"""
    try:
        return fn()
    except Exception as e:
        logger.warning("[MCP] 工具调用失败: %s", e)
        return default


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "rak-brain",
        instructions="Rak 具身智能大脑。可通过这些工具查询认知状态、检索记忆、执行动作。",
    )

    @mcp.tool()
    def execute_action(action: str, device_id: str = "", params: dict | None = None) -> str:
        """执行一个原子动作。直接指定动作名和参数。"""
        from src.core.permissions import get_permission_policy
        # 权限门：设备动作需确认时返回确认，不直接执行（emergency_stop 永远放行）
        decision = get_permission_policy().evaluate(action)
        if decision.verdict == "deny":
            return json.dumps({"action": action, "status": "denied",
                               "reason": decision.reason}, ensure_ascii=False)
        if decision.verdict == "ask":
            return json.dumps({"action": action, "status": "needs_confirmation",
                               "reason": decision.reason,
                               "params": params or {}}, ensure_ascii=False)

        class MockRequest:
            def __init__(self):
                self.trace_id = f"mcp_{json.dumps(params or {}, ensure_ascii=False)[:20]}"
                self.state = "mcp_direct_call"
                self.available_actions = [action]
                self.action = action
                self.params_json = json.dumps(params or {}, ensure_ascii=False)

        engine = _safe(lambda: de._get_memory_engine())
        result = _safe(lambda: __import__("src.core.decision_engine", fromlist=["DecisionEngine"]).DecisionEngine().decide(MockRequest()), {})
        return json.dumps({"action": action, "device_id": device_id, "decision": result}, ensure_ascii=False)

    @mcp.tool()
    def search_memory(query: str, memory_type: str = "", top_k: int = 5) -> str:
        """搜索记忆系统，查找相关的经验、知识或历史事件。"""
        mem = de._get_memory_engine()
        if mem is None:
            return json.dumps({"error": "记忆系统未初始化"}, ensure_ascii=False)
        types = [memory_type] if memory_type else None
        results = mem.recall(query, top_k=top_k, memory_types=types)
        return json.dumps({
            "query": query,
            "results": [
                {"content": r.entry.content, "memory_type": r.entry.memory_type,
                 "score": round(r.score, 4)}
                for r in results
            ],
        }, ensure_ascii=False)

    @mcp.tool()
    def query_device(device_id: str) -> str:
        """查询设备的当前状态和能力。"""
        wm = de._get_world_model()
        if wm is None:
            return json.dumps({"error": "世界模型未初始化"}, ensure_ascii=False)
        dev = wm.get_device(device_id)
        if dev is None:
            return json.dumps({"error": f"设备不存在: {device_id}"}, ensure_ascii=False)
        return json.dumps({
            "device_id": dev.device_id, "online": dev.online,
            "capabilities": dev.capabilities, "current_action": dev.current_action,
            "sensors": dev.sensors,
        }, ensure_ascii=False)

    @mcp.tool()
    def predict_outcome(device_id: str, action: str, params: dict | None = None) -> str:
        """预测执行某个动作后的结果状态。用于动作规划前的'想象'。"""
        wm = de._get_world_model()
        if wm is None:
            return json.dumps({"error": "世界模型未初始化"}, ensure_ascii=False)
        pred = wm.predict_next_state(device_id=device_id, action=action, params=params or {})
        if pred is None:
            return json.dumps({"error": "无法预测"}, ensure_ascii=False)
        return json.dumps({
            "device_id": pred.device_id, "action": pred.action,
            "predicted_state": pred.predicted_state, "confidence": round(pred.confidence, 3),
        }, ensure_ascii=False)

    @mcp.tool()
    def diffuse_memory(query: str) -> str:
        """从一个概念开始扩散激活记忆网络。返回联想链路上的所有激活节点。"""
        graph = de._get_living_graph()
        if graph is None:
            return json.dumps({"error": "图谱未初始化"}, ensure_ascii=False)
        results = graph.diffuse_from_text(query)
        return json.dumps({
            "query": query,
            "activations": [
                {"label": r.label, "energy": r.energy, "depth": r.depth, "path": r.path}
                for r in results[:10]
            ],
        }, ensure_ascii=False)

    @mcp.tool()
    def get_emotion() -> str:
        """获取大脑当前的六维情绪状态。"""
        emo = de._get_emotion_engine()
        if emo is None:
            return json.dumps({"error": "情绪引擎未初始化"}, ensure_ascii=False)
        return json.dumps(emo.get_stats(), ensure_ascii=False)

    @mcp.tool()
    def get_needs() -> str:
        """获取大脑的内部需求向量（学习/稳定/探索/休息/社交/安全）。"""
        need = de._get_need_engine()
        if need is None:
            return json.dumps({"error": "需求引擎未初始化"}, ensure_ascii=False)
        return json.dumps(need.get_stats(), ensure_ascii=False)

    @mcp.tool()
    def get_self_info() -> str:
        """获取大脑的自我认知：我是谁、我会什么、我的性格、当前状态。"""
        sm = de._get_self_model()
        if sm is None:
            return json.dumps({"error": "自我模型未初始化"}, ensure_ascii=False)
        return json.dumps(sm.get_stats(), ensure_ascii=False)

    @mcp.tool()
    def reflect() -> str:
        """触发元认知自我反思，分析最近决策质量并提取教训。"""
        meta = de._get_meta_cognition()
        if meta is None:
            return json.dumps({"error": "元认知未初始化"}, ensure_ascii=False)
        return json.dumps(meta.reflect(), ensure_ascii=False)

    @mcp.tool()
    def record_correction(original_query: str, wrong_action: str, correct_action: str) -> str:
        """记录用户对决策的纠正。这是最强的学习信号。"""
        engine = de._get_llm_client()  # 确保模块已加载
        de.DecisionEngine().record_user_correction(original_query, wrong_action, correct_action)
        return json.dumps({"status": "recorded", "message": "纠正已记录"}, ensure_ascii=False)

    @mcp.tool()
    def get_graph_stats() -> str:
        """获取活体知识图谱的统计：节点数、边数、最活跃节点。"""
        graph = de._get_living_graph()
        if graph is None:
            return json.dumps({"error": "图谱未初始化"}, ensure_ascii=False)
        return json.dumps(graph.get_stats(), ensure_ascii=False)

    @mcp.tool()
    def get_inner_thoughts(count: int = 10) -> str:
        """获取大脑最近的内心独白——即使没有用户输入也在产生的想法。"""
        inner = de._get_inner_loop()
        if inner is None:
            return json.dumps({"error": "内心循环未初始化"}, ensure_ascii=False)
        return json.dumps(inner.get_recent_thoughts(count), ensure_ascii=False)

    @mcp.tool()
    def get_narrative() -> str:
        """获取大脑的自我叙事——'我最近在想什么'。"""
        inner = de._get_inner_loop()
        if inner is None:
            return json.dumps({"error": "内心循环未初始化"}, ensure_ascii=False)
        return json.dumps({"narrative": inner.get_narrative()}, ensure_ascii=False)

    @mcp.tool()
    def get_cognitive_stats() -> str:
        """获取认知系统的全量统计。"""
        stats = {}
        for key, getter in [
            ("world_model", de._get_world_model), ("semantic_cache", de._get_semantic_cache),
            ("learning_loop", de._get_learning_loop), ("prompt_engine", de._get_prompt_engine),
            ("memory", de._get_memory_engine), ("meta_cognition", de._get_meta_cognition),
            ("user_model", de._get_user_model), ("emotion", de._get_emotion_engine),
            ("need", de._get_need_engine), ("living_graph", de._get_living_graph),
            ("inner_loop", de._get_inner_loop),
        ]:
            obj = _safe(getter)
            if obj is not None and hasattr(obj, "stats"):
                stats[key] = _safe(lambda o=obj: o.stats())
            elif obj is not None:
                stats[key] = str(obj)
        return json.dumps(stats, ensure_ascii=False, default=str)

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Rak 大脑 MCP 服务器")
    parser.add_argument("--http", type=int, default=0, help="HTTP 端口（0 = stdio）")
    args = parser.parse_args()

    mcp = create_mcp_server()
    if args.http:
        logger.info("大脑 MCP 服务器启动（HTTP :%d）", args.http)
        mcp.run(transport="http", host="0.0.0.0", port=args.http)
    else:
        logger.info("大脑 MCP 服务器启动（stdio）")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
