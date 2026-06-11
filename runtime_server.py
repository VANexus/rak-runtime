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
        self._init_time = time.time()
        self._request_count = 0

        self._init_cognitive_modules()

    def _init_cognitive_modules(self):
        """初始化认知增强模块"""
        # 世界模型
        try:
            from src.core.world_model import WorldModel
            self._world_model = WorldModel()
            logger.info("世界模型已初始化")
        except Exception as e:
            logger.warning(f"世界模型初始化失败（降级运行）: {e}")

        # 提示词引擎
        try:
            from src.core.prompt_engine import PromptEngine
            self._prompt_engine = PromptEngine()
            logger.info("提示词引擎已初始化")
        except Exception as e:
            logger.warning(f"提示词引擎初始化失败（降级运行）: {e}")

        # 语义缓存
        try:
            from src.core.semantic_cache import SemanticCache
            self._semantic_cache = SemanticCache()
            logger.info("语义缓存已初始化")
        except Exception as e:
            logger.warning(f"语义缓存初始化失败（降级运行）: {e}")

        # 学习闭环
        try:
            from src.core.learning_loop import LearningLoop
            self._learning_loop = LearningLoop()
            logger.info("学习闭环已初始化")
        except Exception as e:
            logger.warning(f"学习闭环初始化失败（降级运行）: {e}")

        # 主动智能引擎
        try:
            from src.core.proactive_engine import ProactiveEngine
            self._proactive_engine = ProactiveEngine()
            self._proactive_engine.set_dependencies(
                world_model=self._world_model,
                learning_loop=self._learning_loop,
            )
            logger.info("主动智能引擎已初始化")
        except Exception as e:
            logger.warning(f"主动智能引擎初始化失败（降级运行）: {e}")

        # 自我模型
        try:
            from src.core.self_model import SelfModel
            import os
            data_dir = os.path.join(os.path.dirname(__file__), "data")
            os.makedirs(data_dir, exist_ok=True)
            persist_path = os.path.join(data_dir, "self_model.json")
            self._self_model = SelfModel.load(persist_path)
            logger.info("自我模型已初始化")
        except Exception as e:
            logger.warning(f"自我模型初始化失败（降级运行）: {e}")

        # 需求引擎
        try:
            from src.core.need_engine import NeedEngine
            self._need_engine = NeedEngine()
            logger.info("需求引擎已初始化")
        except Exception as e:
            logger.warning(f"需求引擎初始化失败（降级运行）: {e}")

        # 联想记忆流
        try:
            from src.core.memory_stream import MemoryStream
            self._memory_stream = MemoryStream()
            logger.info("联想记忆流已初始化")
        except Exception as e:
            logger.warning(f"联想记忆流初始化失败（降级运行）: {e}")

        # 情绪引擎
        try:
            from src.core.emotion_state import EmotionEngine
            self._emotion_engine = EmotionEngine()
            logger.info("情绪引擎已初始化")
        except Exception as e:
            logger.warning(f"情绪引擎初始化失败（降级运行）: {e}")

        # 内心循环（Agent 的心跳）
        try:
            from src.core.inner_loop import InnerLoop
            self._inner_loop = InnerLoop()
            self._inner_loop.set_dependencies(
                emotion_engine=self._emotion_engine,
                need_engine=self._need_engine,
                self_model=self._self_model,
                world_model=self._world_model,
            )
            logger.info("内心循环已初始化")
        except Exception as e:
            logger.warning(f"内心循环初始化失败（降级运行）: {e}")

    # ── gRPC 接口实现 ─────────────────────────────────────

    def Execute(self, request, context):
        """Execute — 单次请求/响应决策"""
        self._request_count += 1
        trace_id = request.trace_id or f"exec-{self._request_count}"
        logger.info(f"[Execute] trace_id={trace_id}, action={request.action}")

        # 更新世界模型
        if self._world_model:
            try:
                self._update_world_model(request)
            except Exception as e:
                logger.warning(f"世界模型更新失败: {e}")

        # 决策
        try:
            result = self.decision_engine.decide(request)
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
        response = runtime_pb2.ActionResponse(
            version="v0",
            status=result.get("status", "error"),
            trace_id=trace_id,
            action=result.get("action", ""),
            params_json=result.get("params_json", "{}"),
            voice_reply=result.get("answer", ""),
        )

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

                # 音频管线处理
                try:
                    event = self.audio_pipeline.process_audio(audio_bytes, task_id)
                except Exception as e:
                    logger.error(f"音频管线异常: {e}")
                    event = {
                        "type": "error",
                        "error_code": "PIPELINE_ERROR",
                        "error_message": str(e),
                    }

                # 如果有动作结果，注入可用动作
                if event.get("type") == "action_result":
                    available_actions = [
                        "shake_head", "wave_hand", "lock_open", "lock_close",
                        "move_forward", "move_back", "turn_left", "turn_right",
                        "dance", "nod", "light_on", "light_off",
                        "emergency_stop", "idle",
                    ]
                    try:
                        decision = self.decision_engine.decide_from_text(
                            text=event.get("text", ""),
                            available_actions=available_actions,
                            trace_id=task_id,
                        )
                        event["actions"] = decision.get("actions", [])
                    except Exception as e:
                        logger.error(f"动作决策失败: {e}")

                # 生成 trace_id
                trace_id = f"asr-{int(time.time() * 1000)}"

                # 序列化动作结果
                actions_json = ""
                if event.get("actions"):
                    actions_json = json.dumps(
                        event["actions"], ensure_ascii=False, indent=2
                    )

                yield runtime_pb2.ASRResponse(
                    text=event.get("text", ""),
                    trace_id=trace_id,
                    is_final=True,
                    confidence=0.9,
                    status=event.get("type", "error"),
                    error_message=event.get("error_message", ""),
                )

            elif request.HasField("config"):
                logger.info("[StreamASR] 配置: language=%s, rate=%d",
                            request.config.language, request.config.sample_rate)

        logger.info("[StreamASR] 客户端断开")

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
    """启动 gRPC 服务器"""
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

    # 启动内心循环（Agent 的心跳）
    loop = asyncio.new_event_loop()
    if servicer._inner_loop:
        loop.run_until_complete(servicer._inner_loop.start())
        logger.info("  inner_loop: ✓ 心跳已启动")

    # 优雅关闭
    def graceful_shutdown(signum, frame):
        logger.info("收到关闭信号，正在优雅关闭...")
        # 保存所有记忆到磁盘
        try:
            save_all_memories()
        except Exception as e:
            logger.warning("保存记忆失败: %s", e)
        if servicer._inner_loop:
            loop.run_until_complete(servicer._inner_loop.stop())
        if servicer._proactive_engine:
            loop.run_until_complete(servicer._proactive_engine.stop())
        server.stop(grace=5)
        logger.info("服务器已关闭")
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        graceful_shutdown(None, None)


if __name__ == "__main__":
    serve()
