import sys
import os
import grpc
import logging
from concurrent import futures
import time

# 添加路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# gRPC 导入
import generated.runtime_pb2 as runtime_pb2
import generated.runtime_pb2_grpc as runtime_pb2_grpc

# 业务模块
from src.core.decision_engine import DecisionEngine
from src.tools import ASRTool

# 日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# ✅ 关键：继承正确的基类
class RuntimeService(runtime_pb2_grpc.RuntimeServiceServicer):
    def __init__(self):
        self.decision_engine = DecisionEngine()

        # 加载ASR模型
        print("[INFO] 正在加载Whisper模型...")
        self.asr_tool = ASRTool()
        print("[INFO] Whisper模型加载完成！")

    def Execute(self, request, context):
        trace_id = request.trace_id
        logging.info(f"[TraceID: {trace_id}] 收到 gRPC 请求")

        decision = self.decision_engine.decide(request)

        response = runtime_pb2.ActionResponse()
        response.version = "v0"
        response.trace_id = trace_id
        response.status = decision.get("status", "error")

        if response.status == "ok":
            response.action = decision["action"]
            response.params_json = decision["params_json"]
        else:
            response.error_code = decision.get("error_code", "UNKNOWN_ERROR")
            response.error_message = decision.get("error_message", "决策失败")

        return response

    # ✅ 关键：方法名必须和proto完全一致，且缩进在类里面
    def StreamASR(self, request_iterator, context):
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