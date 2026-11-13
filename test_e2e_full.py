#!/usr/bin/env python3
"""
端到端全链路测试（2026-09 重定位后口径）

现役架构：
  - rak-runtime = 旁路认知引擎，消费方 gRPC 直连 :50051（Execute / StreamASR）
  - go-kernel   = MCP 联邦网关 :8090（聚合 rak-flowmind 等后端），
                  **不在 rak-runtime 的调用链上**，本脚本只做可达性检查（失败仅告警）

测试内容：
  1. gRPC 直连 rak-runtime（文本决策）
  2. gRPC 直连 rak-runtime（音频双管线 PersonaPlex + ASR/LLM）
  3. go-kernel /api/health 可达性（可选）
  4. go-kernel /metrics 可达性（可选）

说明：旧脚本中的 /api/v1/action/execute 与 PA-HPS 调度器端点已随 go-kernel
AIoT 定位废弃（见 go-kernel/TODO.md 2026-09 重定位），相应用例移除。
"""
import sys, os, json, time, struct, math, base64, requests
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import grpc
import generated.runtime_pb2 as pb
import generated.runtime_pb2_grpc as pb_grpc

RUNTIME_ADDR = os.getenv("RUNTIME_ADDR", "localhost:50051")
KERNEL_ADDR  = os.getenv("KERNEL_ADDR", "http://localhost:8090")

ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "nod", "dance", "move_forward", "move_back",
    "light_on", "light_off", "emergency_stop",
]

def pcm_sine(sec=2.0, sr=16000):
    n = int(sr * sec)
    return b''.join(struct.pack('<h', int(16000*math.sin(2*math.pi*440*i/sr))) for i in range(n))

# ─────────────────────── 测试 1: gRPC 文本路径 ───────────────────────
def test_grpc_text(stub):
    print("\n" + "="*60)
    print("测试1: gRPC 文本路径（单动作决策）")
    print("="*60)
    req = pb.ActionRequest(
        version="v0", trace_id="e2e-text-001",
        source="test:e2e", target="runtime:default",
        state="", available_actions=ACTIONS,
        action="lock_open", params_json="{}",
    )
    t0 = time.time()
    resp = stub.Execute(req)
    dt = time.time() - t0

    print(f"  status:      {resp.status}")
    print(f"  action:      {resp.action}")
    print(f"  params:      {resp.params_json}")
    print(f"  asr_text:    '{resp.asr_text}'")
    print(f"  voice_reply: '{resp.voice_reply}'")
    print(f"  actions:     {len(resp.actions)}")
    print(f"  cognitive_state: {resp.cognitive_state[:120]}")
    print(f"  latency:     {dt:.2f}s")

    ok = resp.status == "ok" and resp.action == "lock_open"
    print(f"  {'✅' if ok else '❌'} 文本路径{'通过' if ok else '失败'}")
    return ok

# ─────────────────────── 测试 2: gRPC 音频双管线 ───────────────────────
def test_grpc_audio(stub):
    print("\n" + "="*60)
    print("测试2: gRPC 音频双管线（PersonaPlex + ASR/LLM）")
    print("="*60)
    pcm = pcm_sine(2.0)
    print(f"  PCM: {len(pcm)} bytes (2s, 16kHz, 16bit, mono)")

    req = pb.ActionRequest(
        version="v0", trace_id="e2e-audio-001",
        source="test:e2e", target="runtime:default",
        state="", available_actions=ACTIONS,
        audio=pcm,
    )
    t0 = time.time()
    resp = stub.Execute(req)
    dt = time.time() - t0

    print(f"  status:      {resp.status}")
    print(f"  asr_text:    '{resp.asr_text}'")
    print(f"  voice_reply: '{resp.voice_reply}'")
    print(f"  voice_audio: {len(resp.voice_audio)} bytes")
    print(f"  actions:     {len(resp.actions)}")
    for i, a in enumerate(resp.actions):
        print(f"    [{i+1}] {a.action} params={a.params_json} priority=Q{a.priority}")
    print(f"  latency_pp:  {resp.latency_personaplex_ms:.0f}ms")
    print(f"  latency_asr: {resp.latency_asr_ms:.0f}ms")
    print(f"  latency_llm: {resp.latency_llm_ms:.0f}ms")
    print(f"  总延迟:      {dt:.2f}s")

    ok = resp.status == "ok"
    if ok and len(resp.actions) > 0:
        print(f"  ✅ 双管线通过: {len(resp.actions)} 个原子动作")
    elif ok:
        print(f"  ⚠ 双管线通过（ASR 无结果，但链路正常）")
    else:
        print(f"  ❌ 双管线失败: {resp.error_code} - {resp.error_message}")
    return ok

