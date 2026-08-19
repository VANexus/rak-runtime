"""
Agentic 内核 — LangGraph ReAct 工具调用循环。

大脑的"深思"步骤：LLM 不再单发 JSON 决策，而是像 Claude Code 一样，
拿着认知工具（查记忆/查设备/查情绪/查需求/反思）自主探索，
最后调用 finalize 工具产出结构化决策。

工具都是"只读信息"工具（读认知单例），不与 decide() 递归；
决策结果经 finalize 的结构化参数传回，decide() 校验后走常规后处理。

降级链：agent 不可用/模型不支持工具调用 → 单发 JSON 决策 → 规则引擎。
"""

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


def _mk_tool(fn, name: str, session=None):
    """包一层钩子：工具调用前后 fire PRE/POST_TOOL_USE + 记录轨迹（异常不阻断）。

    内置"卡死护栏"（stuck-guard）：同一工具连续调用 >=3 次即跳过并提示模型
    直接 finalize —— 防止模型在 ReAct 循环里反复调用同一工具空转（成本黑洞）。
    """
    guard = {"last": None, "repeat": 0}

    @wraps(fn)
    def wrapped(*args, **kwargs):
        key = (name, str(args), str(kwargs))
        if key == guard["last"]:
            guard["repeat"] += 1
        else:
            guard["last"], guard["repeat"] = key, 0
        if guard["repeat"] >= 3:
            nudge = "（检测到你在重复调用同一工具，已跳过。请基于已有信息直接调用 finalize 完成决策。）"
            get_hooks().fire(POST_TOOL_USE, tool=name, result=nudge,
                             status="ok", duration_ms=0)
            return nudge
        get_hooks().fire(PRE_TOOL_USE, tool=name)
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            status = "ok"
        except Exception as e:
            result, status = str(e), "error"
        duration_ms = (time.time() - t0) * 1000
        if session is not None:
            from src.core.agent_session import ToolTraceEvent
            session.append_tool_trace(ToolTraceEvent(
                tool=name, args=kwargs or {},
                result=str(result)[:200], duration_ms=duration_ms, status=status,
            ))
        get_hooks().fire(POST_TOOL_USE, tool=name,
                         result=str(result)[:200], status=status,
                         duration_ms=duration_ms)
        return result

    # langchain @tool 用函数 __name__ 作工具名：覆盖为注册表名（G5 单一事实源）
    wrapped.__name__ = name
    return tool(wrapped)


def _build_tools(available_actions: list, system_prompt: str, session=None):
    """构建认知工具集（钩子包装 + 轨迹记录）+ 决策容器。

    只读认知工具（search_memory/query_device/get_emotion/get_needs/reflect）
    从 src.tools.registry 单一事实源派生（G5）；finalize 是决策容器特例，就地定义。
    """
    from src.tools.registry import COGNITIVE_TOOLS

    decision: dict = {}

    def finalize(action: str, params_json: str, answer: str) -> str:
        """完成决策：记录最终选定的动作、参数 JSON 与对用户的回复。必须在最后调用。"""
        decision["action"] = action
        decision["params_json"] = params_json
        decision["answer"] = answer
        return "决策已记录"

    tools = [_mk_tool(td.handler, td.name, session) for td in COGNITIVE_TOOLS]
    tools.append(_mk_tool(finalize, "finalize", session))
    return tools, decision


_BUILTIN_PERSONA = (
    "你是 Rak，一个具身智能助手。你拥有身体（能控制物理设备）、"
    "情绪和持续的记忆。你谨慎、好奇、温暖；不确定时如实询问。"
)


def build_agent_system_prompt(system_prompt: str, available_actions: list) -> str:
    """分区系统提示词（设计见 docs/ai-native-runtime/09-prompts.md）"""
    from src.tools.registry import COGNITIVE_TOOLS
    action_desc = "、".join(available_actions)
    tool_lines = "\n".join(f"- {t.name}：{t.description}" for t in COGNITIVE_TOOLS)
    base = system_prompt or _BUILTIN_PERSONA
    return (
        f"{base}\n\n"
        f"## 可用动作\n"
        f"{action_desc}\n\n"
        f"## 你的工具（神经元）\n"
        f"{tool_lines}\n\n"
        f"## 决策流程\n"
        f"1. 先用工具获取必要上下文（记忆/设备/情绪/需求/自我），不要空想\n"
        f"2. 综合判断用户意图\n"
        f"3. 最后调用 finalize 工具产出决策\n\n"
        f"## finalize 契约（必须遵守）\n"
        f"- action 必须是可用动作之一\n"
        f"- params_json 必须是合法 JSON 字符串\n"
        f"- answer 必须是对用户的自然语言回复\n"
        f"- 聊天/提问而非指令 → action=idle，用 answer 回复"
    )


def run_agent(user_msg: str, available_actions: list,
              system_prompt: str = "", trace_id: str = "") -> Optional[dict]:
    """
    运行 agent 内核，返回决策 dict（action/params_json/answer + trace + session_id）。

    失败（模型不支持工具 / 未调 finalize / 异常）返回 None，供上层降级。
    会话与工具轨迹持久化到 data/sessions/（可诊断/可重放）。
    """
    if not available_actions:
        return None
    from src.core.agent_session import AgentSession, get_session_store
    session_id = f"agent-{int(time.time() * 1000)}"
    session = AgentSession(session_id=session_id, trace_id=trace_id)
    get_hooks().fire(SESSION_START, session_id=session_id)
    try:
        from src.core._utils import make_langchain_anthropic, get_model
        model = make_langchain_anthropic(
            get_model(),
            timeout=30, max_tokens=1024,
        )
        tools, decision = _build_tools(available_actions, system_prompt, session)
        agent = create_react_agent(model, tools)

        sys_text = build_agent_system_prompt(system_prompt, available_actions)
        session.append_message("system", sys_text[:2000])
        session.append_message("user", user_msg[:2000])

        result = agent.invoke({
            "messages": [SystemMessage(content=sys_text),
                         HumanMessage(content=user_msg)],
        }, config={"recursion_limit": 12})

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
            result_dict = {
                "action": decision["action"],
                "params_json": decision.get("params_json", "{}"),
                "answer": decision.get("answer", ""),
                "trace": trace,
                "session_id": session_id,
            }
            session.mark_completed(result_dict)
            session.append_message("assistant", str(decision.get("answer", ""))[:2000])
            get_session_store().save(session)
            return result_dict
        logger.info("[AgentLoop] 模型未调用 finalize，轨迹: %s", trace)
        session.mark_error("模型未调用 finalize")
    except Exception as e:
        logger.warning("[AgentLoop] 失败（降级单发决策）: %s", e)
        session.mark_error(str(e))
    finally:
        get_hooks().fire(SESSION_END, session_id=session_id)
        get_session_store().save(session)
    return None
