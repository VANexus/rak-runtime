"""
Baseline 对比套件 — 量化 harness 相对"裸 LLM / 纯规则"基线的增量。

三臂（同一任务集，唯一变量是决策路径）：
- arm A  pure_rules  纯规则基线：关键词映射，零 LLM。
                      代表"没有 harness 时最朴素的做法"。
- arm B  bare_llm     裸单发 LLM 基线：一次 _llm_decide，极简提示词，
                      无记忆 / 无缓存 / 无 CogRec / 无用户画像 / 无规则学习。
                      代表"裸 LLM（Claude Code 单发风格）"。
- arm C  harness      完整 harness：run_brain → DecisionEngine 全链路
                      （语义缓存→CogRec→ActionMemory→记忆注入→LLM→学习闭环）。

两阶段（量化增量来源）：
- cold    冷启动：全新指令，三臂都付全价。比准确率 + 首延迟。
- paraphrase 复述/改写：同一意图换个说法再来。
           harness 应命中语义缓存 / CogRec（<10ms）；
           bare_llm 仍付全价；纯规则因同义词不在关键词表而失败。
           这就是 harness 的"可复用学习增量"。

运行（活体，真实 LLM）：
    RAK_LIVE_TESTS=1 python -m src.harness.baseline
输出：三臂 × 两阶段 的命中率 / 延迟 / 增量对比表 + JSON 落盘。
"""

import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 14 动作 MVP 集
DEFAULT_ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "move_forward", "move_back", "turn_left", "turn_right",
    "dance", "nod", "light_on", "light_off",
    "emergency_stop", "idle",
]

# ─────────────────────────────────────────────────────────────────────────────
# 任务集：每条 = (task_id, 冷启动指令, 复述/改写指令, 期望动作)
# 复述版刻意换同义词 / 换句式，使纯关键词规则失配，但语义等价的缓存能命中。
# ─────────────────────────────────────────────────────────────────────────────
_TASKS = [
    ("bl-01", "帮我把客厅的灯打开",       "把屋里的灯开一下",         "light_on"),
    ("bl-02", "我要睡了，把灯关掉",       "睡觉了，灯灭了吧",         "light_off"),
    ("bl-03", "把门打开让我进来",         "让我进屋，把门开开",         "lock_open"),
    ("bl-04", "出门了，帮我把门锁上",     "我要走了，把门关死",         "lock_close"),
    ("bl-05", "向前走两步",               "往前挪一点",               "move_forward"),
    ("bl-06", "往后退一点，太近了",       "退后一些",                 "move_back"),
    ("bl-07", "向左转",                   "往左边转一下",             "turn_left"),
    ("bl-08", "向右转一下",               "往右偏一点",               "turn_right"),
    ("bl-09", "跟我打个招呼，挥挥手",     "招个手问个好",             "wave_hand"),
    ("bl-10", "摇摇头表示不同意",         "摆摆头，不赞同",           "shake_head"),
    ("bl-11", "跳个舞吧",                 "来一段舞蹈",               "dance"),
    ("bl-12", "点个头表示同意",           "颔首一下，可以",           "nod"),
]


# ─────────────────────────────────────────────────────────────────────────────
# arm A: 纯规则基线（关键词映射）
# ─────────────────────────────────────────────────────────────────────────────
# 刻意保持朴素：一对一关键词表，不含同义词扩展。这正是"没有 harness"的样子——
# 复述/改写（"把屋里的灯开一下"不含"打开"）就会失配。
_RULE_TABLE = [
    ("打开", "light_on"), ("开灯", "light_on"), ("灯打开", "light_on"),
    ("关掉", "light_off"), ("关灯", "light_off"), ("灯关", "light_off"),
    ("开门", "lock_open"), ("门打开", "lock_open"), ("打开门", "lock_open"),
    ("锁门", "lock_close"), ("锁上", "lock_close"),
    ("前进", "move_forward"), ("向前走", "move_forward"), ("向前", "move_forward"),
    ("后退", "move_back"), ("往后退", "move_back"),
    ("左转", "turn_left"), ("向左转", "turn_left"), ("向左", "turn_left"),
    ("右转", "turn_right"), ("向右转", "turn_right"), ("向右", "turn_right"),
    ("挥手", "wave_hand"), ("招手", "wave_hand"),
    ("摇头", "shake_head"),
    ("点头", "nod"),
    ("跳舞", "dance"),
    ("紧急停止", "emergency_stop"), ("停止", "emergency_stop"),
]