# ─────────────── 测试 3/4: go-kernel 可达性（可选，仅告警） ───────────────
def _kernel_get(path, timeout=5):
    return requests.get(f"{KERNEL_ADDR}{path}", timeout=timeout)

def test_kernel_health():
    print("\n" + "="*60)
    print("测试3: go-kernel /api/health 可达性（可选）")
    print("="*60)
    try:
        resp = _kernel_get("/api/health")
        data = resp.json()
        print(f"  status:    {data.get('status')}")
        print(f"  service:   {data.get('service')}")
        print(f"  ✅ go-kernel 可达")
        return True
    except Exception as e:
        print(f"  ⚠ go-kernel 不可达（不在 rak-runtime 链路上，可忽略）: {e}")
        return False

def test_kernel_metrics():
    print("\n" + "="*60)
    print("测试4: go-kernel /metrics 可达性（可选）")
    print("="*60)
    try:
        resp = _kernel_get("/metrics")
        ok = resp.status_code == 200 and "go_kernel" in resp.text
        print(f"  HTTP {resp.status_code}, 指标条目 {'✅' if ok else '❌'}")
        return ok
    except Exception as e:
        print(f"  ⚠ /metrics 不可达（可忽略）: {e}")
        return False

# ─────────────────────── 主函数 ───────────────────────
def main():
    print("="*60)
    print("RakTec 端到端全链路测试（现役口径：rak-runtime gRPC 直连）")
    print("="*60)

    # 连接 rak-runtime
    print(f"\n连接 rak-runtime: {RUNTIME_ADDR}")
    try:
        ch = grpc.insecure_channel(RUNTIME_ADDR)
        grpc.channel_ready_future(ch).result(timeout=5)
        stub = pb_grpc.RuntimeServiceStub(ch)
        print("✅ rak-runtime gRPC 已连接")
    except Exception as e:
        print(f"❌ 无法连接 rak-runtime: {e}")
        sys.exit(1)

    print(f"\n检查 go-kernel（可选）: {KERNEL_ADDR}")
    try:
        _kernel_get("/api/health", timeout=3)
        print("✅ go-kernel 已连接")
    except Exception as e:
        print(f"⚠ go-kernel 不可用（不影响 rak-runtime 用例）: {e}")

    required = [
        ("gRPC 文本路径",   test_grpc_text(stub)),
        ("gRPC 音频双管线", test_grpc_audio(stub)),
    ]
    optional = [
        ("go-kernel /api/health", test_kernel_health()),
        ("go-kernel /metrics",    test_kernel_metrics()),
    ]

    ch.close()

    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)
    for name, ok in required:
        print(f"  {'✅' if ok else '❌'} {name}")
    for name, ok in optional:
        print(f"  {'✅' if ok else '⚠ (可选未达)'} {name}")

    passed = sum(1 for _, ok in required if ok)
    print(f"\n必测通过: {passed}/{len(required)}（可选 {'✅' if all(ok for _, ok in optional) else '部分未达'}）")
    return 0 if passed == len(required) else 1

if __name__ == "__main__":
    sys.exit(main())
