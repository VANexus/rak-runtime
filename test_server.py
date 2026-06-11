"""StreamASR 测试 — 零本地依赖"""
import sys, os, struct, math
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))

import grpc
from generated import runtime_pb2, runtime_pb2_grpc


def pcm_sine(sec=1.0, sr=16000):
    """生成正弦波 PCM 测试音频"""
    n = int(sr * sec)
    return b''.join(
        struct.pack('<h', int(16000 * math.sin(2 * math.pi * 440 * i / sr)))
        for i in range(n)
    )


def test():
    channel = grpc.insecure_channel("localhost:50051")
    stub = runtime_pb2_grpc.RuntimeServiceStub(channel)

    # 发送配置包
    req = runtime_pb2.ASRRequest(
        config=runtime_pb2.ASRConfig(
            version="v0",
            trace_id="test_123",
            language="zh",
        )
    )

    # 生成测试音频（1秒正弦波）
    audio = pcm_sine(1.0)
    req2 = runtime_pb2.ASRRequest(audio_chunk=audio)

    def gen():
        yield req
        yield req2

    for res in stub.StreamASR(gen()):
        print(f"结果：{res.text}")


if __name__ == "__main__":
    test()
