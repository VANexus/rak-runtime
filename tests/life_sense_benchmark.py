"""
生命感长期对话基准测试

模拟 3 天 × 350 轮 = 1050 轮对话，测试：
- 长期记忆召回
- 偏好学习
- 纠正记忆
- 情绪状态演变
- 人格一致性
- 世界模型积累

不依赖 LLM（纯内存测试），直接调用各子系统。
"""

import sys
import os
import time
import random
import json
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.memory_engine import CognitiveMemoryEngine
from src.core.user_model import UserModel
from src.core.emotion_state import EmotionEngine
from src.core.need_engine import NeedEngine
from src.core.self_model import SelfModel
from src.core.meta_cognition import MetaCognition
from src.core.conversation_state import ConversationState
from src.core.learning_loop import LearningLoop
from src.core.world_model import WorldModel
from src.core.semantic_cache import SemanticCache


# ========== 测试配置 ==========
DAYS = 3
TURNS_PER_DAY = 350
TOTAL_TURNS = DAYS * TURNS_PER_DAY

# 用户行为模式
MORNING_ACTIONS = ["light_on", "lock_open", "move_forward"]
EVENING_ACTIONS = ["light_off", "lock_close", "move_back"]
RANDOM_ACTIONS = [
    "nod", "shake_head", "wave_hand", "dance",
    "turn_left", "turn_right", "move_forward", "move_back",
    "light_on", "light_off", "lock_open", "lock_close",
]

# 用户偏好（模拟学习目标）
USER_PREFERENCES = {
    "verbosity": "brief",       # 用户喜欢简洁
    "favorite_device": "light-01",
    "morning_routine": ["light_on", "lock_open"],
    "evening_routine": ["light_off", "lock_close"],
}

# 纠正场景
CORRECTIONS = [
    {"query": "开灯", "wrong": "lock_open", "correct": "light_on"},
    {"query": "关门", "wrong": "light_off", "correct": "lock_close"},
    {"query": "前进", "wrong": "turn_left", "correct": "move_forward"},
]

# 关键记忆注入点（在特定轮次注入，后续测试召回）
MEMORY_INJECT_POINTS = {
    50: "用户喜欢把灯调到 50% 亮度",
    150: "用户家有一只猫叫小橘",
    300: "用户每天早上 7:30 有会议",
    500: "用户不喜欢突然的噪音",
    700: "用户的生日是 6 月 15 日",
}

# 关键记忆召回测试点
MEMORY_RECALL_TESTS = {
    100: {"query": "亮度", "expected_keyword": "50%", "description": "记忆注入后召回"},
    200: {"query": "猫", "expected_keyword": "小橘", "description": "动物记忆召回"},
    400: {"query": "会议", "expected_keyword": "7:30", "description": "日程记忆召回"},
    600: {"query": "噪音", "expected_keyword": "噪音", "description": "偏好记忆召回"},
    800: {"query": "生日", "expected_keyword": "6 月 15", "description": "个人信息召回"},
    950: {"query": "猫的名字", "expected_keyword": "小橘", "description": "远期记忆召回"},
}


# ========== 评分系统 ==========
class LifeSenseScorer:
    """生命感评分器"""

    def __init__(self):
        self.scores = defaultdict(list)
        self.details = defaultdict(list)

    def record(self, dimension: str, score: float, detail: str = ""):
        self.scores[dimension].append(score)
        if detail:
            self.details[dimension].append(detail)

    def get_avg(self, dimension: str) -> float:
        vals = self.scores.get(dimension, [])
        return sum(vals) / len(vals) if vals else 0.0

    def report(self) -> dict:
        result = {}
        for dim in self.scores:
            vals = self.scores[dim]
            result[dim] = {
                "avg": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
                "count": len(vals),
                "recent_avg": sum(vals[-20:]) / min(len(vals), 20),
            }
        return result


