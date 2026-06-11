"""
决策引擎（Decision Engine）— 前额叶皮层

核心职责：
1. 接收感知输入（文本/状态），输出可执行动作
2. 注入自我认知 + 用户画像 + 情绪状态 + 记忆联想，让 LLM 拥有"生命感"
3. 四层决策：语义缓存 → 元认知评估 → LLM 深思 → 规则引擎
4. 置信度驱动：不确定时主动询问，而非硬答
5. 需求驱动：内部需求影响行为，不只是被动响应

纯 Agent 工程：零本地推理，全部依赖外部 LLM API。
"""

import json
import logging
import os
import threading
import time
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ========== 延迟初始化 ==========

_memory_engine = None
_llm_client = None
_semantic_cache = None
_prompt_engine = None
_learning_loop = None
_meta_cognition = None
_user_model = None
_self_model = None
_need_engine = None
_memory_stream = None
_emotion_engine = None
_living_graph = None
_inner_loop = None
_conversation_state = None
_cog_rec = None
_action_memory = None
_prompt_evolution = None
_safety_governance = None
_init_lock = threading.Lock()


def _get_memory_engine():
    global _memory_engine
    if _memory_engine is not None:
        return _memory_engine if _memory_engine is not False else None
    with _init_lock:
        if _memory_engine is not None:  # double-check
            return _memory_engine if _memory_engine is not False else None
        try:
            from src.core.memory_engine import CognitiveMemoryEngine
            # 创建持久化管理器
            persistence = None
            try:
                from src.core.memory_persistence import PersistentMemoryManager
                data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "memory")
                persistence = PersistentMemoryManager(data_dir)
                logger.info("持久化记忆管理器初始化成功")
            except Exception as e:
                logger.warning("持久化管理器初始化失败（纯内存模式）: %s", e)

            _memory_engine = CognitiveMemoryEngine(persistence=persistence)
            logger.info("认知记忆引擎初始化成功")
        except Exception as e:
            logger.warning("记忆引擎初始化失败: %s", e)
            _memory_engine = False
    return _memory_engine if _memory_engine is not False else None


def save_all_memories():
    """保存所有记忆和缓存到持久化存储（关闭时调用）"""
    # 保存记忆
    engine = _get_memory_engine()
    if engine:
        try:
            engine.save()
            logger.info("[Memory] 全量持久化完成")
        except Exception as e:
            logger.warning("[Memory] 全量持久化失败: %s", e)
    # 保存缓存
    cache = _get_semantic_cache()
    if cache:
        try:
            cache.save()
        except Exception as e:
            logger.warning("[Cache] 缓存持久化失败: %s", e)
    # CogRec, ActionMemory, PromptEvolution 在每次更新时已自动持久化


def _get_llm_client():
    global _llm_client
    if _llm_client is not None:
        return _llm_client if _llm_client is not False else None
    with _init_lock:
        if _llm_client is not None:  # double-check
            return _llm_client if _llm_client is not False else None
        try:
            import anthropic
            _llm_client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
                base_url=os.getenv(
                    "ANTHROPIC_BASE_URL",
                    "https://token-plan-cn.xiaomimimo.com/anthropic",
                ),
                timeout=15.0,
            )
            logger.info("Anthropic LLM 客户端初始化成功")
        except Exception as e:
            logger.warning("Anthropic LLM 初始化失败: %s，回退到规则引擎", e)
            _llm_client = False
    return _llm_client if _llm_client is not False else None


def _get_semantic_cache():
    global _semantic_cache
    if _semantic_cache is not None:
        return _semantic_cache if _semantic_cache is not False else None
    with _init_lock:
        if _semantic_cache is not None:  # double-check
            return _semantic_cache if _semantic_cache is not False else None
        try:
            from src.core.semantic_cache import SemanticCache
            cache_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "semantic_cache.json")
            _semantic_cache = SemanticCache(persist_path=cache_path)
            logger.info("语义缓存初始化成功")
        except Exception as e:
            logger.warning("语义缓存初始化失败: %s", e)
            _semantic_cache = False
    return _semantic_cache if _semantic_cache is not False else None


def _get_prompt_engine():
    global _prompt_engine
    if _prompt_engine is not None:
        return _prompt_engine if _prompt_engine is not False else None
    with _init_lock:
        if _prompt_engine is not None:  # double-check
            return _prompt_engine if _prompt_engine is not False else None
        try:
            from src.core.prompt_engine import PromptEngine
            _prompt_engine = PromptEngine()
            logger.info("提示词引擎初始化成功")
        except Exception as e:
            logger.warning("提示词引擎初始化失败: %s", e)
            _prompt_engine = False
    return _prompt_engine if _prompt_engine is not False else None


def _get_learning_loop():
    global _learning_loop
    if _learning_loop is not None:
        return _learning_loop if _learning_loop is not False else None
    with _init_lock:
        if _learning_loop is not None:  # double-check
            return _learning_loop if _learning_loop is not False else None
        try:
            from src.core.learning_loop import LearningLoop
            _learning_loop = LearningLoop()
            logger.info("学习闭环初始化成功")
        except Exception as e:
            logger.warning("学习闭环初始化失败: %s", e)
            _learning_loop = False
    return _learning_loop if _learning_loop is not False else None


def _get_meta_cognition():
    global _meta_cognition
    if _meta_cognition is not None:
        return _meta_cognition if _meta_cognition is not False else None
    with _init_lock:
        if _meta_cognition is not None:  # double-check
            return _meta_cognition if _meta_cognition is not False else None
        try:
            from src.core.meta_cognition import MetaCognition
            _meta_cognition = MetaCognition()
            logger.info("元认知引擎初始化成功")
        except Exception as e:
            logger.warning("元认知引擎初始化失败: %s", e)
            _meta_cognition = False
    return _meta_cognition if _meta_cognition is not False else None


def _get_user_model():
    global _user_model
    if _user_model is not None:
        return _user_model if _user_model is not False else None
    with _init_lock:
        if _user_model is not None:  # double-check
            return _user_model if _user_model is not False else None
        try:
            from src.core.user_model import UserModel
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            persist_path = os.path.join(data_dir, "user_model.json")
            _user_model = UserModel(persist_path=persist_path)
            logger.info("用户模型初始化成功")
        except Exception as e:
            logger.warning("用户模型初始化失败: %s", e)
            _user_model = False
    return _user_model if _user_model is not False else None


