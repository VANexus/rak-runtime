"""
LLM 生命感对话基准测试

通过真实的 LLM 决策管线测试 agent 的学习和记忆能力。
每个对话轮次都经过 LLM 推理，不走捷径。

测试流程：
  Day 1: 注入记忆、纠正、偏好
  ── 重启服务器 ──
  Day 2: 测试记忆存活、学习应用
  ── 重启服务器 ──
  Day 3: 测试长期记忆、纠正效果
"""

import sys
import os
import time
import json
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ========== 对话场景定义 ==========

DAY1_CONVERSATIONS = [
    # (输入描述, request_state, request_action, 验证函数)
    ("告诉 agent 关于猫的信息",
     "我家有一只猫叫小橘，她最喜欢吃鸡肉", "", None),

    ("告诉 agent 灯的偏好",
     "我喜欢把卧室的灯调到 50% 亮度，不要太亮", "", None),

    ("告诉 agent 日程",
     "我每天早上 7:30 有团队会议，提醒我别忘了", "", None),

    ("简单指令：开灯",
     "帮我开灯", "", lambda r: r.get("action") == "light_on"),

    ("简单指令：关门",
     "把门关上", "", lambda r: r.get("action") == "lock_close"),

    ("纠正：agent 错误时纠正它",
     "不对，我说的开门是 lock_open 不是 light_on", "",
     lambda r: True),  # 纠正不验证动作，只记录

    ("偏好测试：让 agent 简洁",
     "你回复太啰嗦了，能不能简洁一点", "", None),

    ("告诉 agent 更多个人信息",
     "我不喜欢突然的噪音，会被吓到", "", None),

    ("设备状态更新",
     "", "", None),  # 这轮通过 state 更新设备

    ("简单指令：确认学习效果",
     "开灯", "", lambda r: r.get("action") == "light_on"),
]

DAY2_CONVERSATIONS = [
    ("测试记忆：问猫的名字",
     "我家的猫叫什么名字？", "",
     lambda r: "小橘" in r.get("answer", "")),

    ("测试记忆：问灯的偏好",
     "我喜欢灯调到多少亮度？", "",
     lambda r: "50" in r.get("answer", "")),

    ("测试纠正效果：再次开灯",
     "帮我开灯", "", lambda r: r.get("action") == "light_on"),

    ("新指令：左转",
     "向左转", "", lambda r: r.get("action") == "turn_left"),

    ("告诉 agent 新信息",
     "我明天下午 3 点有个面试", "", None),

    ("偏好测试：回复风格",
     "今天天气怎么样？", "", None),  # 观察回复是否简洁
]

DAY3_CONVERSATIONS = [
    ("远期记忆测试：猫",
     "小橘最近怎么样？", "",
     lambda r: "小橘" in r.get("answer", "")),

    ("远期记忆测试：日程",
     "我明天早上有什么安排？", "",
     lambda r: "7:30" in r.get("answer", "") or "会议" in r.get("answer", "")),

    ("远期记忆测试：面试",
     "我明天下午的面试是几点？", "",
     lambda r: "3" in r.get("answer", "")),

    ("纠正记忆测试",
     "帮我锁门", "", lambda r: r.get("action") == "lock_close"),

    ("综合测试：复杂指令",
     "我有点冷，帮我调整一下", "", None),  # 观察 agent 的推理能力
]


def create_mock_request(query: str, action: str = ""):
    """创建模拟的 gRPC 请求对象"""
    class MockRequest:
        def __init__(self):
            self.version = "v0"
            self.trace_id = f"bench-{int(time.time()*1000)}"
            self.action = action
            self.state = query
            self.available_actions = [
                "shake_head", "wave_hand", "lock_open", "lock_close",
                "move_forward", "move_back", "turn_left", "turn_right",
                "dance", "nod", "light_on", "light_off",
                "emergency_stop", "idle",
            ]
            self.params_json = "{}"
    return MockRequest()


def run_conversations(engine, conversations, day_label):
    """运行一组对话，返回结果"""
    results = []
    print(f"\n{'='*60}")
    print(f"  {day_label}")
    print(f"{'='*60}")

    for i, (desc, query, action, validator) in enumerate(conversations):
        request = create_mock_request(query, action)
        t0 = time.time()
        try:
            response = engine.decide(request)
            latency = (time.time() - t0) * 1000
            status = response.get("status", "?")
            act = response.get("action", "?")

            # 验证
            passed = validator(response) if validator else None
            if passed is not None:
                symbol = "✓" if passed else "✗"
            else:
                symbol = "·"

            answer = response.get("answer", "")
            print(f"  {symbol} [{desc}]")
            print(f"    status={status}, action={act}, latency={latency:.0f}ms")
            if answer:
                print(f"    answer={answer[:80]}")
            if response.get("confidence_hint"):
                print(f"    confidence={response.get('confidence_hint', '')[:60]}")

            results.append({
                "desc": desc,
                "query": query,
                "status": status,
                "action": act,
                "latency": latency,
                "passed": passed,
                "response": response,
            })
        except Exception as e:
            latency = (time.time() - t0) * 1000
            print(f"  ✗ [{desc}] 错误: {e} ({latency:.0f}ms)")
            results.append({
                "desc": desc, "query": query, "status": "error",
                "action": "", "latency": latency, "passed": False,
                "response": {},
            })

    return results


