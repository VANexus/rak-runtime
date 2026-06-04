# src/core/decision_engine.py
import json
import logging
import os
import struct
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 记忆引擎（延迟初始化）
_memory_engine = None


def _get_memory_engine():
    """延迟初始化认知记忆引擎"""
    global _memory_engine
    if _memory_engine is None:
        try:
            from src.core.memory_engine import CognitiveMemoryEngine
            _memory_engine = CognitiveMemoryEngine()
            logger.info("认知记忆引擎初始化成功")
        except Exception as e:
            logger.warning(f"记忆引擎初始化失败: {e}")
            _memory_engine = False
    return _memory_engine if _memory_engine is not False else None

# LLM 客户端（延迟初始化）
_llm_client = None

# ASR 实例（延迟初始化）
_asr_tool = None


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
                timeout=15.0,  # 15 秒超时（代理链路较长）
            )
            logger.info("Anthropic LLM 客户端初始化成功")
        except Exception as e:
            logger.warning(f"Anthropic LLM 初始化失败: {e}，回退到规则引擎")
            _llm_client = False  # 标记为不可用
    return _llm_client if _llm_client is not False else None


def _get_asr_tool():
    """延迟初始化 ASR 工具"""
    global _asr_tool
    if _asr_tool is None:
        try:
            from src.tools import ASRTool
            if ASRTool is not None:
                _asr_tool = ASRTool()
                logger.info("ASR Whisper 模型初始化成功")
            else:
                _asr_tool = False
                logger.warning("ASR 不可用（whisper 未安装）")
        except Exception as e:
            _asr_tool = False
            logger.warning(f"ASR 初始化失败: {e}")
    return _asr_tool if _asr_tool is not False else None


def _build_system_prompt(available_actions: List[str]) -> str:
    """构建 LLM 系统提示（单动作兼容）"""
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


def _build_decompose_prompt(available_actions: List[str]) -> str:
    """构建 LLM 多动作分解提示"""
    actions_desc = "\n".join(f"- {a}" for a in available_actions)
    return f"""你是一个嵌入式设备任务分解引擎。你的任务是将用户的自然语言指令分解为一系列原子动作。

## 可用原子动作
{actions_desc}

## 规则
1. 只能使用上述列表中的动作
2. 每个动作必须是独立可执行的原子操作
3. 按执行顺序排列
4. 每个动作都需要合理的参数
5. 如果指令模糊，选择最安全的解读

## 输出格式
返回一个 JSON 对象：
{{
  "actions": [
    {{"action": "动作名", "params_json": "{{}}", "priority": 0}},
    ...
  ],
  "reasoning": "简短的分解理由（中文）"
}}

priority: 0=实时(Q0), 1=交互(Q1), 2=管理(Q2)"""


def _llm_decide(state: str, available_actions: List[str], action: str = "", params_json: str = "") -> dict:
    """调用 LLM 进行单动作决策（带超时）"""
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

    # 在单独线程中调用 LLM，15 秒超时
    thread = threading.Thread(target=_call_llm, daemon=True)
    thread.start()
    thread.join(timeout=15.0)

    if thread.is_alive():
        logger.warning("LLM 调用超时（5秒），回退到规则引擎")
        return None

    if exception[0]:
        logger.error(f"LLM 决策失败: {exception[0]}")
        return None

    return result[0]


def _llm_decompose(text: str, available_actions: List[str]) -> Optional[List[dict]]:
    """调用 LLM 将自然语言分解为多个原子动作（带超时）"""
    import threading

    client = _get_llm_client()
    if client is None:
        return None

    model = os.getenv("ANTHROPIC_MODEL", "mimo-v2.5-pro")

    result = [None]
    exception = [None]

    def _call_llm():
        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system=_build_decompose_prompt(available_actions),
                messages=[{"role": "user", "content": f"用户指令: {text}"}],
            )

            raw = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw = block.text.strip()
                    break
            if not raw:
                return

            # 提取 JSON
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            parsed = json.loads(raw)
            actions = parsed.get("actions", [])

            # 验证所有动作都在可用列表中
            valid_actions = []
            for a in actions:
                action_name = a.get("action", "")
                if action_name in available_actions:
                    valid_actions.append({
                        "action": action_name,
                        "params_json": a.get("params_json", "{}"),
                        "priority": a.get("priority", 2),
                    })
                else:
                    logger.warning(f"LLM 分解了不可用的动作 '{action_name}'，跳过")

            if valid_actions:
                result[0] = valid_actions
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=_call_llm, daemon=True)
    thread.start()
    thread.join(timeout=20.0)  # 分解任务给更多时间

    if thread.is_alive():
        logger.warning("LLM 分解超时（8秒）")
        return None

    if exception[0]:
        logger.error(f"LLM 分解失败: {exception[0]}")
        return None

    return result[0]