def _get_self_model():
    global _self_model
    if _self_model is not None:
        return _self_model if _self_model is not False else None
    with _init_lock:
        if _self_model is not None:  # double-check
            return _self_model if _self_model is not False else None
        try:
            from src.core.self_model import SelfModel
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            persist_path = os.path.join(data_dir, "self_model.json")
            _self_model = SelfModel.load(persist_path)
            logger.info("自我模型初始化成功")
        except Exception as e:
            logger.warning("自我模型初始化失败: %s", e)
            _self_model = False
    return _self_model if _self_model is not False else None


def _get_need_engine():
    global _need_engine
    if _need_engine is not None:
        return _need_engine if _need_engine is not False else None
    with _init_lock:
        if _need_engine is not None:  # double-check
            return _need_engine if _need_engine is not False else None
        try:
            from src.core.need_engine import NeedEngine
            _need_engine = NeedEngine()
            logger.info("需求引擎初始化成功")
        except Exception as e:
            logger.warning("需求引擎初始化失败: %s", e)
            _need_engine = False
    return _need_engine if _need_engine is not False else None


def _get_memory_stream():
    global _memory_stream
    if _memory_stream is not None:
        return _memory_stream if _memory_stream is not False else None
    with _init_lock:
        if _memory_stream is not None:  # double-check
            return _memory_stream if _memory_stream is not False else None
        try:
            from src.core.memory_stream import MemoryStream
            _memory_stream = MemoryStream()
            # 注入记忆引擎
            mem = _get_memory_engine()
            if mem:
                _memory_stream.set_memory_engine(mem)
            logger.info("联想记忆流初始化成功")
        except Exception as e:
            logger.warning("联想记忆流初始化失败: %s", e)
            _memory_stream = False
    return _memory_stream if _memory_stream is not False else None


def _get_emotion_engine():
    global _emotion_engine
    if _emotion_engine is not None:
        return _emotion_engine if _emotion_engine is not False else None
    with _init_lock:
        if _emotion_engine is not None:  # double-check
            return _emotion_engine if _emotion_engine is not False else None
        try:
            from src.core.emotion_state import EmotionEngine
            _emotion_engine = EmotionEngine()
            logger.info("情绪引擎初始化成功")
        except Exception as e:
            logger.warning("情绪引擎初始化失败: %s", e)
            _emotion_engine = False
    return _emotion_engine if _emotion_engine is not False else None


def _get_living_graph():
    global _living_graph
    if _living_graph is not None:
        return _living_graph if _living_graph is not False else None
    with _init_lock:
        if _living_graph is not None:  # double-check
            return _living_graph if _living_graph is not False else None
        try:
            from src.core.living_graph import LivingGraph
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            persist_path = os.path.join(data_dir, "living_graph.json")
            _living_graph = LivingGraph(persist_path=persist_path)
            logger.info("活体知识图谱初始化成功")
        except Exception as e:
            logger.warning("活体知识图谱初始化失败: %s", e)
            _living_graph = False
    return _living_graph if _living_graph is not False else None


def _get_inner_loop():
    global _inner_loop
    if _inner_loop is not None:
        return _inner_loop if _inner_loop is not False else None
    with _init_lock:
        if _inner_loop is not None:  # double-check
            return _inner_loop if _inner_loop is not False else None
        try:
            from src.core.inner_loop import InnerLoop
            _inner_loop = InnerLoop()
            logger.info("内心循环初始化成功")
        except Exception as e:
            logger.warning("内心循环初始化失败: %s", e)
            _inner_loop = False
    return _inner_loop if _inner_loop is not False else None


def _get_conversation_state():
    global _conversation_state
    if _conversation_state is not None:
        return _conversation_state if _conversation_state is not False else None
    with _init_lock:
        if _conversation_state is not None:  # double-check
            return _conversation_state if _conversation_state is not False else None
        try:
            from src.core.conversation_state import ConversationState
            _conversation_state = ConversationState()
            logger.info("对话状态初始化成功")
        except Exception as e:
            logger.warning("对话状态初始化失败: %s", e)
            _conversation_state = False
    return _conversation_state if _conversation_state is not False else None


def _get_cog_rec():
    global _cog_rec
    if _cog_rec is not None:
        return _cog_rec if _cog_rec is not False else None
    with _init_lock:
        if _cog_rec is not None:
            return _cog_rec if _cog_rec is not False else None
        try:
            from src.core.cog_rec import CogRecEngine
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            _cog_rec = CogRecEngine(persist_path=os.path.join(data_dir, "cogrec_rules.json"))
            logger.info("CogRec 引擎初始化成功")
        except Exception as e:
            logger.warning("CogRec 引擎初始化失败: %s", e)
            _cog_rec = False
    return _cog_rec if _cog_rec is not False else None


def _get_action_memory():
    global _action_memory
    if _action_memory is not None:
        return _action_memory if _action_memory is not False else None
    with _init_lock:
        if _action_memory is not None:
            return _action_memory if _action_memory is not False else None
        try:
            from src.core.action_memory import ActionMemory
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            _action_memory = ActionMemory(persist_path=os.path.join(data_dir, "action_memory.json"))
            logger.info("动作记忆初始化成功")
        except Exception as e:
            logger.warning("动作记忆初始化失败: %s", e)
            _action_memory = False
    return _action_memory if _action_memory is not False else None


def _get_prompt_evolution():
    global _prompt_evolution
    if _prompt_evolution is not None:
        return _prompt_evolution if _prompt_evolution is not False else None
    with _init_lock:
        if _prompt_evolution is not None:
            return _prompt_evolution if _prompt_evolution is not False else None
        try:
            from src.core.prompt_evolution import PromptEvolution
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            _prompt_evolution = PromptEvolution(persist_path=os.path.join(data_dir, "prompt_evolution.json"))
            logger.info("提示词进化引擎初始化成功")
        except Exception as e:
            logger.warning("提示词进化引擎初始化失败: %s", e)
            _prompt_evolution = False
    return _prompt_evolution if _prompt_evolution is not False else None


def _get_safety_governance():
    global _safety_governance
    if _safety_governance is not None:
        return _safety_governance if _safety_governance is not False else None
    with _init_lock:
        if _safety_governance is not None:
            return _safety_governance if _safety_governance is not False else None
        try:
            from src.core.safety_governance import SafetyGovernance
            _safety_governance = SafetyGovernance()
            logger.info("安全治理层初始化成功")
        except Exception as e:
            logger.warning("安全治理层初始化失败: %s", e)
            _safety_governance = False
    return _safety_governance if _safety_governance is not False else None