# ========== 模拟对话生成器 ==========
class ConversationSimulator:
    """模拟 3 天密集对话"""

    def __init__(self):
        self.scorer = LifeSenseScorer()
        self.turn_log = []
        self.day = 0
        self.turn_in_day = 0
        self.current_hour = 8  # 从早上 8 点开始

    def generate_turn(self, turn_id: int) -> dict:
        """生成一轮对话"""
        self.turn_in_day = turn_id % TURNS_PER_DAY
        self.day = turn_id // TURNS_PER_DAY

        # 模拟时间推进（每轮 ~5 分钟）
        self.current_hour = (8 + self.turn_in_day * 5 / 60) % 24

        # 根据时间选择行为
        if 7 <= self.current_hour <= 9:
            # 早上：例行操作
            action = random.choice(MORNING_ACTIONS)
            query = f"早上好，{self._action_to_chinese(action)}"
        elif 20 <= self.current_hour <= 22:
            # 晚上：关灯锁门
            action = random.choice(EVENING_ACTIONS)
            query = f"准备睡了，{self._action_to_chinese(action)}"
        else:
            # 其他时间：随机交互
            action = random.choice(RANDOM_ACTIONS)
            query = self._generate_random_query(action, turn_id)

        # 特殊轮次：注入记忆
        if turn_id in MEMORY_INJECT_POINTS:
            query = MEMORY_INJECT_POINTS[turn_id]
            action = "idle"

        # 特殊轮次：纠正（每个纠正场景各触发一次）
        correction = None
        correction_schedule = {100: 0, 250: 1, 450: 2}  # turn_id → CORRECTIONS index
        if turn_id in correction_schedule:
            c = CORRECTIONS[correction_schedule[turn_id]]
            correction = c
            query = c["query"]

        return {
            "turn_id": turn_id,
            "day": self.day,
            "hour": self.current_hour,
            "query": query,
            "expected_action": action,
            "correction": correction,
            "is_memory_inject": turn_id in MEMORY_INJECT_POINTS,
            "is_recall_test": turn_id in MEMORY_RECALL_TESTS,
            "recall_config": MEMORY_RECALL_TESTS.get(turn_id),
        }

    def _action_to_chinese(self, action: str) -> str:
        mapping = {
            "light_on": "帮我开灯", "light_off": "帮我关灯",
            "lock_open": "帮我开门", "lock_close": "帮我锁门",
            "move_forward": "往前走", "move_back": "往后退",
            "turn_left": "左转", "turn_right": "右转",
            "nod": "点点头", "shake_head": "摇摇头",
            "wave_hand": "挥挥手", "dance": "跳个舞",
        }
        return mapping.get(action, action)

    def _generate_random_query(self, action: str, turn_id: int) -> str:
        templates = [
            f"请执行 {action}",
            f"帮我{_action_to_chinese(action)}" if action in RANDOM_ACTIONS else f"执行 {action}",
            f"我想{self._action_to_chinese(action)}",
        ]
        return random.choice(templates)


def _action_to_chinese(action: str) -> str:
    mapping = {
        "light_on": "开灯", "light_off": "关灯",
        "lock_open": "开门", "lock_close": "锁门",
        "move_forward": "前进", "move_back": "后退",
        "turn_left": "左转", "turn_right": "右转",
        "nod": "点头", "shake_head": "摇头",
        "wave_hand": "挥手", "dance": "跳舞",
    }
    return mapping.get(action, action)