def _transcribe_audio(audio_bytes: bytes) -> Optional[str]:
    """将 PCM 音频转为文本"""
    asr = _get_asr_tool()
    if asr is None:
        logger.warning("ASR 不可用，无法转写音频")
        return None

    try:
        # ASRTool 期望 raw PCM bytes
        asr.add_audio_chunk(audio_bytes)
        text, confidence = asr.transcribe()
        if text:
            logger.info(f"ASR 转写结果: '{text}' (置信度: {confidence:.2f})")
            return text
        else:
            logger.warning("ASR 转写结果为空")
            return None
    except Exception as e:
        logger.error(f"ASR 转写失败: {e}")
        return None


class DecisionEngine:
    def __init__(self):
        # 预初始化 LLM 客户端
        _get_llm_client()
        # 预初始化记忆引擎
        _get_memory_engine()

    def decide(self, request) -> dict:
        """
        核心决策逻辑（单动作，向后兼容）。
        优先使用 LLM，失败时回退到规则引擎。
        集成记忆系统：检索相关记忆作为上下文。
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

        # 步骤 1.5: 检索相关记忆
        memory_context = self._retrieve_memory_context(
            request.state or request.action or ""
        )

        # 步骤 2: 尝试 LLM 决策（带记忆上下文）
        llm_result = _llm_decide(
            state=request.state,
            available_actions=list(request.available_actions),
            action=request.action,
            params_json=request.params_json,
        )

        if llm_result is not None:
            logger.info(f"[TraceID: {trace_id}] LLM 决策完成: {llm_result.get('action')}")
            # 记录到记忆
            self._store_decision_memory(trace_id, request, llm_result, memory_context)
            return llm_result

        # 步骤 3: 回退到规则引擎
        logger.info(f"[TraceID: {trace_id}] LLM 不可用，使用规则引擎")
        if request.action:
            decision = self._handle_action_confirmation(request)
        else:
            decision = self._handle_state_to_action(request)

        logger.info(f"[TraceID: {trace_id}] 规则引擎决策完成: {decision.get('action')}")

        # 记录到记忆
        self._store_decision_memory(trace_id, request, decision, memory_context)

        return decision

    def decide_from_audio(self, audio_bytes: bytes, available_actions: List[str], trace_id: str = "") -> dict:
        """
        音频→ASR→LLM分解→多原子动作（全链路核心方法）。
        集成记忆系统：检索相关记忆增强决策。
        1. ASR 转写音频为文本
        2. 检索相关记忆
        3. LLM 将文本分解为多个原子动作
        4. 返回动作列表（边缘可直接执行，无需再等LLM）
        """
        logger.info(f"[TraceID: {trace_id}] 音频决策引擎启动，音频大小: {len(audio_bytes)} bytes")

        # 步骤 1: ASR 转写
        text = _transcribe_audio(audio_bytes)
        if not text:
            return {
                "status": "error",
                "error_code": "ASR_FAILED",
                "error_message": "语音识别失败或结果为空",
                "asr_text": "",
                "actions": [],
            }

        logger.info(f"[TraceID: {trace_id}] ASR 转写完成: '{text}'")

        # 步骤 1.5: 检索相关记忆
        memory_context = self._retrieve_memory_context(text)

        # 步骤 2: LLM 分解为多原子动作
        actions = _llm_decompose(text, available_actions)

        if actions is not None:
            logger.info(f"[TraceID: {trace_id}] LLM 分解完成: {len(actions)} 个原子动作")
            # 存入记忆
            self._store_audio_memory(trace_id, text, actions, True)
            return {
                "status": "ok",
                "asr_text": text,
                "actions": actions,
            }

        # 步骤 3: LLM 不可用，用规则引擎做简单映射
        logger.info(f"[TraceID: {trace_id}] LLM 不可用，使用规则引擎做简单映射")
        rule_actions = self._rule_decompose(text, available_actions)

        # 存入记忆
        self._store_audio_memory(trace_id, text, rule_actions, False)

        return {
            "status": "ok",
            "asr_text": text,
            "actions": rule_actions,
        }

    def _store_audio_memory(self, trace_id: str, asr_text: str,
                             actions: List[dict], llm_used: bool):
        """将音频决策存入记忆"""
        memory = _get_memory_engine()
        if memory is None:
            return

        try:
            action_names = [a.get("action", "?") for a in actions]
            content = f"语音指令: '{asr_text}' → 动作: {', '.join(action_names)}"
            if llm_used:
                content += " (LLM决策)"
            else:
                content += " (规则引擎)"

            memory.remember(
                content=content,
                memory_type="episodic",
                importance=0.7,
                metadata={
                    "trace_id": trace_id,
                    "asr_text": asr_text,
                    "actions": action_names,
                    "llm_used": llm_used,
                },
            )
        except Exception as e:
            logger.warning(f"[Memory] 存储音频记忆失败: {e}")

    def _rule_decompose(self, text: str, available_actions: List[str]) -> List[dict]:
        """规则引擎：基于关键词的简单动作映射"""
        # 关键词→动作映射（中文+英文）
        keyword_map = {
            # 中文
            "开门": "lock_open", "开锁": "lock_open", "打开门": "lock_open",
            "关门": "lock_close", "锁门": "lock_close", "关上门": "lock_close",
            "前进": "move_forward", "往前走": "move_forward", "向前": "move_forward",
            "后退": "move_back", "往后走": "move_back", "向后": "move_back",
            "左转": "turn_left", "向左转": "turn_left",
            "右转": "turn_right", "向右转": "turn_right",
            "挥手": "wave_hand", "招手": "wave_hand",
            "摇头": "shake_head", "点头": "nod",
            "跳舞": "dance",
            "停止": "emergency_stop", "停": "emergency_stop",
            # 英文
            "open": "lock_open", "unlock": "lock_open",
            "close": "lock_close", "lock": "lock_close",
            "forward": "move_forward", "back": "move_back",
            "left": "turn_left", "right": "turn_right",
            "wave": "wave_hand", "nod": "nod", "shake": "shake_head",
            "dance": "dance", "stop": "emergency_stop",
        }

        # 按关键词长度降序排序（长的优先匹配）
        sorted_keywords = sorted(keyword_map.keys(), key=len, reverse=True)

        actions = []
        remaining = text
        for keyword in sorted_keywords:
            if keyword in remaining:
                action_name = keyword_map[keyword]
                if action_name in available_actions:
                    actions.append({
                        "action": action_name,
                        "params_json": "{}",
                        "priority": 1,  # Q1 交互
                    })
                    remaining = remaining.replace(keyword, "", 1)

        # 如果没匹配到任何动作，返回默认动作
        if not actions and available_actions:
            actions.append({
                "action": available_actions[0],
                "params_json": "{}",
                "priority": 2,
            })

        return actions

    def _retrieve_memory_context(self, query: str) -> str:
        """检索相关记忆作为决策上下文"""
        memory = _get_memory_engine()
        if memory is None or not query:
            return ""

        try:
            results = memory.recall(query, top_k=3)
            if results:
                context_parts = [r.entry.content for r in results]
                logger.info(f"[Memory] 检索到 {len(results)} 条相关记忆")
                return "\n".join(context_parts)
        except Exception as e:
            logger.warning(f"[Memory] 记忆检索失败: {e}")

        return ""

    def _store_decision_memory(self, trace_id: str, request, result: dict,
                                memory_context: str = ""):
        """将决策结果存入记忆"""
        memory = _get_memory_engine()
        if memory is None:
            return

        try:
            action = result.get("action", "unknown")
            success = result.get("status") == "ok"

            # 构建记忆内容
            content = f"决策: action={action}, state={request.state or 'N/A'}"
            if memory_context:
                content += f", 参考记忆: {memory_context[:100]}"

            memory.remember(
                content=content,
                memory_type="episodic",
                importance=0.6 if success else 0.4,
                metadata={
                    "trace_id": trace_id,
                    "action": action,
                    "success": success,
                },
            )

            # 记录执行到反思引擎
            memory.record_execution(
                trace_id=trace_id,
                action=action,
                success=success,
                context=request.state or "",
                result=result.get("status", ""),
            )
        except Exception as e:
            logger.warning(f"[Memory] 存储决策记忆失败: {e}")

    def get_memory_stats(self) -> dict:
        """获取记忆系统统计"""
        memory = _get_memory_engine()
        if memory is None:
            return {"status": "unavailable"}
        return memory.stats()

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
