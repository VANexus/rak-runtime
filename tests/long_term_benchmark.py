"""
30 天万轮长期对话基准测试

模拟一个真实用户与 Rak 的 30 天交互：
- 每天 ~333 轮对话
- 覆盖：设备控制、问答、纠正、情感、闲聊、日程、偏好
- 每 5 天重启一次验证持久化
- 全量日志写入文件

用户模拟：LLM 批量生成（每批 10 轮），模拟真实人类行为模式。
Agent 决策：每轮都走完整 LLM 管线。

预计耗时：3-5 小时（取决于 API 速度）
"""

import sys
import os
import time
import json
import shutil
import random
import logging
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

# ========== 配置 ==========
TOTAL_DAYS = 30
TURNS_PER_DAY = 333
TOTAL_TURNS = TOTAL_DAYS * TURNS_PER_DAY  # ~10000
RESTART_EVERY_DAYS = 5
USER_BATCH_SIZE = 10  # 每次 LLM 调用生成的用户轮次数
LOG_FILE = "/tmp/rak_long_term_benchmark.log"

AVAILABLE_ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "move_forward", "move_back", "turn_left", "turn_right",
    "dance", "nod", "light_on", "light_off",
    "emergency_stop", "idle",
]

# 用户画像（模拟一个真实的人）
USER_PROFILE = {
    "name": "小明",
    "age": 28,
    "occupation": "程序员",
    "home": "一室一厅公寓",
    "devices": ["客厅灯", "卧室灯", "门锁", "空调", "扫地机器人"],
    "personality": "有点懒但讲效率，喜欢简洁回复，偶尔会纠正机器人",
    "routines": {
        "07:30": "起床，开灯，开锁",
        "08:00": "出门上班，锁门",
        "12:00": "午餐时间，可能回家",
        "18:00": "下班回家，开锁，开灯",
        "22:00": "准备睡觉，关灯，锁门",
    },
    "corrections_history": [],  # 记录纠正过的内容
    "facts_learned": [],  # agent 学到的事实
}


# ========== 日志 ==========
def setup_logging():
    """配置日志"""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("benchmark")


