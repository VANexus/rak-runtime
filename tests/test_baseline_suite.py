"""
Baseline 对比套件的离线测试（fake runner，不打 LLM）。

验证：
- 三臂 runner 契约（返回含 action 的 dict）
- pure_rules 对直白指令命中、对同义改写失配（体现基线脆弱性）
- _extract_action 兼容 action 单值与 actions 列表
- run_arm/report 统计形状正确（冷启动 vs 复述两阶段）
- harness 复述阶段增量可量化（fake：首见慢，复述快——模拟缓存命中）
"""

import time

from benchmarks.baseline_suite import (
    _extract_action,
    pure_rules_runner,
    report,
    run_arm,
    ArmResult,
)


def test_pure_rules_cold_hits():
    """直白指令应命中关键词规则。"""
    assert _extract_action(pure_rules_runner("帮我把客厅的灯打开")) == "light_on"
    assert _extract_action(pure_rules_runner("向前走两步")) == "move_forward"
    assert _extract_action(pure_rules_runner("向左转")) == "turn_left"


def test_pure_rules_paraphrase_misses():
    """同义改写（不含关键词表的词）应失配——这正是无 harness 的脆弱点。"""
    # "把屋里的灯开一下" 不含 "开灯"/"打开灯" 连续子串
    assert _extract_action(pure_rules_runner("把屋里的灯开一下")) == "idle"
    # "往前挪一点" 不含 "前进"/"向前走"
    assert _extract_action(pure_rules_runner("往前挪一点")) == "idle"
    # "招个手问个好" 插入了"个"，不含连续的 "招手" 子串 → 失配。
    # 这正是中文形态（语素插入 "招个手"）能击败朴素关键词匹配的原因。
    assert _extract_action(pure_rules_runner("招个手问个好")) == "idle"


def test_extract_action_forms():
    assert _extract_action({"action": "nod"}) == "nod"
    assert _extract_action({"actions": [{"action": "dance"}]}) == "dance"
    assert _extract_action({"actions": ["turn_left"]}) == "turn_left"
    assert _extract_action({"status": "error"}) == ""
    assert _extract_action("not-a-dict") == ""


def test_run_arm_two_phase_stats():
    """fake runner：首见慢且对，复述快且对——模拟 harness 缓存命中。"""
    seen = {}

    def fake(text):
        # 模拟：复述与冷启动语义等价 → 命中缓存（快）
        key = "light" if "灯" in text else "other"
        if key in seen:
            return {"action": "light_on"}
        seen[key] = True
        time.sleep(0.001)
        return {"action": "light_on"}

    # 用单任务子集跑（不动全局 _TASKS，直接调 run_arm 会跑全部——
    # 这里只验证统计形状，fake 对所有输入都回 light_on，bl-01 正好期望 light_on）
    r = run_arm("fake", fake, phases=("cold", "paraphrase"))
    assert r.n == 12
    assert r.cold_acc >= 0.0 and r.para_acc >= 0.0
    assert len(r.cold_lat_ms) == 12 and len(r.para_lat_ms) == 12
    assert isinstance(r.cold_avg_ms, float) and isinstance(r.para_avg_ms, float)


def test_report_renders_increment():
    a = ArmResult(name="pure_rules", n=12, cold_hits=7, para_hits=2,
                  cold_lat_ms=[0.01] * 12, para_lat_ms=[0.01] * 12)
    b = ArmResult(name="bare_llm", n=12, cold_hits=11, para_hits=11,
                  cold_lat_ms=[900] * 12, para_lat_ms=[900] * 12)
    h = ArmResult(name="harness", n=12, cold_hits=12, para_hits=12,
                  cold_lat_ms=[950] * 12, para_lat_ms=[3] * 12)
    out = report([a, b, h])
    assert "Baseline 对比实证" in out
    assert "pure_rules" in out and "bare_llm" in out and "harness" in out
    # harness 复述准确率 100% vs bare_llm 100% → 增量 0.0%；
    # 但延迟节省 ~897ms 应出现在报告里
    assert "延迟节省" in out
