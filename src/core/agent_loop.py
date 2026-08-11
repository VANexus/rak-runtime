"""
Agentic 内核 — LangGraph ReAct 工具调用循环。

大脑的"深思"步骤：LLM 不再单发 JSON 决策，而是像 Claude Code 一样，
拿着认知工具（查记忆/查设备/查情绪/查需求/反思）自主探索，
最后调用 finalize 工具产出结构化决策。

工具都是"只读信息"工具（读认知单例），不与 decide() 递归；
决策结果经 finalize 的结构化参数传回，decide() 校验后走常规后处理。

降级链：agent 不可用/模型不支持工具调用 → 单发 JSON 决策 → 规则引擎。
"""

import json
import logging
import os
import time
from functools import wraps
from typing import Optional

logger = logging.getLogger(__name__)

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from src.core.hooks import (
    get_hooks, PRE_TOOL_USE, POST_TOOL_USE, SESSION_START, SESSION_END,
)


def _mk_tool(fn, name: str):
    """包一层钩子：工具调用前后 fire PRE/POST_TOOL_USE（异常不阻断，降级原则）"""
    @tool
    @wraps(fn)
    def wrapped(*args, **kwargs):
        get_hooks().fire(PRE_TOOL_USE, tool=name)
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            status = "ok"
        except Exception as e:
            result, status = str(e), "error"
        get_hooks().fire(POST_TOOL_USE, tool=name,
                         result=str(result)[:200], status=status,
                         duration_ms=(time.time() - t0) * 1000)
        return result
    return wrapped


def _build_tools(available_actions: list, system_prompt: str):
    """构建认知工具集（钩子包装）+ 决策容器"""
    decision: dict = {}

    def search_memory(query: str, top_k: int = 5) -> str:
        """搜索记忆系统，查找相关经验、知识或历史事件。"""
        from src.core import decision_engine as de
        mem = de._get_memory_engine()
        if mem is None:
            return "（记忆系统不可用）"
        results = mem.recall(query, top_k=top_k)
        return json.dumps([
            {"content": r.entry.content, "type": r.entry.memory_type}
            for r in results
        ], ensure_ascii=False)[:500]

    def query_device(device_id: str = "") -> str:
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

    def get_emotion() -> str:
        """查询大脑当前情绪状态。"""
        from src.core import decision_engine as de
        emo = de._get_emotion_engine()
        return emo.state.describe() if emo else "（情绪引擎不可用）"

    def get_needs() -> str:
        """查询大脑当前内部需求。"""
        from src.core import decision_engine as de
        need = de._get_need_engine()
        if need:
            need.update()
            return need.needs.describe()
        return "（需求引擎不可用）"

    def reflect() -> str:
        """触发元认知自我反思，返回洞察。"""
        from src.core import decision_engine as de
        meta = de._get_meta_cognition()
        if meta is None:
            return "（元认知不可用）"
        return json.dumps(meta.reflect(), ensure_ascii=False)[:500]

    def finalize(action: str, params_json: str, answer: str) -> str:
        """完成决策：记录最终选定的动作、参数 JSON 与对用户的回复。必须在最后调用。"""
        decision["action"] = action
        decision["params_json"] = params_json
        decision["answer"] = answer
        return "决策已记录"

    return [
        _mk_tool(search_memory, "search_memory"),
        _mk_tool(query_device, "query_device"),
        _mk_tool(get_emotion, "get_emotion"),
        _mk_tool(get_needs, "get_needs"),
        _mk_tool(reflect, "reflect"),
        _mk_tool(finalize, "finalize"),
    ], decision


def run_agent(user_msg: str, available_actions: list,
              system_prompt: str = "") -> Optional[dict]:
    """
    运行 agent 内核，返回决策 dict（action/params_json/answer + trace）。

    失败（模型不支持工具 / 未调 finalize / 异常）返回 None，供上层降级。
    """
    if not available_actions:
        return None
    session_id = f"agent-{int(time.time() * 1000)}"
    get_hooks().fire(SESSION_START, session_id=session_id)
    try:
        from src.core._utils import make_langchain_anthropic
        model = make_langchain_anthropic(
            os.getenv("ANTHROPIC_MODEL", "mimo-v2.5-pro"),
            timeout=30, max_tokens=1024,
        )
        tools, decision = _build_tools(available_actions, system_prompt)
        agent = create_react_agent(model, tools)

        action_desc = "、".join(available_actions)
        sys_text = (
            f"{system_prompt}\n\n"
            f"## 工具使用规则\n"
            f"1. 你可以调用 search_memory/query_device/get_emotion/get_needs/reflect "
            f"获取上下文后再决策。\n"
            f"2. 可用动作必须在以下集合内：{action_desc}\n"
            f"3. 决策完成后必须调用 finalize 工具，action 必须是集合内动作，"
            f"params_json 是合法 JSON 字符串，answer 是对用户的自然语言回复。\n"
            f"4. 如果用户在聊天/提问而非下指令，action 选 idle，用 answer 回复。"
        )

        result = agent.invoke({
            "messages": [SystemMessage(content=sys_text),
                         HumanMessage(content=user_msg)],
        })

        # 提取工具调用轨迹
        trace = []
        for m in result.get("messages", []):
            mtype = getattr(m, "type", "")
            if mtype == "tool":
                trace.append(f"tool:{getattr(m, 'name', '?')}")
            elif mtype == "ai" and getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    trace.append(f"llm→{tc.get('name', '?')}")

        if decision.get("action"):
            return {
                "action": decision["action"],
                "params_json": decision.get("params_json", "{}"),
                "answer": decision.get("answer", ""),
                "trace": trace,
            }
        logger.info("[AgentLoop] 模型未调用 finalize，轨迹: %s", trace)
    except Exception as e:
        logger.warning("[AgentLoop] 失败（降级单发决策）: %s", e)
    finally:
        get_hooks().fire(SESSION_END, session_id=session_id)
    return None
