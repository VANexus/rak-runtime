# src/core/decision_engine.py
import json
import logging
import os
from typing import List, Dict

logger = logging.getLogger(__name__)

# LLM 客户端（延迟初始化）
_llm_client = None


def _get_llm_client():
    """延迟初始化 Anthropic 客户端"""
    global _llm_client
    if _llm_client is None:
        try:
            import anthropic
            _llm_client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
                base_url=os.getenv(
                    "ANTHROPIC_BASE_URL",
                    "https://token-plan-cn.xiaomimimo.com/anthropic",
                ),
                timeout=5.0,  # 5 秒超时
            )
            logger.info("Anthropic LLM 客户端初始化成功")
        except Exception as e:
            logger.warning(f"Anthropic LLM 初始化失败: {e}，回退到规则引擎")
            _llm_client = False  # 标记为不可用
    return _llm_client if _llm_client is not False else None


def _build_system_prompt(available_actions: List[str]) -> str:
    """构建 LLM 系统提示"""
    actions_desc = "\n".join(f"- {a}" for a in available_actions)
    return f"""你是一个嵌入式设备决策引擎。你的任务是从可用动作列表中选择最合适的动作并生成参数。

## 可用动作
{actions_desc}

## 规则
1. 你必须且只能选择上述列表中的一个动作
2. params_json 必须是合法的 JSON 字符串
3. 参数应根据上下文合理设置（如速度、角度、距离等）
4. 如果上下文信息不足以判断，选择最安全/最保守的动作

## 输出格式
返回一个 JSON 对象，包含：
- "action": 选择的动作名（必须在可用列表中）
- "params_json": 参数 JSON 字符串
- "reasoning": 简短的决策理由（中文）"""


def _llm_decide(state: str, available_actions: List[str], action: str = "", params_json: str = "") -> dict:
    """调用 LLM 进行决策（带超时）"""
    import threading

    client = _get_llm_client()
    if client is None:
        return None  # LLM 不可用，回退到规则引擎

    model = os.getenv("ANTHROPIC_MODEL", "mimo-v2.5-pro")

    result = [None]
    exception = [None]

    def _call_llm():
        try:
            if action:
                user_msg = f"执行动作: {action}, 参数: {params_json or '{}'}"
            else:
                user_msg = f"状态: {state or '未知'}, 可用动作: {', '.join(available_actions)}"

            response = client.messages.create(
                model=model,
                max_tokens=256,
                system=_build_system_prompt(available_actions),
                messages=[{"role": "user", "content": user_msg}],
            )

            # 解析 LLM 响应（兼容 ThinkingBlock 和 TextBlock）
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    break
            if not text:
                return

            # 尝试提取 JSON
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]

            parsed = json.loads(text)

            # 验证动作在可用列表中
            chosen_action = parsed.get("action", "")
            if chosen_action not in available_actions:
                logger.warning(f"LLM 选择了不可用的动作 '{chosen_action}'，回退到第一个可用动作")
                chosen_action = available_actions[0]

            result[0] = {
                "status": "ok",
                "action": chosen_action,
                "params_json": parsed.get("params_json", "{}"),
            }
        except Exception as e:
            exception[0] = e

    # 在单独线程中调用 LLM，5 秒超时
    thread = threading.Thread(target=_call_llm, daemon=True)
    thread.start()
    thread.join(timeout=5.0)

    if thread.is_alive():
        logger.warning("LLM 调用超时（5秒），回退到规则引擎")
        return None

    if exception[0]:
        logger.error(f"LLM 决策失败: {exception[0]}")
        return None

    return result[0]


class DecisionEngine:
    def __init__(self):
        # 预初始化 LLM 客户端
        _get_llm_client()

    def decide(self, request) -> dict:
        """
        核心决策逻辑。
        优先使用 LLM，失败时回退到规则引擎。
        """
        trace_id = request.trace_id
        logger.info(f"[TraceID: {trace_id}] 决策引擎启动...")

        # 步骤 1: 输入校验
        validation_result = self._validate_request(request)
        if not validation_result["is_valid"]:
            return {
                "status": "error",
                "error_code": "INVALID_REQUEST",
                "error_message": validation_result["message"],
            }

        # 步骤 2: 尝试 LLM 决策
        llm_result = _llm_decide(
            state=request.state,
            available_actions=list(request.available_actions),
            action=request.action,
            params_json=request.params_json,
        )

        if llm_result is not None:
            logger.info(f"[TraceID: {trace_id}] LLM 决策完成: {llm_result.get('action')}")
            return llm_result

        # 步骤 3: 回退到规则引擎
        logger.info(f"[TraceID: {trace_id}] LLM 不可用，使用规则引擎")
        if request.action:
            decision = self._handle_action_confirmation(request)
        else:
            decision = self._handle_state_to_action(request)

        logger.info(f"[TraceID: {trace_id}] 规则引擎决策完成: {decision.get('action')}")
        return decision

    def _validate_request(self, request) -> dict:
        """请求校验逻辑"""
        if not request.available_actions:
            return {"is_valid": False, "message": "available_actions 不能为空"}

        if request.action and request.action not in request.available_actions:
            return {
                "is_valid": False,
                "message": f"动作 '{request.action}' 不在允许列表 {request.available_actions} 中",
            }

        if request.params_json:
            try:
                json.loads(request.params_json)
            except json.JSONDecodeError:
                return {"is_valid": False, "message": "params_json 不是有效的 JSON 格式"}

        return {"is_valid": True}

    def _handle_action_confirmation(self, request) -> dict:
        """规则引擎：动作确认模式"""
        return {
            "status": "ok",
            "action": request.action,
            "params_json": request.params_json,
        }

    def _handle_state_to_action(self, request) -> dict:
        """规则引擎：状态转动作模式"""
        if not request.available_actions:
            return {
                "status": "error",
                "error_code": "NO_AVAILABLE_ACTIONS",
                "error_message": "无可用动作",
            }

        chosen_action = request.available_actions[0]

        default_params = {}
        if chosen_action == "move_forward":
            default_params = {"distance_cm": 5, "speed": 50}
        elif chosen_action == "turn_left":
            default_params = {"angle_deg": 90, "speed": 30}

        return {
            "status": "ok",
            "action": chosen_action,
            "params_json": json.dumps(default_params, ensure_ascii=False),
        }