# ========== LLM 调用（StreamMA 流式优化） ==========

def _try_parse_json(text: str) -> Optional[dict]:
    """
    尝试从文本中解析 JSON。

    StreamMA 核心思想：头部步骤质量高，一旦检测到完整 JSON 立即返回，
    不等待 LLM stream 结束。这将延迟从"完整响应时间"缩短到"JSON 出现时间"。
    """
    if not text or "{" not in text:
        return None
    text = text.strip()
    # 剥离 markdown 代码块
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
    # 快速检查：必须有 { 和 } 才可能是完整 JSON
    if "}" not in text:
        return None
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        return None


def _llm_decide(system_prompt: str, user_message: str,
                max_retries: int = 3) -> Optional[dict]:
    """
    调用 LLM 进行决策（流式提前返回 + 指数退避重试）。

    StreamMA 优化：使用 streaming API，逐 chunk 累积文本，
    一旦检测到完整 JSON 立即返回，不等待 stream 结束。

    重试策略：不降级，排队重试。指数退避 1s/2s/4s。
    """
    client = _get_llm_client()
    if client is None:
        return None

    model = os.getenv("ANTHROPIC_MODEL", "mimo-v2.5-pro")

    for attempt in range(max_retries + 1):
        result = [None]
        exception = [None]
        cancelled = threading.Event()

        def _stream_call():
            try:
                with client.messages.stream(
                    model=model,
                    max_tokens=256,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    extra_body={"thinking": {"type": "disabled"}},
                ) as stream:
                    accumulated = ""
                    for text_chunk in stream.text_stream:
                        if cancelled.is_set():
                            return
                        accumulated += text_chunk
                        parsed = _try_parse_json(accumulated)
                        if parsed is not None:
                            result[0] = parsed
                            return
                    parsed = _try_parse_json(accumulated)
                    if parsed is not None:
                        result[0] = parsed
            except Exception as e:
                if not cancelled.is_set():
                    exception[0] = e

        thread = threading.Thread(target=_stream_call, daemon=True)
        thread.start()
        thread.join(timeout=15.0)

        if thread.is_alive():
            cancelled.set()
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("LLM 流式调用超时（尝试 %d/%d），%ds 后重试",
                               attempt + 1, max_retries + 1, wait)
                time.sleep(wait)
                continue
            else:
                logger.error("LLM 流式调用超时（%d 次尝试全部失败）", max_retries + 1)
                return None

        if exception[0]:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("LLM 决策失败（尝试 %d/%d）: %s，%ds 后重试",
                               attempt + 1, max_retries + 1, exception[0], wait)
                time.sleep(wait)
                continue
            else:
                logger.error("LLM 决策失败（%d 次尝试全部失败）: %s", max_retries + 1, exception[0])
                return None

        # 成功
        if attempt > 0:
            logger.info("LLM 决策成功（第 %d 次尝试）", attempt + 1)
        return result[0]

    return None


def _llm_decompose(system_prompt: str, user_message: str,
                   max_retries: int = 3) -> Optional[List[dict]]:
    """
    调用 LLM 进行多动作分解（流式提前返回 + 指数退避重试）。

    StreamMA 优化：与 _llm_decide 相同的流式策略。
    重试策略：不降级，排队重试。指数退避 1s/2s/4s。
    """
    client = _get_llm_client()
    if client is None:
        return None

    model = os.getenv("ANTHROPIC_MODEL", "mimo-v2.5-pro")

    for attempt in range(max_retries + 1):
        result = [None]
        exception = [None]
        cancelled = threading.Event()

        def _stream_call():
            try:
                with client.messages.stream(
                    model=model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    extra_body={"thinking": {"type": "disabled"}},
                ) as stream:
                    accumulated = ""
                    for text_chunk in stream.text_stream:
                        if cancelled.is_set():
                            return
                        accumulated += text_chunk
                        parsed = _try_parse_json(accumulated)
                        if parsed is not None:
                            actions = parsed.get("actions", [])
                            if actions:
                                result[0] = actions
                                return
                    parsed = _try_parse_json(accumulated)
                    if parsed is not None:
                        result[0] = parsed.get("actions", [])
            except Exception as e:
                if not cancelled.is_set():
                    exception[0] = e

        thread = threading.Thread(target=_stream_call, daemon=True)
        thread.start()
        thread.join(timeout=20.0)

        if thread.is_alive():
            cancelled.set()
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("LLM 分解超时（尝试 %d/%d），%ds 后重试",
                               attempt + 1, max_retries + 1, wait)
                time.sleep(wait)
                continue
            else:
                logger.error("LLM 分解超时（%d 次尝试全部失败）", max_retries + 1)
                return None

        if exception[0]:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("LLM 分解失败（尝试 %d/%d）: %s，%ds 后重试",
                               attempt + 1, max_retries + 1, exception[0], wait)
                time.sleep(wait)
                continue
            else:
                logger.error("LLM 分解失败（%d 次尝试全部失败）: %s", max_retries + 1, exception[0])
                return None

        if attempt > 0:
            logger.info("LLM 分解成功（第 %d 次尝试）", attempt + 1)
        return result[0]

    return None


# ========== 决策引擎 ==========

