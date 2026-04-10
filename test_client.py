import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))

import grpc
import json
from generated import runtime_pb2
from generated import runtime_pb2_grpc

def run_test():
    """测试gRPC调用"""
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = runtime_pb2_grpc.RuntimeServiceStub(channel)
        
        # 测试1: 动作确认模式
        print("测试1: 动作确认模式")
        request = runtime_pb2.ActionRequest(
            version="v0",
            trace_id="test-001",
            source="go_cloud",
            target="runtime_01",
            state="机器人位于原点，前方无障碍物",
            available_actions=["move_forward", "turn_left", "turn_right", "stop"],
            action="move_forward",  # 前端已指定动作
            params_json=json.dumps({"distance_cm": 10}, ensure_ascii=False)
        )
        
        try:
            response = stub.Execute(request)
            print(f"  状态: {response.status}")
            print(f"  动作: {response.action}")
            print(f"  参数: {response.params_json}")
            print(f"  错误码: {response.error_code}")
        except grpc.RpcError as e:
            print(f"  gRPC错误: {e}")
        
        # 测试2: 状态转动作模式
        print("\n测试2: 状态转动作模式")
        request2 = runtime_pb2.ActionRequest(
            version="v0",
            trace_id="test-002",
            source="go_cloud",
            target="runtime_01",
            state="机器人需要向前移动",
            available_actions=["move_forward", "turn_left", "turn_right", "stop"],
            # 不指定action，让Runtime决策
            params_json=json.dumps({}, ensure_ascii=False)
        )
        
        try:
            response2 = stub.Execute(request2)
            print(f"  状态: {response2.status}")
            print(f"  动作: {response2.action}")
            print(f"  参数: {response2.params_json}")
        except grpc.RpcError as e:
            print(f"  gRPC错误: {e}")

if __name__ == '__main__':
    run_test()