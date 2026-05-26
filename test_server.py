import grpc
from generated import runtime_pb2, runtime_pb2_grpc

def test():
    channel = grpc.insecure_channel("localhost:50051")
    stub = runtime_pb2_grpc.RuntimeServiceStub(channel)

    # 发送配置包
    req = runtime_pb2.ASRRequest(
        config=runtime_pb2.ASRConfig(
            version="v0",
            trace_id="test_123",
            language="zh"
        )
    )

    # 发送一段空音频（测试接口是否通）
    import numpy as np
    audio = np.zeros(16000, dtype=np.int16).tobytes()
    req2 = runtime_pb2.ASRRequest(audio_chunk=audio)

    # 调用StreamASR接口
    def gen():
        yield req
        yield req2

    for res in stub.StreamASR(gen()):
        print(f"结果：{res.text}")

if __name__ == "__main__":
    test()