class DecisionEngine:
    """
    决策引擎 — 大脑前额叶皮层。

    四层决策（元认知增强）：
    1. 语义缓存（<1ms）：高频查询直接返回
    2. 元认知评估：置信度打分 + 策略选择
    3. LLM 深思（~1s）：注入记忆 + 用户画像 + 学习洞察
    4. 规则引擎兜底

    关键改进：不确定时主动询问，而非硬答。
    """

    def __init__(self):
        _get_llm_client()
        _get_memory_engine()
        _get_semantic_cache()
        _get_prompt_engine()
        _get_learning_loop()
        _get_meta_cognition()
        _get_user_model()
        _get_self_model()
        _get_need_engine()
        _get_memory_stream()
        _get_emotion_engine()
        _get_living_graph()

        # 启动联想记忆流
        stream = _get_memory_stream()
        if stream:
            stream.start()

    def decide(self, request, force_llm: bool = False) -> dict:
        """
        核心决策逻辑 — 元认知增强版。

        流程：
        1. 语义缓存 → 命中则直接返回
        2. 元认知评估置信度 → 不确定则主动询问
        3. 用户纠正历史检查 → 避免重复犯错
        4. LLM 深思（注入记忆+画像+洞察）→ 返回
        5. 规则引擎兜底
        """
        trace_id = request.trace_id
        start_time = time.time()
        logger.info("[TraceID: %s] 决策引擎启动...", trace_id)

        # 输入校验
        validation = self._validate_request(request)
        if not validation["is_valid"]:
            return {
                "status": "error",
                "error_code": "INVALID_REQUEST",
                "error_message": validation["message"],
            }

        available_actions = list(request.available_actions)
        query = request.state or request.action or ""

        # ── 步骤 0: 复合指令检测 ──
        # "A 和 B"、"先 A 再 B"、"A，然后 B" → 走多动作分解路径
        if query and self._is_compound_command(query):
            logger.info("[TraceID: %s] 检测到复合指令，走多动作分解", trace_id)
            return self.decide_from_text(
                text=query,
                available_actions=available_actions,
                trace_id=trace_id,
                device_state=request.state or "",
            )

        # ── 步骤 0.5: 记录对话状态 ──
        conv = _get_conversation_state()
        if conv and query:
            conv.add_user_message(query)

        # ── 步骤 1: 语义缓存（<1ms）──────────────────────
        cache = _get_semantic_cache()
        cache_hit = False
        cache_similarity = 0.0

        # force_llm 模式：跳过所有缓存，直接走 LLM
        if force_llm:
            logger.info("[TraceID: %s] force_llm 模式，跳过缓存", trace_id)
        elif cache and query:
            cached = cache.lookup(query, available_actions)
            if cached:
                cache_hit = True
                cache_similarity = cached.get("_similarity", 0.0)
                logger.info("[TraceID: %s] 语义缓存命中: %s", trace_id, cached['action'])

                # 元认知评估：缓存命中但也要检查置信度
                meta = _get_meta_cognition()
                if meta:
                    assessment = meta.evaluate_confidence(
                        query=query,
                        cache_hit=True,
                        cache_similarity=cache_similarity,
                    )
                    if assessment.should_confirm:
                        # 缓存命中但置信度低（可能是语义匹配但不精确）
                        logger.info("[TraceID: %s] 缓存命中但置信度低 (%s)，继续深思", trace_id, assessment.score)
                    else:
                        # 高置信度缓存命中
                        result = {"status": "ok", **cached}
                        self._record_to_user_model(query, cached.get("action", ""), trace_id)
                        self._record_feedback(trace_id, query, result, True)
                        latency = int((time.time() - start_time) * 1000)
                        self._record_meta_decision(query, "cache", assessment.score, latency)
                        return result
                else:
                    # 无元认知，直接返回缓存
                    result = {"status": "ok", **cached}
                    self._record_to_user_model(query, cached.get("action", ""), trace_id)
                    self._record_feedback(trace_id, query, result, True)
                    return result

        # ── 步骤 1.5: CogRec 规则匹配 + ActionMemory 重放 ──
        # CogRec: LLM 教的规则，<1ms 命中
        cog_rec = _get_cog_rec()
        if not force_llm and cog_rec and query:
            rule_result = cog_rec.match(query, available_actions)
            if rule_result:
                result = {"status": "ok", **rule_result}
                self._record_to_user_model(query, rule_result["action"], trace_id)
                self._record_feedback(trace_id, query, result, True)
                latency = int((time.time() - start_time) * 1000)
                logger.info("[TraceID: %s] CogRec 规则命中: %s (%sms)",
                            trace_id, rule_result["action"], latency)
                return result

        # ActionMemory: 完整轨迹重放，<1ms 命中
        action_mem = _get_action_memory()
        if not force_llm and action_mem and query:
            replay_result = action_mem.replay(query, available_actions)
            if replay_result:
                result = {"status": "ok", **replay_result}
                self._record_to_user_model(query, replay_result["action"], trace_id)
                self._record_feedback(trace_id, query, result, True)
                latency = int((time.time() - start_time) * 1000)
                logger.info("[TraceID: %s] ActionMemory 重放: %s (%sms)",
                            trace_id, replay_result["action"], latency)
                return result

        # ── 步骤 2: 用户纠正历史检查 ─────────────────────
        user_model = _get_user_model()
        correction_hint = ""
        has_correction_history = False
        if user_model and query:
            correction_hint = user_model.get_correction_context(query) or ""
            has_correction_history = bool(correction_hint)
            if correction_hint:
                logger.info("[TraceID: %s] 发现纠正历史: %s", trace_id, correction_hint)

        # ── 步骤 3: 意图推断（用户画像）──────────────────
        user_profile_summary = ""
        if user_model:
            user_profile_summary = user_model.get_profile_summary()

        # ── 步骤 3.5: 自我认知 + 情绪 + 需求 ────────────
        self_model = _get_self_model()
        emotion = _get_emotion_engine()
        need_engine = _get_need_engine()

        self_context = ""
        if self_model:
            self_model.update_task(query[:50])
            self_context += f"\n\n## 自我认知\n{self_model.who_am_i()}"

        if emotion:
            emotion.on_new_interaction()
            emotion_state = emotion.state.to_dict()
            emotion_desc = emotion.state.describe()
            if emotion_desc:
                self_context += f"\n\n## 当前情绪\n{emotion_desc}（stress={emotion_state['stress']:.2f}, confidence={emotion_state['confidence']:.2f}）"

        if need_engine:
            needs = need_engine.update()
            need_desc = needs.describe()
            if need_desc:
                self_context += f"\n\n## 内部需求\n{need_desc}"

        # 联想记忆流的洞察
        stream = _get_memory_stream()
        if stream:
            insight = stream.get_unused_insight()
            if insight:
                self_context += f"\n\n## 联想洞察\n{insight.content}"

        # 内心独白（Agent 的持续思考）
        inner = _get_inner_loop()
        if inner:
            narrative = inner.get_narrative()
            if narrative and "刚醒来" not in narrative:
                self_context += f"\n\n{narrative}"

        # 对话状态 + 发散思考上下文（无缝衔接的关键）
        conv = _get_conversation_state()
        if conv:
            conv_context = conv.get_context_for_response()
            if conv_context:
                self_context += f"\n\n{conv_context}"

        # ── 步骤 4: 记忆检索 ─────────────────────────────
        memory_context = self._build_memory_context(query)

        # PromptEvolution: 注入进化后的指南
        prompt_evo = _get_prompt_evolution()
        if prompt_evo and query:
            guidelines = prompt_evo.get_relevant(query, max_items=3)
            if guidelines:
                guidelines_text = "\n".join(f"- {g}" for g in guidelines)
                memory_context += f"\n\n## 学习到的指南\n{guidelines_text}"

        # ── 步骤 5: 构建提示词（记忆 + 用户画像 + 自我 + 情绪 + 纠正）──
        prompt_engine = _get_prompt_engine()
        if prompt_engine:
            extra_context = ""
            if user_profile_summary:
                extra_context += f"\n\n## 用户画像\n{user_profile_summary}"
            if correction_hint:
                extra_context += f"\n\n## ⚠️ 纠正提醒\n{correction_hint}"
            if self_context:
                extra_context += self_context

            system_prompt = prompt_engine.build_system_prompt(
                available_actions=available_actions,
                memory_context=memory_context + extra_context,
                device_state=request.state or "",
            )
        else:
            system_prompt = self._build_fallback_prompt(available_actions)
            if correction_hint:
                system_prompt += f"\n\n{correction_hint}"
            if self_context:
                system_prompt += self_context

        # ── 步骤 6: 构建用户消息 ─────────────────────────
        if request.action:
            user_msg = f"执行动作: {request.action}, 参数: {request.params_json or '{}'}"
        else:
            user_msg = f"状态: {request.state or '未知'}"

        # ── 步骤 7: LLM 深思（~1s）───────────────────────
        llm_result = _llm_decide(system_prompt, user_msg)

        # ── 步骤 8: 元认知置信度评估 ─────────────────────
        meta = _get_meta_cognition()
        if meta:
            assessment = meta.evaluate_confidence(
                query=query,
                cache_hit=cache_hit,
                cache_similarity=cache_similarity,
                memory_match_count=memory_context.count("\n") if memory_context else 0,
                llm_response=llm_result,
                rule_match=False,
                user_expertise=user_model.profile.expertise_level if user_model else 0.5,
                has_correction_history=has_correction_history,
            )

            strategy_decision = meta.select_strategy(
                query=query,
                confidence=assessment,
                cache_hit=cache_hit,
                available_actions=available_actions,
                user_expertise=user_model.profile.expertise_level if user_model else 0.5,
            )

            logger.info("[TraceID: %s] 元认知: 置信度=%.2f (%s), 策略=%s",
                        trace_id, assessment.score, assessment.level, strategy_decision.strategy)

            # 确认逻辑：仅在 LLM 未返回有效结果 + 策略明确要求时才确认
            llm_has_valid_result = llm_result is not None and llm_result.get("action")
            if (assessment.should_confirm
                    and strategy_decision.strategy == "ask_user"
                    and not llm_has_valid_result):
                latency = int((time.time() - start_time) * 1000)
                self._record_meta_decision(query, "ask_user", assessment.score, latency)
                return {
                    "status": "confirm",
                    "message": assessment.confirmation_prompt,
                    "confidence": assessment.score,
                    "reasoning": assessment.reasoning,
                    "suggested_action": "",
                }

        # ── 步骤 9: 处理 LLM 结果 ───────────────────────
        if llm_result is not None:
            chosen = llm_result.get("action", "")
            if chosen not in available_actions:
                logger.warning("LLM 选择了不可用动作 '%s'，回退到第一个", chosen)
                chosen = available_actions[0] if available_actions else ""

            result = {
                "status": "ok",
                "action": chosen,
                "params_json": llm_result.get("params_json", "{}"),
            }

            # LLM 的自然语言回复（问答、聊天等）
            answer = llm_result.get("answer", "")
            if answer:
                result["answer"] = answer
            elif chosen == "idle" and query:
                # idle 不能沉默——必须回复用户
                result["answer"] = self._generate_idle_response(query, memory_context)

            # 注入置信度提示
            if meta:
                hint = meta.format_confidence_hint(assessment)
                if hint:
                    result["confidence_hint"] = hint

            # 安全治理检查
            safety = _get_safety_governance()
            if safety:
                allowed, reason = safety.check(chosen, query)
                if not allowed:
                    logger.warning("[TraceID: %s] 安全治理阻止: %s → %s", trace_id, chosen, reason)
                    result["status"] = "blocked"
                    result["error_code"] = "SAFETY_VIOLATION"
                    result["error_message"] = reason
                    return result
                safety.record_action(chosen)

            # 存入语义缓存
            if cache and query:
                cache.store(query, result, available_actions)

            # 记录到记忆 + 学习闭环 + 用户模型
            self._store_decision_memory(trace_id, request, result, memory_context)
            self._record_feedback(trace_id, query, result, True)
            self._record_to_user_model(query, chosen, trace_id)

            # 记录到新模块
            self._record_to_new_modules(query, chosen, True)

            # CogRec: 从 LLM 成功中学习规则
            if cog_rec and query and chosen:
                cog_rec.learn_from_success(query, chosen, llm_result.get("params_json", "{}"),
                                          answer=llm_result.get("answer", ""))

            # ActionMemory: 记录成功轨迹
            if action_mem and query and chosen:
                action_mem.record(
                    query=query, action=chosen,
                    params_json=llm_result.get("params_json", "{}"),
                    context={"device_id": request.state},
                    result=result,
                )

            # PromptEvolution: 成功反馈
            if prompt_evo and query:
                prompt_evo.on_success(query)

            # 记录助手回复到对话状态
            self._record_assistant_response(conv, chosen)

            latency = int((time.time() - start_time) * 1000)
            if meta:
                self._record_meta_decision(query, "llm", assessment.score, latency)

            logger.info("[TraceID: %s] LLM 决策完成: %s (%sms)", trace_id, chosen, latency)
            return result

        # ── 步骤 10: 规则引擎兜底 ────────────────────────
        logger.info("[TraceID: %s] LLM 不可用，使用规则引擎", trace_id)
        if request.action:
            decision = self._handle_action_confirmation(request)
        else:
            decision = self._handle_state_to_action(request)

        self._store_decision_memory(trace_id, request, decision, memory_context)
        self._record_to_user_model(query, decision.get("action", ""), trace_id)
        self._record_to_new_modules(query, decision.get("action", ""), decision.get("status") == "ok")
        self._record_assistant_response(conv, decision.get("action", ""))

        latency = int((time.time() - start_time) * 1000)
        if meta:
            self._record_meta_decision(query, "rule", 0.5, latency)

        logger.info("[TraceID: %s] 规则引擎决策完成: %s (%sms)", trace_id, decision.get('action'), latency)
        return decision

    def decide_from_text(self, text: str, available_actions: List[str],
                         trace_id: str = "", device_state: str = "") -> dict:
        """
        文本 → 多原子动作分解（元认知增强版）。
        """
        logger.info("[TraceID: %s] 文本决策引擎启动: '%s'", trace_id, text)

        # 语义缓存
        cache = _get_semantic_cache()
        if cache:
            cached = cache.lookup(text, available_actions)
            if cached:
                logger.info("[TraceID: %s] 语义缓存命中", trace_id)
                self._record_to_user_model(text, cached.get("action", ""), trace_id)
                return {"status": "ok", **cached}

        # 用户纠正历史
        user_model = _get_user_model()
        correction_hint = ""
        if user_model:
            correction_hint = user_model.get_correction_context(text) or ""

        # 记忆 + 用户画像
        memory_context = self._build_memory_context(text)
        if user_model:
            profile = user_model.get_profile_summary()
            if profile:
                memory_context += f"\n\n## 用户画像\n{profile}"
        if correction_hint:
            memory_context += f"\n\n## ⚠️ 纠正提醒\n{correction_hint}"

        # 构建提示词
        prompt_engine = _get_prompt_engine()
        if prompt_engine:
            system_prompt = prompt_engine.build_decompose_prompt(
                available_actions=available_actions,
                memory_context=memory_context,
                device_state=device_state,
            )
        else:
            system_prompt = self._build_fallback_decompose_prompt(available_actions)
            if correction_hint:
                system_prompt += f"\n\n{correction_hint}"

        # LLM 分解
        actions = _llm_decompose(system_prompt, f"用户指令: {text}")

        if actions is not None:
            valid = [a for a in actions if a.get("action") in available_actions]
            if valid:
                logger.info("[TraceID: %s] LLM 分解完成: %s 个动作", trace_id, len(valid))
                self._store_text_decision_memory(trace_id, text, valid, True, memory_context)
                self._record_to_user_model(text, valid[0].get("action", ""), trace_id)
                return {"status": "ok", "asr_text": text, "actions": valid}

        # 规则兜底
        logger.info("[TraceID: %s] LLM 不可用，规则引擎兜底", trace_id)
        rule_actions = self._rule_decompose(text, available_actions)
        self._store_text_decision_memory(trace_id, text, rule_actions, False, memory_context)
        if rule_actions:
            self._record_to_user_model(text, rule_actions[0].get("action", ""), trace_id)

        return {"status": "ok", "asr_text": text, "actions": rule_actions}

    # ========== 用户模型交互 ==========

    def _record_to_user_model(self, query: str, action: str, trace_id: str = ""):
        """记录交互到用户模型"""
        user_model = _get_user_model()
        if user_model and query:
            try:
                user_model.record_interaction(query=query, action=action)
            except Exception as e:
                logger.warning("[UserModel] 记录失败: %s", e)

    def _record_assistant_response(self, conv, action: str):
        """记录助手回复到对话状态"""
        if conv and action:
            try:
                conv.add_assistant_message(f"执行: {action}")
            except Exception as e:
                logger.warning("[ConversationState] 记录失败: %s", e)

    def record_user_correction(self, original_query: str, wrong_action: str,
                               correct_action: str):
        """外部接口：记录用户纠正"""
        user_model = _get_user_model()
        if user_model:
            user_model.record_correction(original_query, wrong_action, correct_action)
            logger.info("用户纠正已记录: '%s' → %s", original_query, correct_action)

        # 通知学习闭环（Reflexion 即时反思）
        loop = _get_learning_loop()
        if loop:
            loop.on_correction(original_query, wrong_action, correct_action)

        # CogRec: 从纠正中学习（最高优先级规则）
        cog_rec = _get_cog_rec()
        if cog_rec:
            cog_rec.learn_from_correction(original_query, wrong_action, correct_action)

        # PromptEvolution: 添加战术指南（短期纠错）
        prompt_evo = _get_prompt_evolution()
        if prompt_evo:
            prompt_evo.add_tactical(
                f"用户纠正: '{original_query}' 应该执行 {correct_action}，不是 {wrong_action}",
                confidence=0.95,
                source="correction",
                ttl_hits=15,
            )

        # 更新信任度
        self_model = _get_self_model()
        if self_model:
            self_model.update_relationship("default_user", trust_delta=-0.05)

        # 内心循环（事件驱动 — 会自动更新情绪和需求）
        inner = _get_inner_loop()
        if inner:
            inner.on_event("correction", {
                "original_query": original_query,
                "wrong_action": wrong_action,
                "correct_action": correct_action,
            })

    def record_user_feedback(self, query: str, feedback: str):
        """外部接口：记录用户反馈"""
        user_model = _get_user_model()
        if user_model:
            user_model.record_interaction(query=query, action="", feedback=feedback)

        # 内心循环（事件驱动）
        inner = _get_inner_loop()
        if inner:
            inner.on_event("feedback", {"query": query, "feedback": feedback})

    def _record_to_new_modules(self, query: str, action: str, success: bool):
        """记录决策结果到新模块（事件驱动）"""

        # 活体知识图谱（自动建图）
        graph = _get_living_graph()
        if graph:
            try:
                graph.auto_build_from_interaction(query, action, success)
                if graph._stats["total_auto_builds"] % 20 == 0:
                    graph.save()
            except Exception as e:
                logger.warning("[LivingGraph] 自动建图失败: %s", e)

        # 联想记忆流
        stream = _get_memory_stream()
        if stream:
            stream.inject_memory(f"{query} → {action} ({'成功' if success else '失败'})")

        # 自我模型
        self_model = _get_self_model()
        if self_model:
            self_model.update_focus(query[:30])

        # 内心循环（事件驱动 — 会自动更新情绪和需求）
        inner = _get_inner_loop()
        if inner:
            inner.on_event("decision", {
                "query": query,
                "action": action,
                "success": success,
            })

    # ========== 元认知交互 ==========

    def _record_meta_decision(self, query: str, strategy: str,
                              confidence: float, latency_ms: int):
        """记录决策到元认知"""
        meta = _get_meta_cognition()
        if meta:
            try:
                meta.record_decision(query, strategy, confidence, latency_ms)
            except Exception as e:
                logger.warning("[MetaCognition] 记录失败: %s", e)

    def get_confidence_assessment(self, query: str, available_actions: list) -> dict:
        """外部接口：获取置信度评估（不执行决策）"""
        meta = _get_meta_cognition()
        if not meta:
            return {"status": "unavailable"}

        cache = _get_semantic_cache()
        cache_hit = False
        cache_sim = 0.0
        if cache:
            cached = cache.lookup(query, available_actions)
            if cached:
                cache_hit = True
                cache_sim = cached.get("_similarity", 0.98)

        assessment = meta.evaluate_confidence(
            query=query,
            cache_hit=cache_hit,
            cache_similarity=cache_sim,
        )
        return {
            "status": "ok",
            "level": assessment.level,
            "score": assessment.score,
            "reasoning": assessment.reasoning,
            "should_confirm": assessment.should_confirm,
        }

    # ========== 记忆上下文构建 ==========

    def _build_memory_context(self, query: str) -> str:
        """
        构建记忆上下文 — 双通道：扩散激活 + 传统检索。

        优先使用 LivingGraph 扩散激活（联想式记忆），
        同时保留传统 TopK 检索作为补充（精确记忆）。
        """
        if not query:
            return ""

        parts = []

        # ── 通道 1: 活体图谱扩散激活 ──
        graph = _get_living_graph()
        if graph:
            activations = graph.diffuse_from_text(query, energy=1.0, max_depth=3)
            if activations:
                graph_context = graph.to_memory_context(activations, max_items=8)
                parts.append(graph_context)
                logger.info("[LivingGraph] 扩散激活 %d 个节点", len(activations))

        # ── 通道 2: 传统记忆检索（补充精确匹配）──
        memory = _get_memory_engine()
        if memory:
            # 语义记忆（事实、偏好、个人信息）
            semantic = memory.recall(query, top_k=5, memory_types=["semantic"])
            if semantic:
                parts.append("## 已知事实和用户偏好")
                for r in semantic:
                    parts.append(f"- {r.entry.content}")

            # 程序性记忆（纠正、操作经验）
            procedural = memory.recall(query, top_k=3, memory_types=["procedural"])
            if procedural:
                parts.append("## 相关经验（含纠正记录）")
                for r in procedural:
                    parts.append(f"- {r.entry.content}")

            # 情景记忆（最近发生的事件）
            episodic = memory.recall(query, top_k=3, memory_types=["episodic"])
            if episodic:
                parts.append("## 近期事件")
                for r in episodic:
                    parts.append(f"- {r.entry.content}")

            context = memory.get_context(max_tokens=300)
            if context:
                parts.append(f"## 当前对话\n{context}")

        result = "\n".join(parts)
        if result:
            logger.info("[Memory] 注入记忆上下文到 prompt")
        return result

    # ========== 学习闭环 ==========

    def _record_feedback(self, trace_id: str, query: str, result: dict, success: bool):
        loop = _get_learning_loop()
        if loop:
            try:
                loop.on_decision(trace_id, query, result, success)
            except Exception as e:
                logger.warning("[Learning] 反馈记录失败: %s", e)

    # ========== 记忆存储 ==========

    def _store_decision_memory(self, trace_id: str, request, result: dict,
                                memory_context: str = ""):
        memory = _get_memory_engine()
        if memory is None:
            return

        try:
            action = result.get("action", "unknown")
            success = result.get("status") == "ok"

            content = f"决策: action={action}, state={request.state or 'N/A'}"
            if memory_context:
                content += f", 参考记忆: {memory_context[:100]}"

            memory.remember(
                content=content,
                memory_type="episodic",
                importance=0.6 if success else 0.4,
                metadata={"trace_id": trace_id, "action": action, "success": success},
            )

            memory.record_execution(
                trace_id=trace_id, action=action, success=success,
                context=request.state or "", result=result.get("status", ""),
            )
        except Exception as e:
            logger.warning("[Memory] 存储决策记忆失败: %s", e)

    def _store_text_decision_memory(self, trace_id: str, text: str,
                                     actions: List[dict], llm_used: bool,
                                     memory_context: str = ""):
        memory = _get_memory_engine()
        if memory is None:
            return

        try:
            action_names = [a.get("action", "?") for a in actions]
            content = f"语音指令: '{text}' → 动作: {', '.join(action_names)}"
            content += " (LLM)" if llm_used else " (规则)"

            memory.remember(
                content=content,
                memory_type="episodic",
                importance=0.7,
                metadata={"trace_id": trace_id, "asr_text": text,
                          "actions": action_names, "llm_used": llm_used},
            )
        except Exception as e:
            logger.warning("[Memory] 存储文本记忆失败: %s", e)

    # ========== 规则引擎兜底 ==========

    def _generate_idle_response(self, query: str, memory_context: str = "") -> str:
        """
        生成 idle 时的默认回复。

        不能沉默——用户说了话，Agent 必须回应。
        用 LLM 生成自然的回复，失败时用模板。
        """
        llm = _get_llm_client()
        if llm:
            try:
                prompt = f"""用户说: "{query}"

{f"已知信息:{chr(10)}{memory_context[:500]}" if memory_context else ""}

用户在和你聊天或问问题，但你没有对应的设备动作可以执行。
请用自然的中文回复用户（简短，1-2句话）。
不要说"我无法执行"，而是像朋友一样回应。"""

                response = llm.messages.create(
                    model="mimo-v2.5-pro",
                    max_tokens=128,
                    system="你是 Rak，一个温暖的智能家居助手。用自然的中文简短回复。",
                    messages=[{"role": "user", "content": prompt}],
                    extra_body={"thinking": {"type": "disabled"}},
                )
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text.strip()
            except Exception as e:
                logger.warning("[Decision] idle 回复生成失败: %s", e)

        # 模板降级
        return "收到！有什么需要帮忙的随时说～"

    def _is_compound_command(self, text: str) -> bool:
        """
        检测是否为复合指令。

        复合模式：
        - "A 和 B"、"A 与 B"
        - "先 A 再 B"、"先 A 然后 B"
        - "A，然后 B"、"A，再 B"
        - "A，B"（逗号分隔的多个动作）
        """
        compound_markers = [
            " 和 ", " 与 ", "及",
            "先", "然后", "再", "接着",
            "同时", "顺便", "还有",
        ]

        # 检查是否有复合标记
        for marker in compound_markers:
            if marker in text:
                # 确认标记两侧都有实质性内容（不是"先走了"这种）
                parts = text.split(marker)
                if len(parts) >= 2 and len(parts[0].strip()) > 1 and len(parts[1].strip()) > 1:
                    return True

        # 逗号分隔的多个动作指令
        if "，" in text:
            parts = text.split("，")
            if len(parts) >= 2:
                # 检查每个部分是否包含动作关键词
                action_words = ["开", "关", "锁", "打开", "关闭", "调", "设"]
                action_count = sum(
                    1 for p in parts
                    if any(w in p for w in action_words)
                )
                if action_count >= 2:
                    return True

        return False

    def _rule_decompose(self, text: str, available_actions: List[str]) -> List[dict]:
        keyword_map = {
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
            "open": "lock_open", "unlock": "lock_open",
            "close": "lock_close", "lock": "lock_close",
            "forward": "move_forward", "back": "move_back",
            "left": "turn_left", "right": "turn_right",
            "wave": "wave_hand", "nod": "nod", "shake": "shake_head",
            "dance": "dance", "stop": "emergency_stop",
        }

        sorted_kw = sorted(keyword_map.keys(), key=len, reverse=True)
        actions = []
        remaining = text

        for kw in sorted_kw:
            if kw in remaining:
                action_name = keyword_map[kw]
                if action_name in available_actions:
                    actions.append({
                        "action": action_name,
                        "params_json": "{}",
                        "priority": 1,
                    })
                    remaining = remaining.replace(kw, "", 1)

        if not actions and available_actions:
            actions.append({
                "action": available_actions[0],
                "params_json": "{}",
                "priority": 2,
            })

        return actions

    def _validate_request(self, request) -> dict:
        if not request.available_actions:
            return {"is_valid": False, "message": "available_actions 不能为空"}

        if request.action and request.action not in request.available_actions:
            return {
                "is_valid": False,
                "message": f"动作 '{request.action}' 不在允许列表中",
            }

        if request.params_json:
            try:
                json.loads(request.params_json)
            except json.JSONDecodeError:
                return {"is_valid": False, "message": "params_json 不是有效的 JSON"}

        return {"is_valid": True}

    def _handle_action_confirmation(self, request) -> dict:
        return {
            "status": "ok",
            "action": request.action,
            "params_json": request.params_json,
        }

    def _handle_state_to_action(self, request) -> dict:
        if not request.available_actions:
            return {
                "status": "error",
                "error_code": "NO_AVAILABLE_ACTIONS",
                "error_message": "无可用动作",
            }

        chosen = request.available_actions[0]
        default_params = {}
        if chosen == "move_forward":
            default_params = {"distance_cm": 5, "speed": 50}
        elif chosen == "turn_left":
            default_params = {"angle_deg": 90, "speed": 30}

        return {
            "status": "ok",
            "action": chosen,
            "params_json": json.dumps(default_params, ensure_ascii=False),
        }

    def _build_fallback_prompt(self, available_actions: List[str]) -> str:
        actions_desc = "\n".join(f"- {a}" for a in available_actions)
        return f"""你是一个嵌入式设备决策引擎。从可用动作中选择最合适的。

## 可用动作
{actions_desc}

## 输出格式
返回 JSON: {{"action": "动作名", "params_json": "{{}}", "reasoning": "理由"}}"""

    def _build_fallback_decompose_prompt(self, available_actions: List[str]) -> str:
        actions_desc = "\n".join(f"- {a}" for a in available_actions)
        return f"""将用户指令分解为原子动作序列。

## 可用原子动作
{actions_desc}

## 输出格式
返回 JSON: {{"actions": [{{"action": "动作名", "params_json": "{{}}", "priority": 0}}]}}"""

    # ========== 统计接口 ==========

    def get_memory_stats(self) -> dict:
        memory = _get_memory_engine()
        if memory is None:
            return {"status": "unavailable"}
        return memory.stats()

    def get_user_model_stats(self) -> dict:
        user_model = _get_user_model()
        if user_model is None:
            return {"status": "unavailable"}
        return user_model.get_stats()

    def get_meta_cognition_stats(self) -> dict:
        meta = _get_meta_cognition()
        if meta is None:
            return {"status": "unavailable"}
        return meta.get_stats()

    def reflect(self) -> dict:
        """触发元认知自我反思"""
        meta = _get_meta_cognition()
        if meta is None:
            return {"status": "unavailable"}
        return meta.reflect()

    def get_self_model_stats(self) -> dict:
        self_model = _get_self_model()
        if self_model is None:
            return {"status": "unavailable"}
        return self_model.get_stats()

    def get_need_engine_stats(self) -> dict:
        need = _get_need_engine()
        if need is None:
            return {"status": "unavailable"}
        return need.get_stats()

    def get_memory_stream_stats(self) -> dict:
        stream = _get_memory_stream()
        if stream is None:
            return {"status": "unavailable"}
        return stream.get_stats()

    def get_emotion_stats(self) -> dict:
        emotion = _get_emotion_engine()
        if emotion is None:
            return {"status": "unavailable"}
        return emotion.get_stats()

    def get_who_am_i(self) -> str:
        """自我介绍"""
        self_model = _get_self_model()
        if self_model is None:
            return "自我模型未初始化"
        return self_model.who_am_i()

    def get_need_suggestion(self) -> Optional[dict]:
        """获取需求引擎的行为建议"""
        need = _get_need_engine()
        if need is None:
            return None
        need.update()
        return need.suggest_action()

    def get_living_graph_stats(self) -> dict:
        graph = _get_living_graph()
        if graph is None:
            return {"status": "unavailable"}
        return graph.get_stats()

    def diffuse_memory(self, query: str) -> list[dict]:
        """外部接口：从查询扩散激活记忆"""
        graph = _get_living_graph()
        if graph is None:
            return []
        results = graph.diffuse_from_text(query)
        return [
            {"label": r.label, "energy": r.energy, "depth": r.depth, "path": r.path}
            for r in results[:10]
        ]

    def save_living_graph(self):
        """外部接口：保存活体图谱"""
        graph = _get_living_graph()
        if graph:
            graph.save()

    def get_inner_loop_stats(self) -> dict:
        inner = _get_inner_loop()
        if inner is None:
            return {"status": "unavailable"}
        return inner.get_stats()

    def get_narrative(self) -> str:
        """获取内心独白"""
        inner = _get_inner_loop()
        if inner is None:
            return ""
        return inner.get_narrative()

    def get_conversation_stats(self) -> dict:
        conv = _get_conversation_state()
        if conv is None:
            return {"status": "unavailable"}
        return conv.get_stats()

    def get_wandering_context(self) -> str:
        """获取发散思考上下文"""
        conv = _get_conversation_state()
        if conv is None:
            return ""
        return conv.get_wandering_context()