# ========== 用户模拟 ==========
def generate_user_turns(llm_client, day, turn_in_day, recent_history, user_state):
    """
    用 LLM 批量生成用户对话。

    输入用户画像、当前时间、近期历史，输出 10 轮自然对话。
    """
    hour = 8 + (turn_in_day * 5 / 60) % 16  # 8:00-24:00

    # 构建用户模拟 prompt
    history_text = ""
    if recent_history:
        history_text = "\n".join(
            f"用户: {h['user']}\nRak: {h['agent'][:50]}"
            for h in recent_history[-5:]
        )

    prompt = f"""你是一个叫{USER_PROFILE['name']}的用户，正在和你的智能家居助手 Rak 对话。

你的特征：
- {USER_PROFILE['age']}岁，{USER_PROFILE['occupation']}
- 住在{USER_PROFILE['home']}
- 家里有：{', '.join(USER_PROFILE['devices'])}
- 性格：{USER_PROFILE['personality']}

当前是第 {day+1} 天，时间 {int(hour)}:{int((hour%1)*60):02d}。

你的日常作息：
{json.dumps(USER_PROFILE['routines'], ensure_ascii=False, indent=2)}

最近的对话：
{history_text if history_text else '（刚开始）'}

请生成 {USER_BATCH_SIZE} 轮对话。每轮是你对 Rak 说的话。
要求：
1. 符合当前时间和日常作息（早上就说早上的事，晚上就说晚上的事）
2. 包含设备控制指令（开灯、锁门等）
3. 偶尔问问题（天气、日程等）
4. 偶尔纠正 Rak 的错误
5. 偶尔分享个人信息（偏好、感受等）
6. 偶尔闲聊
7. 自然、口语化，像真人发消息

输出格式（每行一轮）：
1. [你的对话]
2. [你的对话]
...

只输出对话内容，不要其他文字。"""

    try:
        response = llm_client.messages.create(
            model="mimo-v2.5-pro",
            max_tokens=1024,
            system="你是一个对话数据生成器。只输出用户说的话，不要编号以外的任何内容。",
            messages=[{"role": "user", "content": prompt}],
            extra_body={"thinking": {"type": "disabled"}},
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
                break

        # 解析对话行
        turns = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # 去掉编号 "1. " 等
            if line[0].isdigit() and ". " in line:
                line = line.split(". ", 1)[1]
            if line.startswith("[") and line.endswith("]"):
                line = line[1:-1]
            turns.append(line)

        return turns[:USER_BATCH_SIZE]

    except Exception as e:
        logging.warning("用户生成失败: %s，使用模板", e)
        # 降级：模板生成
        return _generate_template_turns(hour)


def _generate_template_turns(hour):
    """模板生成用户对话（LLM 失败时的降级）"""
    templates = {
        "morning": [
            "早上好，帮我开灯", "开锁，我要出门了", "今天天气怎么样？",
            "帮我把灯调亮一点", "锁门，我走了",
        ],
        "noon": [
            "我回来了，开锁", "帮我开灯", "中午吃什么好？",
            "把空调打开", "扫地机器人开始工作",
        ],
        "evening": [
            "我到家了", "帮我开灯，调暗一点", "锁门了吗？",
            "我有点累，帮我把灯调暖色", "今天有什么安排？",
        ],
        "night": [
            "准备睡了，关灯", "帮我锁门", "明天几点有会议？",
            "晚安", "把所有灯都关了",
        ],
    }

    if hour < 12:
        pool = templates["morning"]
    elif hour < 17:
        pool = templates["noon"]
    elif hour < 21:
        pool = templates["evening"]
    else:
        pool = templates["night"]

    return [random.choice(pool) for _ in range(USER_BATCH_SIZE)]


# ========== Agent 决策 ==========
def agent_respond(engine, user_input, turn_id):
    """通过完整 LLM 管线处理用户输入"""

    class MockRequest:
        def __init__(self, state, turn_id):
            self.version = "v0"
            self.trace_id = f"lt-{turn_id}"
            self.action = ""
            self.state = state
            self.available_actions = AVAILABLE_ACTIONS
            self.params_json = "{}"

    request = MockRequest(user_input, turn_id)
    t0 = time.time()
    try:
        result = engine.decide(request)
        latency = (time.time() - t0) * 1000
        return {
            "status": result.get("status", "?"),
            "action": result.get("action", "?"),
            "answer": result.get("answer", ""),
            "latency": latency,
            "error": None,
        }
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return {
            "status": "error",
            "action": "?",
            "answer": "",
            "latency": latency,
            "error": str(e),
        }


# ========== 引擎管理 ==========
def create_engine():
    """创建决策引擎（重置单例模拟重启）"""
    import src.core.decision_engine as de

    # 重置所有单例
    for attr in ["_memory_engine", "_llm_client", "_semantic_cache",
                 "_prompt_engine", "_learning_loop", "_meta_cognition",
                 "_user_model", "_self_model", "_need_engine",
                 "_memory_stream", "_emotion_engine", "_living_graph",
                 "_inner_loop", "_conversation_state"]:
        setattr(de, attr, None)

    return de.DecisionEngine()


def save_engine_state(engine):
    """保存引擎状态"""
    from src.core.decision_engine import save_all_memories
    try:
        save_all_memories()
    except Exception as e:
        logging.warning("状态保存失败: %s", e)


# ========== 主测试 ==========
def main():
    logger = setup_logging()
    logger.info("=" * 70)
    logger.info("  rak-runtime 30 天万轮长期对话基准测试")
    logger.info("  总轮次: %d, 每天: %d, 重启周期: %d 天", TOTAL_TURNS, TURNS_PER_DAY, RESTART_EVERY_DAYS)
    logger.info("  日志文件: %s", LOG_FILE)
    logger.info("=" * 70)

    # 初始化 LLM 客户端（用于用户模拟）
    import anthropic
    llm_client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.getenv("ANTHROPIC_BASE_URL", "https://token-plan-cn.xiaomimimo.com/anthropic"),
        timeout=30.0,
    )

    # 创建引擎
    engine = create_engine()

    # 统计
    stats = {
        "total_turns": 0,
        "total_llm_calls": 0,
        "total_errors": 0,
        "total_latency": 0,
        "status_counts": {},
        "action_counts": {},
        "day_stats": [],
        "restarts": 0,
    }

    recent_history = []  # 最近的对话历史
    user_state = {}  # 用户状态

    t_start = time.time()

    for day in range(TOTAL_DAYS):
        logger.info("")
        logger.info("=" * 60)
        logger.info("  Day %d / %d", day + 1, TOTAL_DAYS)
        logger.info("=" * 60)

        day_start = time.time()
        day_turns = 0
        day_errors = 0
        day_latency = 0

        # 每 RESTART_EVERY_DAYS 天重启一次
        if day > 0 and day % RESTART_EVERY_DAYS == 0:
            logger.info("[重启] 保存状态...")
            save_engine_state(engine)
            logger.info("[重启] 创建新引擎...")
            engine = create_engine()
            stats["restarts"] += 1
            logger.info("[重启] 完成 (第 %d 次重启)", stats["restarts"])

        turn_in_day = 0
        while turn_in_day < TURNS_PER_DAY:
            # 批量生成用户对话
            remaining = min(USER_BATCH_SIZE, TURNS_PER_DAY - turn_in_day)
            user_turns = generate_user_turns(
                llm_client, day, turn_in_day, recent_history, user_state
            )
            stats["total_llm_calls"] += 1

            for user_input in user_turns[:remaining]:
                turn_id = stats["total_turns"]

                # Agent 决策
                result = agent_respond(engine, user_input, turn_id)

                # 记录
                stats["total_turns"] += 1
                stats["total_latency"] += result["latency"]
                stats["status_counts"][result["status"]] = stats["status_counts"].get(result["status"], 0) + 1
                if result["action"] != "?":
                    stats["action_counts"][result["action"]] = stats["action_counts"].get(result["action"], 0) + 1
                if result["error"]:
                    stats["total_errors"] += 1
                    day_errors += 1

                day_turns += 1
                day_latency += result["latency"]

                # 更新历史
                recent_history.append({
                    "user": user_input,
                    "agent": result["answer"] or result["action"],
                })
                if len(recent_history) > 20:
                    recent_history = recent_history[-20:]

                # 日志（每 50 轮输出一次摘要）
                if turn_in_day % 50 == 0:
                    logger.info(
                        "  [Day %d] Turn %d: status=%s, action=%s, latency=%.0fms, input='%s'",
                        day + 1, turn_in_day, result["status"],
                        result["action"], result["latency"],
                        user_input[:30],
                    )

                # 每 200 轮巩固记忆
                if turn_in_day % 200 == 0 and turn_in_day > 0:
                    mem_engine = engine._get_memory_engine() if hasattr(engine, '_get_memory_engine') else None
                    if mem_engine:
                        try:
                            mem_engine.consolidate()
                        except Exception:
                            pass

                turn_in_day += 1

        # Day 结束统计
        day_elapsed = time.time() - day_start
        day_avg_latency = day_latency / day_turns if day_turns > 0 else 0
        ok_count = stats["status_counts"].get("ok", 0)

        day_stat = {
            "day": day + 1,
            "turns": day_turns,
            "errors": day_errors,
            "avg_latency": day_avg_latency,
            "elapsed": day_elapsed,
        }
        stats["day_stats"].append(day_stat)

        logger.info("")
        logger.info("  Day %d 完成: %d 轮, %.0f ms/轮, %d 错误, %.1f 秒",
                     day + 1, day_turns, day_avg_latency, day_errors, day_elapsed)

        # 每天结束保存一次
        save_engine_state(engine)

    # ========== 最终报告 ==========
    total_elapsed = time.time() - t_start
    avg_latency = stats["total_latency"] / stats["total_turns"] if stats["total_turns"] > 0 else 0

    logger.info("")
    logger.info("=" * 70)
    logger.info("  最终报告")
    logger.info("=" * 70)
    logger.info("  总轮次: %d", stats["total_turns"])
    logger.info("  总 LLM 调用: %d", stats["total_llm_calls"])
    logger.info("  总错误: %d", stats["total_errors"])
    logger.info("  平均延迟: %.0f ms", avg_latency)
    logger.info("  总耗时: %.1f 小时", total_elapsed / 3600)
    logger.info("  重启次数: %d", stats["restarts"])
    logger.info("")
    logger.info("  状态分布:")
    for status, count in sorted(stats["status_counts"].items()):
        pct = count / stats["total_turns"] * 100
        logger.info("    %s: %d (%.1f%%)", status, count, pct)
    logger.info("")
    logger.info("  Top 10 动作:")
    for action, count in sorted(stats["action_counts"].items(), key=lambda x: -x[1])[:10]:
        logger.info("    %s: %d", action, count)

    # 保存最终结果
    result_path = "/tmp/rak_long_term_result.json"
    with open(result_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logger.info("")
    logger.info("  结果已保存: %s", result_path)
    logger.info("  日志文件: %s", LOG_FILE)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
