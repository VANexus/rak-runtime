"""
性能基准测试（规范化版，P4-3）

纯内存/本地 IO，不依赖 LLM、不需要网络——测量各子系统热路径的
单次操作时延（p50/p95/p99）与吞吐，作为回归基线。

覆盖面：
- SemanticCache：精确命中 / 改写命中
- CognitiveMemoryEngine：remember / recall（含默认字符 n-gram embedding）
- MetaCognition：evaluate_confidence（含校准因子）
- EmotionPerception：perceive（词典法）
- UserModel：record_interaction（含 JSON 持久化，tmp 目录）
- ProactiveEngine：_predict_needs（多特征）

LLM 全管线时延不在此测（需 API key），见 llm_life_benchmark.py。

运行：python tests/perf_benchmark.py
"""

import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.semantic_cache import SemanticCache
from src.core.memory_engine import CognitiveMemoryEngine
from src.core.meta_cognition import MetaCognition
from src.core.emotion_perception import EmotionPerception
from src.core.user_model import UserModel
from src.core.proactive_engine import ProactiveEngine

N = 500  # 每项操作次数


def _percentiles(samples):
    """p50 / p95 / p99（毫秒）"""
    s = sorted(samples)
    def pct(p):
        idx = min(len(s) - 1, int(len(s) * p / 100))
        return s[idx] * 1000
    return pct(50), pct(95), pct(99)


def _bench(name, fn, n=N):
    """跑 n 次取时延分布，打印一行结果"""
    samples = []
    for i in range(n):
        t0 = time.perf_counter()
        fn(i)
        samples.append(time.perf_counter() - t0)
    p50, p95, p99 = _percentiles(samples)
    ops = 1.0 / statistics.mean(samples)
    print(f"  {name:<36} p50={p50:8.3f}ms  p95={p95:8.3f}ms  "
          f"p99={p99:8.3f}ms  ~{ops:9.0f} ops/s")
    return {"name": name, "p50": p50, "p95": p95, "p99": p99, "ops": ops}


def bench_semantic_cache(results):
    print("\n[1] SemanticCache")
    cache = SemanticCache()
    actions = ["light_on", "music_play"]
    for i in range(100):
        cache.store(f"打开客厅的灯然后播放音乐{i}", {"action": "light_on"}, actions)
    results.append(_bench(
        "精确命中（exact lookup）",
        lambda i: cache.lookup(f"打开客厅的灯然后播放音乐{i % 100}", actions)))


def bench_memory(results):
    print("\n[2] CognitiveMemoryEngine（默认字符 n-gram embedding）")
    engine = CognitiveMemoryEngine()
    for i in range(200):
        engine.remember(f"用户在周{i % 7}上午习惯把客厅灯调到 {30 + i}%",
                        memory_type="semantic", importance=0.5 + (i % 50) / 100)

    def _remember(i):
        engine.remember(f"临时记忆条目 {i}：用户喜欢把空调设定为 26 度",
                        memory_type="episodic", importance=0.3)

    def _recall(i):
        engine.recall("用户喜欢把空调调到几度", top_k=5)

    results.append(_bench("remember（写入+embedding）", _remember, n=200))
    results.append(_bench("recall（top_k=5 语义检索）", _recall))


def bench_meta(results):
    print("\n[3] MetaCognition.evaluate_confidence")
    meta = MetaCognition()
    results.append(_bench(
        "缓存命中场景（含校准因子）",
        lambda i: meta.evaluate_confidence("打开灯", cache_hit=True,
                                           cache_similarity=0.99)))


def bench_emotion(results):
    print("\n[4] EmotionPerception（词典法）")
    p = EmotionPerception()
    results.append(_bench(
        "perceive（情绪句）",
        lambda i: p.perceive("你们这个产品真的太让人恼火了，烦死了！")))


def bench_user_model(results):
    print("\n[5] UserModel.record_interaction（含 JSON 持久化）")
    with tempfile.TemporaryDirectory() as tmp:
        um = UserModel(str(Path(tmp) / "user_model.json"))
        results.append(_bench(
            "record_interaction（写盘）",
            lambda i: um.record_interaction(f"打开灯{i}", "light_on"), n=200))


def bench_proactive(results):
    print("\n[6] ProactiveEngine._predict_needs（多特征）")
    um = UserModel()
    um.behavior.frequent_devices = {"light": 20}
    engine = ProactiveEngine()
    engine.set_dependencies(user_model=um)

    def _predict(i):
        asyncio.run(engine._predict_needs())

    results.append(_bench("_predict_needs", _predict, n=100))


def main():
    print("=" * 78)
    print("rak-runtime 性能基准（无 LLM、无网络）")
    print("=" * 78)

    results = []
    bench_semantic_cache(results)
    bench_memory(results)
    bench_meta(results)
    bench_emotion(results)
    bench_user_model(results)
    bench_proactive(results)

    print("\n" + "=" * 78)
    print(f"共 {len(results)} 项。注意：首次调用含懒初始化，建议以 p95/p99 观察尾部。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
