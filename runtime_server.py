"""
rak-runtime gRPC 服务器

启动 gRPC 服务器，提供：
- RuntimeService.Execute — 单次请求/响应决策
- RuntimeService.StreamASR — 双向流式语音识别

用法：
    python runtime_server.py

环境变量：
    ANTHROPIC_AUTH_TOKEN — Anthropic API Key（必需）
    RUNTIME_PORT — 监听端口（默认 50051）
    MQTT_BROKER_HOST — MQTT Broker 地址（默认 localhost）
    MQTT_BROKER_PORT — MQTT Broker 端口（默认 1883）
"""

import asyncio
import json
import logging
import os
import sys
import signal
import time

import grpc
from concurrent import futures

# 添加项目根目录和 generated 目录到 sys.path
_root = os.path.dirname(__file__)
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "generated"))

from generated import runtime_pb2, runtime_pb2_grpc
from src.core.decision_engine import DecisionEngine, save_all_memories
from src.core.audio_pipeline import DualPipelineProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rak.server")


class RuntimeServicer(runtime_pb2_grpc.RuntimeServiceServicer):
    """gRPC 服务实现"""

    def __init__(self):
        # 核心模块
        self.decision_engine = DecisionEngine()
        self.audio_pipeline = DualPipelineProcessor(decision_engine=self.decision_engine)

        # 认知增强模块（延迟初始化）
        self._world_model = None
        self._prompt_engine = None
        self._semantic_cache = None
        self._learning_loop = None
        self._proactive_engine = None
        self._self_model = None
        self._need_engine = None
        self._memory_stream = None
        self._emotion_engine = None
        self._inner_loop = None
        self._sleep_consolidation = None
        self._init_time = time.time()
        self._request_count = 0

        # 常驻事件循环（serve() 注入）+ MVP 动作集
        self._loop = None
        self._available_actions = [
            "shake_head", "wave_hand", "lock_open", "lock_close",
            "move_forward", "move_back", "turn_left", "turn_right",
            "dance", "nod", "light_on", "light_off",
            "emergency_stop", "idle",
        ]

        self._init_cognitive_modules()

    def _init_cognitive_modules(self):
        """
        从 decision_engine 单例拉取认知模块。

        统一实例来源：decision_engine 的模块级单例是唯一事实源，
        这里不再自建并行实例（否则 InnerLoop 有依赖没被启动、被启动的没依赖）。
        """
        from src.core.decision_engine import (
            _get_world_model, _get_prompt_engine, _get_semantic_cache,
            _get_learning_loop, _get_proactive_engine, _get_self_model,
            _get_need_engine, _get_memory_stream, _get_emotion_engine,
            _get_inner_loop, _get_sleep_consolidation,
        )
        from src.core.outbound import get_outbound

        modules = {
            "world_model": _get_world_model,
            "prompt_engine": _get_prompt_engine,
            "semantic_cache": _get_semantic_cache,
            "learning_loop": _get_learning_loop,
            "proactive_engine": _get_proactive_engine,
            "self_model": _get_self_model,
            "need_engine": _get_need_engine,
            "memory_stream": _get_memory_stream,
            "emotion_engine": _get_emotion_engine,
            "inner_loop": _get_inner_loop,
            "sleep_consolidation": _get_sleep_consolidation,
        }
        for name, getter in modules.items():
            try:
                setattr(self, f"_{name}", getter())
                if getattr(self, f"_{name}") is not None:
                    logger.info("认知模块 %s: ✓", name)
            except Exception as e:
                logger.warning("认知模块 %s 初始化失败（降级运行）: %s", name, e)
                setattr(self, f"_{name}", None)

        # 出站通道：大脑主动说话/告警 → MQTT（RAK_OUTBOUND=1 才真发）
        outbound = get_outbound()
        if self._inner_loop:
            self._inner_loop.set_speak_callback(
                lambda text: asyncio.to_thread(outbound.speak, text)
            )
        if self._proactive_engine:
            self._proactive_engine.set_alert_callback(
                lambda alert: asyncio.to_thread(outbound.alert, alert)
            )
        logger.info("出站通道已接线（InnerLoop speak + ProactiveEngine alert）")

    # ── gRPC 接口实现 ─────────────────────────────────────

    def Execute(self, request, context):
        """Execute — 单次请求/响应决策"""
        self._request_count += 1
        trace_id = request.trace_id or f"exec-{self._request_count}"
        logger.info(f"[Execute] trace_id={trace_id}, action={request.action}")

        # 读取 gRPC metadata 中的 force-llm 标志
        force_llm = False
        try:
            md = dict(context.invocation_metadata())
            force_llm = md.get("force-llm", "").lower() == "true"
            if force_llm:
                logger.info(f"[Execute] force_llm=True，跳过缓存")
        except Exception as e:
            logger.debug(f"[Execute] 读取 metadata 失败: {e}")

        # 更新世界模型
        if self._world_model:
            try:
                self._update_world_model(request)
            except Exception as e:
                logger.warning(f"世界模型更新失败: {e}")

        # 决策
        try:
            result = self.decision_engine.decide(request, force_llm=force_llm)
        except Exception as e:
            logger.error(f"决策引擎异常: {e}", exc_info=True)
            result = {
                "status": "error",
                "error_code": "ENGINE_ERROR",
                "error_message": str(e),
            }

        # 处理确认请求（元认知低置信度）
        if result.get("status") == "confirm":
            return runtime_pb2.ActionResponse(
                version="v0",
                status="confirm",
                trace_id=trace_id,
                action=result.get("suggested_action", ""),
                params_json=json.dumps({}),
                error_code="CONFIRMATION_NEEDED",
                error_message=result.get("message", "需要用户确认"),
            )

        # 构造响应
        cognitive = result.get("cognitive_state", {})
        response = runtime_pb2.ActionResponse(
            version="v0",
            status=result.get("status", "error"),
            trace_id=trace_id,
            action=result.get("action", ""),
            params_json=result.get("params_json", "{}"),
            voice_reply=result.get("answer", ""),
            cognitive_state=json.dumps(cognitive, ensure_ascii=False) if cognitive else "",
        )

        # 多动作结果（复合指令分解）→ repeated ActionItem
        actions = result.get("actions", [])
        if actions:
            for a in actions[:10]:
                response.actions.extend([runtime_pb2.ActionItem(
                    action=a.get("action", ""),
                    params_json=a.get("params_json", "{}"),
                    target_device=a.get("target_device", ""),
                    priority=a.get("priority", 0),
                )])

        if result.get("status") == "error":
            response.error_code = result.get("error_code", "UNKNOWN")
            response.error_message = result.get("error_message", "")

        return response

    def StreamASR(self, request_iterator, context):
        """StreamASR — 双向流式语音识别"""
        logger.info("[StreamASR] 客户端连接")

        for request in request_iterator:
            if request.HasField("audio_chunk"):
                audio_bytes = request.audio_chunk
                logger.info("[StreamASR] 收到音频片段 (%d bytes)", len(audio_bytes))

                # 生成任务 ID
                task_id = f"asr-{int(time.time())}"

                # 音频双管线处理（在常驻事件循环上执行）
                try:
                    result = self._run_audio_pipeline(audio_bytes, task_id)
                except Exception as e:
                    logger.error("[StreamASR] 音频管线异常: %s", e)
                    result = None

                if result is not None and result.asr_text:
                    logger.info("[StreamASR] 转写: '%s', %d 个动作",
                                result.asr_text[:50], len(result.actions))
                    yield runtime_pb2.ASRResponse(
                        text=result.asr_text,
                        trace_id=task_id,
                        is_final=True,
                        confidence=0.9,
                        status="ok",
                        error_message="",
                    )
                else:
                    yield runtime_pb2.ASRResponse(
                        text="",
                        trace_id=task_id,
                        is_final=True,
                        confidence=0.0,
                        status="error",
                        error_message="音频处理失败或无转写结果",
                    )

            elif request.HasField("config"):
                logger.info("[StreamASR] 配置: language=%s, rate=%d",
                            request.config.language, request.config.sample_rate)

        logger.info("[StreamASR] 客户端断开")

    def _run_audio_pipeline(self, audio_bytes: bytes, task_id: str):
        """
        在常驻事件循环上运行音频双管线（gRPC 线程 → 事件循环线程的桥接）。

        DualPipelineProcessor.process_audio 是 async 且 PersonaPlex 连接
        绑定在事件循环线程，必须经 run_coroutine_threadsafe 调度。
        """
        if self._loop is None:
            raise RuntimeError("事件循环未启动")
        coro = self.audio_pipeline.process_audio(
            audio_pcm=audio_bytes,
            available_actions=self._available_actions,
            trace_id=task_id,
            device_id="default",
        )
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    # ── 世界模型更新 ──────────────────────────────────────

    def _update_world_model(self, request):
        """从请求中提取设备状态，更新世界模型"""
        if not request.state:
            return

        try:
            state_data = json.loads(request.state)
            if isinstance(state_data, dict):
                device_id = state_data.get("device_id", "default")
                self._world_model.update_device(
                    device_id=device_id,
                    online=state_data.get("online", True),
                    capabilities=state_data.get("capabilities"),
                    position=state_data.get("position"),
                    sensors=state_data.get("sensors"),
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # ── 主动智能启动 ──────────────────────────────────────

    async def start_proactive(self):
        """启动主动智能引擎和内心循环（异步）"""
        if self._proactive_engine:
            await self._proactive_engine.start()
        if self._inner_loop:
            await self._inner_loop.start()

    def get_cognitive_stats(self) -> dict:
        """获取认知系统全量统计"""
        uptime = int(time.time() - self._init_time)
        return {
            "uptime_seconds": uptime,
            "total_requests": self._request_count,
            "world_model": self._world_model.stats() if self._world_model else None,
            "semantic_cache": self._semantic_cache.stats() if self._semantic_cache else None,
            "learning_loop": self._learning_loop.stats() if self._learning_loop else None,
            "prompt_engine": self._prompt_engine.stats() if self._prompt_engine else None,
            "user_model": self.decision_engine.get_user_model_stats(),
            "meta_cognition": self.decision_engine.get_meta_cognition_stats(),
            "proactive_engine": self._proactive_engine.get_stats() if self._proactive_engine else None,
            "self_model": self._self_model.get_stats() if self._self_model else None,
            "need_engine": self._need_engine.get_stats() if self._need_engine else None,
            "memory_stream": self._memory_stream.get_stats() if self._memory_stream else None,
            "emotion_engine": self._emotion_engine.get_stats() if self._emotion_engine else None,
            "inner_loop": self._inner_loop.get_stats() if self._inner_loop else None,
        }


def serve():
    """启动 gRPC 服务器 + 常驻心跳事件循环"""
    port = os.getenv("RUNTIME_PORT", "50051")

    # 创建服务器
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ("grpc.max_receive_message_length", 10 * 1024 * 1024),
            ("grpc.max_send_message_length", 10 * 1024 * 1024),
        ],
    )

    servicer = RuntimeServicer()
    runtime_pb2_grpc.add_RuntimeServiceServicer_to_server(servicer, server)

    server.add_insecure_port(f"[::]:{port}")
    server.start()

    logger.info("=" * 60)
    logger.info("  rak-runtime gRPC 服务器已启动")
    logger.info(f"  端口: {port}")
    logger.info("=" * 60)

    # 打印认知系统状态
    stats = servicer.get_cognitive_stats()
    for module, info in stats.items():
        if info is not None:
            logger.info(f"  {module}: {'✓' if info else '✗'}")

    # ── 常驻事件循环：心跳 + 主动智能 + 睡眠整合 + 音频管线 ──
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    servicer._loop = loop

    async def _start_heartbeat():
        """启动大脑的心跳（InnerLoop + ProactiveEngine + Sleep 定时器）"""
        if servicer._inner_loop:
            await servicer._inner_loop.start()
            logger.info("  inner_loop: ✓ 心跳已启动")
        if servicer._proactive_engine:
            await servicer._proactive_engine.start()
            logger.info("  proactive_engine: ✓ 主动智能已启动")
        asyncio.create_task(_sleep_loop())

    async def _sleep_loop(interval_minutes: float = 15.0):
        """睡眠整合定时器（记忆巩固 + 遗忘 + 反思）"""
        while True:
            await asyncio.sleep(interval_minutes * 60)
            if servicer._sleep_consolidation:
                try:
                    servicer._sleep_consolidation.consolidate()
                    logger.info("[Sleep] 睡眠整合完成")
                except Exception as e:
                    logger.warning("[Sleep] 睡眠整合失败: %s", e)

    loop.run_until_complete(_start_heartbeat())

    # 优雅关闭：信号 → 停 loop → finally 收尾
    def graceful_shutdown(signum, frame):
        logger.info("收到关闭信号，正在优雅关闭...")
        loop.stop()

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # 保存所有记忆到磁盘
        try:
            save_all_memories()
        except Exception as e:
            logger.warning("保存记忆失败: %s", e)
        # 停止心跳
        if servicer._inner_loop:
            try:
                loop.run_until_complete(servicer._inner_loop.stop())
            except Exception:
                pass
        if servicer._proactive_engine:
            try:
                loop.run_until_complete(servicer._proactive_engine.stop())
            except Exception:
                pass
        server.stop(grace=5)
        loop.close()
        logger.info("服务器已关闭")


if __name__ == "__main__":
    serve()
