"""
统一大脑入口（Brain Facade）— harness 的核心抽象。

CLI / A2A / benchmark / harness 各组件此前各自构建 SimpleNamespace 请求 +
DecisionEngine().decide()（三处重复）。这里收拢为单一入口：

    run_brain(text, trace_id, source) -> dict

所有文本 → 决策的调用统一走此函数；trace_id/source 用于区分调用方，
available_actions 可覆盖（默认 14 动作 MVP 集）。
"""

import os
from typing import Optional

# 14 动作 MVP 集（与 go-kernel / rak-esp 契约一致）
DEFAULT_ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "move_forward", "move_back", "turn_left", "turn_right",
    "dance", "nod", "light_on", "light_off",
    "emergency_stop", "idle",
]


def run_brain(text: str, trace_id: str = "harness", source: str = "harness",
              available_actions: Optional[list] = None) -> dict:
    """统一大脑入口：用户文本 → 决策 dict（走完整 DecisionEngine 链路）。"""
    from types import SimpleNamespace
    from src.core.decision_engine import DecisionEngine

    actions = list(available_actions or DEFAULT_ACTIONS)
    req = SimpleNamespace(
        version="v0",
        trace_id=trace_id or f"harness-{abs(hash(text)) % 10**6}",
        source=source,
        target="runtime:default",
        action="",
        state=text,
        available_actions=actions,
        params_json="{}",
    )
    return DecisionEngine().decide(req)


def run_brain_single_shot(text: str, trace_id: str = "harness-single",
                          source: str = "harness",
                          available_actions: Optional[list] = None) -> dict:
    """
    基线路径：强制 RAK_AGENT=0（单发 JSON 深思），走完 decide 后恢复环境。
    用于与 Agent 内核路径（LangGraph 工具循环）做 A/B 对比。
    """
    saved = os.environ.get("RAK_AGENT")
    os.environ["RAK_AGENT"] = "0"
    try:
        return run_brain(text, trace_id=trace_id, source=source,
                         available_actions=available_actions)
    finally:
        if saved is None:
            os.environ.pop("RAK_AGENT", None)
        else:
            os.environ["RAK_AGENT"] = saved