def pure_rules_runner(text: str, available_actions=None) -> dict:
    """纯关键词规则：匹配到即返回该动作，否则 idle。"""
    actions = available_actions or DEFAULT_ACTIONS
    for kw, act in _RULE_TABLE:
        if kw in text and act in actions:
            return {"status": "ok", "action": act, "params_json": "{}", "source": "rule"}
    return {"status": "ok", "action": "idle", "params_json": "{}", "source": "rule"}


# ─────────────────────────────────────────────────────────────────────────────
# arm B: 裸单发 LLM 基线（无 harness 任何增强）
# ─────────────────────────────────────────────────────────────────────────────
_BARE_PROMPT = """你是一个嵌入式设备决策引擎。根据用户的话，从可用动作中选一个最合适的动作。

## 可用动作
{actions}

## 输出格式
只返回 JSON，不要任何多余文字：{{"action": "动作名"}}"""


def bare_llm_runner(text: str, available_actions=None) -> dict:
    """
    裸单发 LLM：一次 _llm_decide，极简提示词。
    无记忆注入、无缓存、无 CogRec、无用户画像、无学习闭环。
    这就是"裸 LLM"的决策质量与延迟。
    """
    from src.core.decision_engine import _llm_decide
    actions = available_actions or DEFAULT_ACTIONS
    prompt = _BARE_PROMPT.format(actions="\n".join(f"- {a}" for a in actions))
    res = _llm_decide(prompt, f"用户说: {text}")
    if not res:
        return {"status": "ok", "action": "idle", "params_json": "{}", "source": "bare_llm_fallback"}
    act = res.get("action", "idle")
    if act not in actions:
        act = "idle"
    return {"status": "ok", "action": act, "params_json": "{}", "source": "bare_llm"}


# ─────────────────────────────────────────────────────────────────────────────
# arm C: 完整 harness
# ─────────────────────────────────────────────────────────────────────────────
def harness_runner(text: str, available_actions=None) -> dict:
    from src.harness.brain import run_brain
    return run_brain(text, trace_id="baseline-harness", available_actions=available_actions)


# ─────────────────────────────────────────────────────────────────────────────
# 实验驱动
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ArmResult:
    name: str
    cold_hits: int = 0
    para_hits: int = 0
    cold_lat_ms: List[float] = field(default_factory=list)
    para_lat_ms: List[float] = field(default_factory=list)
    n: int = 0

    @property
    def cold_acc(self) -> float:
        return self.cold_hits / self.n if self.n else 0.0

    @property
    def para_acc(self) -> float:
        return self.para_hits / self.n if self.n else 0.0

    @property
    def cold_avg_ms(self) -> float:
        return sum(self.cold_lat_ms) / len(self.cold_lat_ms) if self.cold_lat_ms else 0.0

    @property
    def para_avg_ms(self) -> float:
        return sum(self.para_lat_ms) / len(self.para_lat_ms) if self.para_lat_ms else 0.0