# ========== 主测试流程 ==========
def run_life_sense_benchmark():
    """运行 1050 轮生命感基准测试"""
    print("=" * 70)
    print("  rak-runtime 生命感长期对话基准测试")
    print(f"  模拟 {DAYS} 天 × {TURNS_PER_DAY} 轮 = {TOTAL_TURNS} 轮对话")
    print("=" * 70)
    print()

    # 初始化所有子系统
    print("[初始化] 加载认知子系统...")
    memory = CognitiveMemoryEngine()
    user_model = UserModel(persist_path="/tmp/test_user_model.json")
    emotion = EmotionEngine()
    need = NeedEngine()
    self_model = SelfModel()
    meta = MetaCognition()
    conv = ConversationState()
    world = WorldModel()
    cache = SemanticCache()
    scorer = LifeSenseScorer()
    sim = ConversationSimulator()

    # 清理持久化文件
    for f in ["/tmp/test_user_model.json"]:
        if os.path.exists(f):
            os.remove(f)

    print("[初始化] 完成，开始模拟...")
    print()

    # ========== 模拟对话 ==========
    t_start = time.time()
    recall_hits = 0
    recall_total = 0
    correction_fixes = 0
    correction_total = 0

    for turn_id in range(TOTAL_TURNS):
        turn = sim.generate_turn(turn_id)

        # ── 记忆注入 ──
        if turn["is_memory_inject"]:
            memory.remember(
                content=turn["query"],
                memory_type="semantic",
                importance=0.9,
                metadata={"source": "user", "turn": turn_id},
            )
            # 也记录到对话状态
            conv.add_user_message(turn["query"])
            conv.add_assistant_message("好的，我记住了。")

            if turn_id % 100 == 0:
                print(f"  [Day {turn['day']+1}] Turn {turn_id}: 💉 记忆注入: '{turn['query'][:40]}'")
            continue

        # ── 纠正处理 ──
        if turn["correction"]:
            c = turn["correction"]
            # 记录纠正
            user_model.record_correction(c["query"], c["wrong"], c["correct"])
            # 情绪反应
            emotion.on_failure()
            # 学习
            memory.remember(
                content=f"用户纠正: '{c['query']}' 不应该执行 {c['wrong']}，应该执行 {c['correct']}",
                memory_type="procedural",
                importance=0.95,
                metadata={"type": "correction"},
            )
            correction_total += 1

            if turn_id % 100 == 0:
                print(f"  [Day {turn['day']+1}] Turn {turn_id}: ⚠️ 纠正: '{c['query']}' → {c['correct']}")
            continue

        # ── 记忆召回测试 ──
        if turn["is_recall_test"]:
            config = turn["recall_config"]
            recall_total += 1
            results = memory.recall(config["query"])
            found = any(config["expected_keyword"] in r.entry.content for r in results)
            if found:
                recall_hits += 1
                scorer.record("memory_recall", 1.0, f"Turn {turn_id}: ✓ '{config['query']}'")
            else:
                scorer.record("memory_recall", 0.0, f"Turn {turn_id}: ✗ '{config['query']}' 期望 '{config['expected_keyword']}'")
                # 看看实际召回了什么
                if results:
                    actual = results[0].entry.content[:50]
                else:
                    actual = "无结果"

            if turn_id % 100 == 0:
                status = "✓" if found else "✗"
                print(f"  [Day {turn['day']+1}] Turn {turn_id}: 🔍 召回测试 '{config['query']}': {status}")

        # ── 正常对话轮次 ──
        # 记录到对话
        conv.add_user_message(turn["query"])

        # 记忆存储
        memory.remember(
            content=f"用户说: {turn['query']}",
            memory_type="episodic",
            importance=0.3 + random.random() * 0.3,
        )

        # 用户模型记录
        user_model.record_interaction(
            query=turn["query"],
            action=turn["expected_action"],
        )

        # 情绪更新
        if random.random() < 0.1:
            emotion.on_success()
        elif random.random() < 0.02:
            emotion.on_failure()

        # 需求更新
        success = random.random() > 0.05
        need.record_decision(success)
        if not success:
            need.record_correction()
        if random.random() < 0.3:
            need.record_cache_hit()
        else:
            need.record_cache_miss()

        # 世界模型
        device_id = f"device-{turn_id % 5}"
        world.update_device(device_id, {"online": True, "last_seen": time.time()})

        # 缓存
        cache.store(turn["query"], {"action": turn["expected_action"]},
                    RANDOM_ACTIONS + MORNING_ACTIONS + EVENING_ACTIONS)

        # 助手回复
        conv.add_assistant_message(f"执行: {turn['expected_action']}")

        # ── 定期巩固（防止工作记忆溢出丢失关键记忆）──
        if turn_id > 0 and turn_id % 20 == 0:
            memory.consolidate()

        # ── 定期评估 ──
        if turn_id > 0 and turn_id % 100 == 0:

            # 评估各项指标
            _evaluate_periodic(turn_id, memory, user_model, emotion, need,
                             self_model, conv, world, cache, scorer, sim)

        # 进度
        if turn_id > 0 and turn_id % 350 == 0:
            elapsed = time.time() - t_start
            print(f"\n  === Day {turn['day']} 完成 ({elapsed:.1f}s) ===\n")

    elapsed_total = time.time() - t_start

    # ========== 最终评估 ==========
    print()
    print("=" * 70)
    print("  最终评估")
    print("=" * 70)

    # 远期记忆召回（Day 1 注入的记忆，Day 3 测试）
    long_term_tests = [
        ("猫", "小橘", "Day 1 注入 → Day 3 召回"),
        ("亮度", "50%", "Day 1 注入 → Day 3 召回"),
        ("会议", "7:30", "Day 1 注入 → Day 3 召回"),
    ]
    lt_hits = 0
    for query, expected, desc in long_term_tests:
        results = memory.recall(query)
        found = any(expected in r.entry.content for r in results)
        if found:
            lt_hits += 1
        scorer.record("long_term_memory", 1.0 if found else 0.0,
                      f"{desc}: '{query}' → {'✓' if found else '✗'}")
        print(f"  远期记忆 [{desc}]: '{query}' → {'✓ 找到' if found else '✗ 未找到'} (期望: {expected})")

    # 纠正学习测试
    print()
    for c in CORRECTIONS:
        correction_hint = user_model.get_correction_context(c["query"])
        found = correction_hint and c["correct"] in str(correction_hint)
        if found:
            correction_fixes += 1
        scorer.record("correction_learning", 1.0 if found else 0.0,
                      f"'{c['query']}': {'✓' if found else '✗'}")
        print(f"  纠正学习: '{c['query']}' → {'✓ 记住了' if found else '✗ 未记住'} (期望: {c['correct']})")

    # 情绪状态
    print()
    emotion_state = emotion.state.to_dict()
    print(f"  最终情绪: joy={emotion_state['joy']:.2f}, stress={emotion_state['stress']:.2f}, confidence={emotion_state['confidence']:.2f}")
    scorer.record("emotion_realism", 0.5 + emotion_state["confidence"] * 0.5)

    # 需求状态
    needs = need.update()
    print(f"  最终需求: {needs.describe()[:80]}")

    # 用户画像
    profile = user_model.get_profile_summary()
    print(f"  用户画像: {profile[:100] if profile else '无'}")
    scorer.record("user_profiling", 1.0 if profile else 0.0)

    # 世界模型
    device_count = len(world._devices)
    print(f"  世界模型: {device_count} 个设备")
    scorer.record("world_model", min(1.0, device_count / 5))

    # 缓存效率
    cache_stats = cache.stats()
    print(f"  缓存: {cache_stats}")

    # 对话轮次
    print(f"\n  总轮次: {TOTAL_TURNS}, 耗时: {elapsed_total:.1f}s")
    print(f"  记忆召回: {recall_hits}/{recall_total}")
    print(f"  纠正学习: {correction_fixes}/{len(CORRECTIONS)}")
    print(f"  远期记忆: {lt_hits}/{len(long_term_tests)}")

    # ========== 综合评分 ==========
    print()
    print("=" * 70)
    print("  生命感综合评分")
    print("=" * 70)

    report = scorer.report()
    dimensions = {
        "memory_recall": ("记忆召回", 0.25),
        "long_term_memory": ("远期记忆", 0.20),
        "correction_learning": ("纠正学习", 0.15),
        "emotion_realism": ("情绪真实感", 0.15),
        "user_profiling": ("用户画像", 0.10),
        "world_model": ("世界模型", 0.10),
    }

    total_weighted = 0
    for dim, (label, weight) in dimensions.items():
        if dim in report:
            avg = report[dim]["avg"]
            total_weighted += avg * weight
            bar = "█" * int(avg * 20) + "░" * (20 - int(avg * 20))
            print(f"  {label:10s} [{bar}] {avg:.2f} (权重 {weight:.0%})")
        else:
            print(f"  {label:10s} [░░░░░░░░░░░░░░░░░░░░] N/A")

    print(f"\n  综合得分: {total_weighted:.2f} / 1.00")
    if total_weighted >= 0.8:
        print("  评级: ⭐⭐⭐⭐⭐ 优秀 — 强烈的生命感")
    elif total_weighted >= 0.6:
        print("  评级: ⭐⭐⭐⭐ 良好 — 有明显的生命感")
    elif total_weighted >= 0.4:
        print("  评级: ⭐⭐⭐ 中等 — 有一定生命感但不稳定")
    elif total_weighted >= 0.2:
        print("  评级: ⭐⭐ 较弱 — 生命感不明显")
    else:
        print("  评级: ⭐ 弱 — 像在和 API 对话")

    return {
        "total_score": total_weighted,
        "dimensions": report,
        "recall_hits": recall_hits,
        "recall_total": recall_total,
        "correction_fixes": correction_fixes,
        "lt_hits": lt_hits,
        "elapsed": elapsed_total,
    }


def _evaluate_periodic(turn_id, memory, user_model, emotion, need,
                       self_model, conv, world, cache, scorer, sim):
    """每 100 轮的定期评估"""

    # 1. 记忆系统健康度
    mem_stats = memory.get_stats() if hasattr(memory, 'get_stats') else {}
    long_term_count = mem_stats.get("long_term_count", 0)
    scorer.record("memory_health", min(1.0, long_term_count / 50),
                  f"Turn {turn_id}: {long_term_count} long-term memories")

    # 2. 对话连贯性（检查是否还在运行）
    scorer.record("continuity", 1.0 if conv else 0.0)

    # 3. 情绪动态范围
    joy = emotion.state.joy
    stress = emotion.state.stress
    dynamic_range = abs(joy - 0.5) + abs(stress - 0.0)
    scorer.record("emotion_dynamics", min(1.0, dynamic_range * 2))


if __name__ == "__main__":
    result = run_life_sense_benchmark()