def save_all(engine):
    """保存所有状态"""
    try:
        engine.save()  # memory
    except Exception:
        pass
    # 缓存通过 decision_engine 的 save_all_memories 保存


def start_engine():
    """创建新的决策引擎（模拟重启 — 重置所有模块级单例）"""
    import src.core.decision_engine as de

    # 重置所有模块级单例，模拟进程重启
    de._memory_engine = None
    de._llm_client = None
    de._semantic_cache = None
    de._prompt_engine = None
    de._learning_loop = None
    de._meta_cognition = None
    de._user_model = None
    de._self_model = None
    de._need_engine = None
    de._memory_stream = None
    de._emotion_engine = None
    de._living_graph = None
    de._inner_loop = None
    de._conversation_state = None

    return de.DecisionEngine()


# ========== 主测试 ==========

def main():
    print("=" * 60)
    print("  LLM 生命感对话基准测试")
    print("  每轮都经过真实 LLM 推理，中间重启验证持久化")
    print("=" * 60)

    data_dir = "/tmp/rak_life_test"
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    # 设置持久化目录
    os.environ.setdefault("RAK_DATA_DIR", data_dir)

    all_results = {}
    total_passed = 0
    total_tests = 0

    # === Day 1 ===
    print("\n[启动 Day 1 引擎...]")
    engine = start_engine()
    results_d1 = run_conversations(engine, DAY1_CONVERSATIONS, "Day 1: 注入记忆和偏好")
    all_results["day1"] = results_d1
    save_all(engine)
    del engine  # 模拟关闭

    # === 重启 ===
    print("\n[重启服务器...]")
    time.sleep(0.5)

    # === Day 2 ===
    print("[启动 Day 2 引擎...]")
    engine = start_engine()
    results_d2 = run_conversations(engine, DAY2_CONVERSATIONS, "Day 2: 测试记忆存活")
    all_results["day2"] = results_d2
    save_all(engine)
    del engine

    # === 重启 ===
    print("\n[重启服务器...]")
    time.sleep(0.5)

    # === Day 3 ===
    print("[启动 Day 3 引擎...]")
    engine = start_engine()
    results_d3 = run_conversations(engine, DAY3_CONVERSATIONS, "Day 3: 测试长期记忆")
    all_results["day3"] = results_d3
    save_all(engine)

    # ========== 评分 ==========
    print(f"\n{'='*60}")
    print("  评分汇总")
    print(f"{'='*60}")

    for day, results in all_results.items():
        tested = [r for r in results if r["passed"] is not None]
        passed = sum(1 for r in tested if r["passed"])
        total = len(tested)
        total_passed += passed
        total_tests += total

        avg_latency = sum(r["latency"] for r in results) / len(results) if results else 0
        ok_count = sum(1 for r in results if r["status"] == "ok")

        print(f"\n  {day}:")
        print(f"    验证通过: {passed}/{total}")
        print(f"    status=ok: {ok_count}/{len(results)}")
        print(f"    平均延迟: {avg_latency:.0f}ms")

    print(f"\n  总计: {total_passed}/{total_tests} 验证通过")

    if total_tests > 0:
        score = total_passed / total_tests
        print(f"  得分: {score:.2f}")
        if score >= 0.8:
            print("  评级: ⭐⭐⭐⭐⭐ 优秀")
        elif score >= 0.6:
            print("  评级: ⭐⭐⭐⭐ 良好")
        elif score >= 0.4:
            print("  评级: ⭐⭐⭐ 中等")
        else:
            print("  评级: ⭐⭐ 需改进")

    # 详细结果
    print(f"\n{'='*60}")
    print("  详细结果")
    print(f"{'='*60}")
    for day, results in all_results.items():
        print(f"\n  {day}:")
        for r in results:
            symbol = "✓" if r["passed"] else ("✗" if r["passed"] is not None else "·")
            print(f"    {symbol} {r['desc']}: action={r['action']}, latency={r['latency']:.0f}ms")


if __name__ == "__main__":
    main()
