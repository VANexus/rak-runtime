"""
工具注册表（Tool Registry）— 大脑全部能力的单一事实源（G5）。

此前三种工具形态各自为政：agent_loop 的 LangGraph @tool、fastmcp 的 MCP 工具、
a2a 的 Agent Card skills，同一认知能力在三处重复实现，接口漂移。

这里收拢为 ToolDef 单一事实源：加一个能力 = 改 registry 一处，三种形态自动派生。

ToolDef 字段借鉴 Claude Code 的工具元数据（category / permission / token_budget）。

当前范围：cognitive 类只读"神经元"（查记忆/查设备/查情绪/查需求/反思），
是 agent_loop 与 fastmcp 的共享集。finalize（决策容器）与 device 类动作工具
形态差异大，仍由各自调用方特判，后续再并入。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, List

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    """一个工具的单一定义：名称 / 描述 / 分类 / 权限 / 返回预算 / 处理函数"""
    name: str
    description: str
    category: str                  # cognitive | meta | device | system
    handler: Callable              # 纯 Python 函数（无副作用读取认知单例）
    permission: str = "allow"      # allow | ask | deny（见 permissions.py）
    token_budget: int = 500        # 返回截断（渐进披露第一层）


# ========== 认知神经元 handlers（只读，无副作用） ==========

def _search_memory(query: str, top_k: int = 5) -> str:
    """检索记忆系统，查找相关经验、知识或历史事件。"""
    from src.core import decision_engine as de
    mem = de._get_memory_engine()
    if mem is None:
        return "（记忆系统不可用）"
    results = mem.recall(query, top_k=top_k)
    return json.dumps([
        {"content": r.entry.content, "type": r.entry.memory_type}
        for r in results
    ], ensure_ascii=False)[:500]


def _query_device(device_id: str = "") -> str:
    """查询设备当前状态和能力。"""
    from src.core import decision_engine as de
    wm = de._get_world_model()
    if wm is None:
        return "（世界模型不可用）"
    if device_id:
        dev = wm.get_device(device_id)
        if dev:
            return json.dumps({
                "device_id": dev.device_id, "online": dev.online,
                "capabilities": dev.capabilities,
            }, ensure_ascii=False)
        return f"设备 {device_id} 未知"
    return wm.format_device_state()[:500]


def _get_emotion() -> str:
    """查询大脑当前情绪状态。"""
    from src.core import decision_engine as de
    emo = de._get_emotion_engine()
    return emo.state.describe() if emo else "（情绪引擎不可用）"


def _get_needs() -> str:
    """查询大脑当前内部需求。"""
    from src.core import decision_engine as de
    need = de._get_need_engine()
    if need:
        need.update()
        return need.needs.describe()
    return "（需求引擎不可用）"


def _reflect() -> str:
    """触发元认知自我反思，返回洞察。"""
    from src.core import decision_engine as de
    meta = de._get_meta_cognition()
    if meta is None:
        return "（元认知不可用）"
    return json.dumps(meta.reflect(), ensure_ascii=False)[:500]


def _safe_read(fn, fallback: str) -> str:
    """只读认知调用包裹：任何异常降级为 fallback（永不抛，窄腰原则）。"""
    try:
        out = fn()
        if out is None:
            return fallback
        return str(out)[:500]
    except Exception as e:
        logging.getLogger(__name__).warning("[Registry] %s 读取失败: %s",
                                            getattr(fn, "__name__", "tool"), e)
        return fallback


def _diffuse_memory(query: str) -> str:
    """从概念出发扩散激活记忆网络，返回联想链路上的激活节点。"""
    from src.core import decision_engine as de
    return _safe_read(lambda: json.dumps(
        de.DecisionEngine().diffuse_memory(query), ensure_ascii=False), "（扩散不可用）")


def _get_self_info() -> str:
    """查询大脑自我认知：我是谁、能力、性格、当前状态。"""
    from src.core import decision_engine as de
    sm = de._get_self_model()
    if sm is None:
        return "（自我模型不可用）"
    return _safe_read(sm.who_am_i, "（自我认知不可用）")


def _get_inner_thoughts() -> str:
    """查询大脑最近的内心独白——即使没有用户输入也在产生的想法。"""
    from src.core import decision_engine as de
    inner = de._get_inner_loop()
    if inner is None:
        return "（内心循环不可用）"
    return _safe_read(lambda: json.dumps(inner.get_recent_thoughts(10), ensure_ascii=False),
                      "（内心独白不可用）")


def _get_graph_stats() -> str:
    """查询活体知识图谱统计：节点/边/最活跃节点。"""
    from src.core import decision_engine as de
    graph = de._get_living_graph()
    if graph is None:
        return "（图谱不可用）"
    return _safe_read(lambda: json.dumps(graph.get_stats(), ensure_ascii=False), "（图谱统计不可用）")


def _get_cognitive_stats() -> str:
    """查询认知系统全量统计（记忆/元认知/用户模型/情绪等）。"""
    from src.core import decision_engine as de
    engine = de.DecisionEngine()
    seen = {
        "memory": engine.get_memory_stats(),
        "meta_cognition": engine.get_meta_cognition_stats(),
        "user_model": engine.get_user_model_stats(),
        "emotion": engine.get_emotion_stats(),
        "need": engine.get_need_engine_stats(),
        "inner_loop": engine.get_inner_loop_stats(),
    }
    return _safe_read(lambda: json.dumps(seen, ensure_ascii=False, default=str),
                      "（认知统计不可用）")


# ========== 单一事实源：认知工具清单 ==========

COGNITIVE_TOOLS: List[ToolDef] = [
    ToolDef(name="search_memory", description="检索记忆系统，查找相关经验、知识或历史事件。",
            category="cognitive", handler=_search_memory),
    ToolDef(name="query_device", description="查询设备当前状态和能力。",
            category="cognitive", handler=_query_device),
    ToolDef(name="get_emotion", description="查询大脑当前情绪状态。",
            category="cognitive", handler=_get_emotion),
    ToolDef(name="get_needs", description="查询大脑当前内部需求。",
            category="cognitive", handler=_get_needs),
    ToolDef(name="reflect", description="触发元认知自我反思，返回洞察。",
            category="cognitive", handler=_reflect),
    ToolDef(name="diffuse_memory", description="从概念出发扩散激活记忆网络，返回联想链路上的激活节点。",
            category="cognitive", handler=_diffuse_memory),
    ToolDef(name="get_self_info", description="查询大脑自我认知：我是谁、能力、性格、当前状态。",
            category="cognitive", handler=_get_self_info),
    ToolDef(name="get_inner_thoughts", description="查询大脑最近的内心独白，了解自己此刻在想什么。",
            category="cognitive", handler=_get_inner_thoughts),
    ToolDef(name="get_graph_stats", description="查询活体知识图谱统计：节点、边、最活跃概念。",
            category="cognitive", handler=_get_graph_stats),
    ToolDef(name="get_cognitive_stats", description="查询认知系统全量统计（记忆/元认知/用户模型/情绪等）。",
            category="cognitive", handler=_get_cognitive_stats),
]


def get_tool_defs(category: str = None) -> List[ToolDef]:
    """按分类获取工具定义（None = 全量）"""
    if category is None:
        return list(COGNITIVE_TOOLS)
    return [t for t in COGNITIVE_TOOLS if t.category == category]
