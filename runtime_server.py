import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))

import grpc
from concurrent import futures
import json
import time
from generated import runtime_pb2
from generated import runtime_pb2_grpc

class RuntimeService(runtime_pb2_grpc.RuntimeServiceServicer):
    def Execute(self, request, context):
        """
        处理gRPC Execute请求
        当前实现最简单的决策逻辑
        """
        print(f"[Runtime] 收到请求: trace_id={request.trace_id}")
        print(f"  state: {request.state}")
        print(f"  available_actions: {request.available_actions}")
        print(f"  action: {request.action}")
        print(f"  params_json: {request.params_json}")
        
        # 创建响应对象
        response = runtime_pb2.ActionResponse()
        response.version = "v0"
        response.trace_id = request.trace_id
        
        # 决策模式1: 动作确认（前端已明确动作）
        if request.action:
            if request.action in request.available_actions:
                response.action = request.action
                response.params_json = request.params_json
                response.status = "ok"
                print(f"  决策: 确认动作 {request.action}")
            else:
                response.status = "error"
                response.error_code = "ACTION_NOT_ALLOWED"
                response.error_message = f"动作 {request.action} 不在允许列表中"
                print(f"  错误: 动作不允许")
        
        # 决策模式2: 状态转动作（前端只给状态，Runtime决定动作）
        else:
            # 最简单的决策逻辑：选第一个可用动作
            if request.available_actions:
                chosen_action = request.available_actions[0]
                response.action = chosen_action
                
                # 为不同动作设置默认参数
                params = {}
                if chosen_action == "move_forward":
                    params = {"distance_cm": 5, "speed": 50}
                elif chosen_action == "turn_left":
                    params = {"angle_deg": 90, "speed": 30}
                
                response.params_json = json.dumps(params, ensure_ascii=False)
                response.status = "ok"
                print(f"  决策: 自动选择动作 {chosen_action}")
            else:
                response.status = "error"
                response.error_code = "DECISION_FAILED"
                response.error_message = "无可用动作"
                print(f"  错误: 无可用动作")
        
        return response

def serve():
    """启动gRPC服务器"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    runtime_pb2_grpc.add_RuntimeServiceServicer_to_server(RuntimeService(), server)
    server.add_insecure_port('[::]:50051')
    print("Fake Runtime 服务启动，监听端口 50051...")
    print("按 Ctrl+C 停止服务")
    server.start()
    
    try:
        while True:
            time.sleep(86400)  # 一天
    except KeyboardInterrupt:
        server.stop(0)
        print("服务已停止")

if __name__ == '__main__':
    serve()