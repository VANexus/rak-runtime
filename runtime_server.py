import sys
import os
import grpc
import logging
from concurrent import futures
import time
import asyncio

# 添加路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# gRPC 导入
import generated.runtime_pb2 as runtime_pb2
import generated.runtime_pb2_grpc as runtime_pb2_grpc

# 业务模块
from src.core.decision_engine import DecisionEngine
from src.core.audio_pipeline import DualPipelineProcessor, PipelineResult
from src.tools import ASRTool

# 日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class RuntimeService(runtime_pb2_grpc.RuntimeServiceServicer):
    def __init__(self):
        self.decision_engine = DecisionEngine()
        self.audio_pipeline = None  # 延迟初始化

        # 加载ASR模型（可选）
        if ASRTool is not None:
            print("[INFO] 正在加载Whisper模型...")
            self.asr_tool = ASRTool()
            print("[INFO] Whisper模型加载完成！")
        else:
            self.asr_tool = None
            print("[WARN] ASR 不可用（whisper 未安装），语音功能已禁用")

    def _get_audio_pipeline(self):
        """延迟初始化双管线处理器"""
        if self.audio_pipeline is None:
            self.audio_pipeline = DualPipelineProcessor(
                decision_engine=self.decision_engine,
                asr_tool=self.asr_tool,
            )
        return self.audio_pipeline

    def Execute(self, request, context):
        trace_id = request.trace_id
        logging.info(f"[TraceID: {trace_id}] 收到 gRPC 请求")

        response = runtime_pb2.ActionResponse()
        response.version = "v0"
        response.trace_id = trace_id

        # ========== 音频路径：双管线并行处理 ==========
        if request.audio:
            audio_size = len(request.audio)
            logging.info(f"[TraceID: {trace_id}] 检测到音频数据 ({audio_size} bytes)，启动双管线")

            result = self._process_audio_dual_pipeline(
                audio_bytes=request.audio,
                available_actions=list(request.available_actions),
                trace_id=trace_id,
            )

            response.status = "ok"
            response.asr_text = result.asr_text

            # PersonaPlex 语音回复（超快路径）
            response.voice_reply = result.voice_response
            if result.voice_audio:
                response.voice_audio = result.voice_audio

            # LLM 动作决策（主力路径）
            for action_item in result.actions:
                item = response.actions.add()
                item.action = action_item.get("action", "")
                item.params_json = action_item.get("params_json", "{}")
                item.target_device = action_item.get("target_device", "")
                item.priority = action_item.get("priority", 2)

            # 兼容单动作字段
            if result.actions:
                first = result.actions[0]
                response.action = first.get("action", "")
                response.params_json = first.get("params_json", "{}")

            # 延迟统计
            response.latency_personaplex_ms = result.latency_personaplex_ms
            response.latency_asr_ms = result.latency_asr_ms
            response.latency_llm_ms = result.latency_llm_ms

            logging.info(
                f"[TraceID: {trace_id}] 双管线完成: "
                f"PersonaPlex={result.latency_personaplex_ms:.0f}ms, "
                f"ASR={result.latency_asr_ms:.0f}ms, "
                f"LLM={result.latency_llm_ms:.0f}ms, "
                f"动作={len(result.actions)}个, "
                f"语音回复='{result.voice_response[:20]}'"
            )

        # ========== 文本路径：原有逻辑 ==========
        else:
            decision = self.decision_engine.decide(request)

            response.status = decision.get("status", "error")
            if response.status == "ok":
                response.action = decision["action"]
                response.params_json = decision["params_json"]
            else:
                response.error_code = decision.get("error_code", "UNKNOWN_ERROR")
                response.error_message = decision.get("error_message", "决策失败")

        return response

    def _process_audio_dual_pipeline(
        self,
        audio_bytes: bytes,
        available_actions: list,
        trace_id: str,
    ) -> PipelineResult:
        """
        双管线处理：PersonaPlex(超快回复) + ASR/LLM(动作决策)
        在 gRPC 线程中创建事件循环运行异步管线。
        """
        pipeline = self._get_audio_pipeline()

        # 创建新的事件循环（gRPC 线程中）
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                pipeline.process_audio(
                    audio_pcm=audio_bytes,
                    available_actions=available_actions,
                    trace_id=trace_id,
                )
            )
            return result
        except Exception as e:
            logging.error(f"[TraceID: {trace_id}] 双管线异常: {e}")
            import traceback
            traceback.print_exc()
            # 返回空结果，回退到规则引擎
            return PipelineResult(
                trace_id=trace_id,
                asr_text="",
                actions=self.decision_engine._rule_decompose("", available_actions),
            )
        finally:
            loop.close()

    def StreamASR(self, request_iterator, context):
        if self.asr_tool is None:
            yield runtime_pb2.ASRResponse(
                status="error",
                error_message="ASR 不可用（whisper 未安装）"
            )
            return

        trace_id = ""
        last_time = time.time()
        audio_buffer = []

        try:
            for req in request_iterator:
                if req.HasField("config"):
                    trace_id = req.config.trace_id
                    continue

                if req.HasField("audio_chunk"):
                    audio_buffer.append(req.audio_chunk)
                    if len(audio_buffer) > 3:
                        full_audio = b"".join(audio_buffer)
                        self.asr_tool.add_audio_chunk(full_audio)
                        audio_buffer = []

                    if time.time() - last_time >= 0.3:
                        text, conf = self.asr_tool.transcribe()
                        last_time = time.time()
                        if text:
                            yield runtime_pb2.ASRResponse(
                                text=text,
                                trace_id=trace_id,
                                is_final=True,
                                confidence=conf,
                                status="ok"
                            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield runtime_pb2.ASRResponse(
                status="error",
                error_message=str(e)
            )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    runtime_pb2_grpc.add_RuntimeServiceServicer_to_server(RuntimeService(), server)
    server.add_insecure_port('[::]:50051')
    logging.info("rak runtime 服务启动，监听端口 50051...")
    server.start()
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == '__main__':
    serve()