def _extract_action(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    if result.get("action"):
        return result["action"]
    acts = result.get("actions") or []
    if acts:
        first = acts[0]
        return first.get("action", "") if isinstance(first, dict) else str(first)
    return ""


def run_arm(name: str, runner: Callable, phases=("cold", "paraphrase")) -> ArmResult:
    r = ArmResult(name=name, n=len(_TASKS))
    for i, (tid, cold_in, para_in, expected) in enumerate(_TASKS, start=1):
        # 渐进进度日志：长活体跑需要可见性（上次盲等数分钟零信号）
        if "cold" in phases:
            t0 = time.perf_counter()
            res = runner(cold_in)
            lat = (time.perf_counter() - t0) * 1000
            r.cold_lat_ms.append(lat)
            ok = _extract_action(res) == expected
            if ok:
                r.cold_hits += 1
            logger.info("[%s] cold %d/%d %-6s %-13s->%-13s %.0fms",
                        name, i, len(_TASKS), "PASS" if ok else "FAIL",
                        "(期望)" + expected, res.get("action", "?"), lat)
        if "paraphrase" in phases:
            t0 = time.perf_counter()
            res = runner(para_in)
            lat = (time.perf_counter() - t0) * 1000
            r.para_lat_ms.append(lat)
            ok = _extract_action(res) == expected
            if ok:
                r.para_hits += 1
            logger.info("[%s] para %d/%d %-6s %-18s->%-13s %.0fms",
                        name, i, len(_TASKS), "PASS" if ok else "FAIL",
                        "(" + para_in + ")", res.get("action", "?"), lat)
    return r


def _pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def _ms(x: float) -> str:
    return f"{x:8.1f}"


def report(results: List[ArmResult]) -> str:
    lines = []
    lines.append("=" * 86)
    lines.append("Baseline 对比实证 — harness vs 裸 LLM vs 纯规则（LongCat-2.0 活体）")
    lines.append("说明: cold=冷启动新指令  paraphrase=同义改写(测可复用学习)  增量=harness-基线")
    lines.append("-" * 86)
    lines.append(f"{'决策路径':<22}{'cold 准确率':>12}{'para 准确率':>12}"
                 f"{'cold 延迟ms':>13}{'para 延迟ms':>13}")
    lines.append("-" * 86)
    for r in results:
        lines.append(f"{r.name:<22}{_pct(r.cold_acc):>12}{_pct(r.para_acc):>12}"
                     f"{_ms(r.cold_avg_ms):>13}{_ms(r.para_avg_ms):>13}")
    lines.append("-" * 86)

    by = {r.name: r for r in results}
    h = by.get("harness")
    if h:
        for base in ("bare_llm", "pure_rules"):
            b = by.get(base)
            if not b:
                continue
            d_acc = h.para_acc - b.para_acc
            d_lat = b.para_avg_ms - h.para_avg_ms
            lines.append(f"harness 对 {base:<10}: para 准确率增量 {_pct(d_acc)}  "
                         f"para 延迟节省 {_ms(d_lat)}ms")
    lines.append("=" * 86)
    return "\n".join(lines)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("[Baseline] 任务数=%d 手臂=%s", len(_TASKS), "pure_rules/bare_llm/harness")

    # 数据隔离：指向独立临时目录，避免读写线上 data/ 的缓存/规则。
    # 每臂用独立子目录，保证纯规则臂不被 harness 臂学到的缓存污染，且
    # harness 臂从"冷"开始，复述阶段的命中确实来自当次学习。
    tmp_root = tempfile.mkdtemp(prefix="rak-baseline-")
    os.environ["RAK_DATA_DIR"] = os.path.join(tmp_root, "harness_data")

    logger.info("[Baseline] 数据隔离目录: %s", tmp_root)

    results: List[ArmResult] = []

    # arm A: 纯规则（无状态，无 LLM）——先跑，便宜
    results.append(run_arm("pure_rules", pure_rules_runner))

    # arm B: 裸单发 LLM（无 harness 增强）
    results.append(run_arm("bare_llm", bare_llm_runner))

    # arm C: 完整 harness（独立数据目录，从冷开始）
    results.append(run_arm("harness", harness_runner))

    out = report(results)
    print(out)

    # 落盘 JSON
    payload = {
        "data_dir": tmp_root,
        "tasks": len(_TASKS),
        "arms": [
            {
                "name": r.name,
                "cold_acc": round(r.cold_acc, 4),
                "para_acc": round(r.para_acc, 4),
                "cold_avg_ms": round(r.cold_avg_ms, 2),
                "para_avg_ms": round(r.para_avg_ms, 2),
                "cold_hits": r.cold_hits,
                "para_hits": r.para_hits,
                "n": r.n,
            }
            for r in results
        ],
    }
    out_json = os.path.join(tmp_root, "baseline_report.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[Baseline] JSON 报告: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
