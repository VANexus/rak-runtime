# runtime_server.py
import sys
import os
import grpc
import json
import logging
from concurrent import futures

# 添加 generated 目录到系统路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))
try:
    from generated import runtime_pb2, runtime_pb2_grpc
    print("[INFO] Successfully imported generated gRPC files.")
except ImportError as e:
    print(f"[ERROR] Failed to import generated files: {e}")

# 从 src 目录导入我们的模块
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from src.core.decision_engine import DecisionEngine
from src.tools.mqtt_publisher import mqtt_publisher

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class RuntimeService(runtime_pb2_grpc.RuntimeServiceServicer):
    def __init__(self):
        self.engine = DecisionEngine()

    def Execute(self, request, context):
        """gRPC Execute 方法 - 现在它只是一个协调者"""
        trace_id = request.trace_id
        logging.info(f"[TraceID: {trace_id}] 收到 gRPC 请求")

        # 1. 调用核心决策引擎
        decision = self.engine.decide(request)

        # 2. 构建 gRPC 响应
        response = runtime_pb2.ActionResponse()
        response.version = "v0"
        response.trace_id = trace_id
        response.status = decision.get("status", "error")

        if response.status == "ok":
            response.action = decision["action"]
            response.params_json = decision["params_json"]
            # 决策成功后，通过 MQTT 下发指令
            mqtt_publisher.publish_action(
                target=request.target,
                action=response.action,
                params_json=response.params_json
            )
        else:
            # 决策失败，填充错误信息
            response.error_code = decision.get("error_code", "UNKNOWN_ERROR")
            response.error_message = decision.get("error_message", "决策失败")

        return response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    runtime_pb2_grpc.add_RuntimeServiceServicer_to_server(RuntimeService(), server)
    server.add_insecure_port('[::]:50051')
    logging.info("Fake Runtime 服务启动，监听端口 50051...")
    server.start()
    
    try:
        while True:
            pass # 保持服务运行
    except KeyboardInterrupt:
        server.stop(0)
        logging.info("服务已停止")

if __name__ == '__main__':
    serve()