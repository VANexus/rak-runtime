"""
基准测试基础设施单元测试 - 全部离线（fake runner / 临时记忆库），不触网。

覆盖：
- 三个套件的任务字段校验（期望值是已知动作或非空）
- run_suite 产出结构 / score_suite 计算（全对=1.0，半错=0.5，加权）
- report 文本含 PASS 与任务 id；json 可解析
- compare 基线对比表产出 delta
- run_brain_single_shot 的 RAK_AGENT 环境变量切换与恢复
- memory_runner 临时库播种与跨会话召回
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness.benchmark import (  # noqa: E402
  AVAILABLE_ACTIONS,
  BenchmarkTask,
  TaskSuite,
  compare,
  report,
  run_brain_single_shot,
  run_suite,
  score_suite,
)
from benchmarks.decision_suite import build_suite as build_decision_suite  # noqa: E402
from benchmarks.memory_suite import (  # noqa: E402
  SEED_FACTS,
  build_suite as build_memory_suite,
  memory_runner,
)
from benchmarks.workflow_suite import build_suite as build_workflow_suite  # noqa: E402


# ========== fake runner（离线，不触网） ==========

def _fake_runner_by_text(mapping):
  """按输入文本返回预置结果的 fake runner。"""
  def _run(text):
    return mapping.get(text, {"status": "ok", "action": "idle", "answer": ""})
  return _run


def _fake_action_runner(action):
  """永远返回同一动作的 fake runner。"""
  return lambda text: {"status": "ok", "action": action, "answer": ""}


# ========== 任务校验 ==========

class TestSuiteValidation:
  def test_decision_suite_tasks_valid(self):
    suite = build_decision_suite()
    assert len(suite.tasks) == 13
    ids = set()
    for t in suite.tasks:
      for field_name in ("task_id", "description", "input", "expected", "category"):
        assert getattr(t, field_name), f"{t.task_id} 字段 {field_name} 为空"
      assert t.category == "decision"
      assert t.task_id not in ids
      ids.add(t.task_id)
      # 单动作套件：期望必须是 14 动作之一
      assert t.expected in AVAILABLE_ACTIONS

  def test_memory_suite_tasks_valid(self):
    suite = build_memory_suite()
    assert len(suite.tasks) == 8
    for t in suite.tasks:
      assert t.task_id and t.description and t.input
      assert t.expected  # 期望子串非空
      assert t.category == "memory"
      # 期望必须是某条种子事实的子串（保证可命中）
      assert any(t.expected in fact for fact in SEED_FACTS), t.expected

  def test_workflow_suite_tasks_valid(self):
    suite = build_workflow_suite()
    assert len(suite.tasks) == 8
    for t in suite.tasks:
      assert t.task_id and t.description and t.input
      assert t.category == "workflow"
      parts = [p for p in t.expected.split("|") if p]
      assert len(parts) >= 2, "复合指令应期望至少两个动作"
      assert all(p in AVAILABLE_ACTIONS for p in parts)

  def test_seed_facts_count(self):
    assert len(SEED_FACTS) == 8


# ========== run_suite 结构与打分 ==========

class TestRunSuite:
  def _small_suite(self):
    return TaskSuite(
      name="mini",
      description="打分用小套件",
      tasks=[
        BenchmarkTask("t1", "任务1", "开灯", "light_on", "decision"),
        BenchmarkTask("t2", "任务2", "锁门", "lock_close", "decision"),
      ],
    )

  def test_outcome_fields(self):
    suite = self._small_suite()
    result = run_suite(suite, runner=_fake_action_runner("light_on"))
    assert result.suite_name == "mini"
    assert len(result.results) == 2
    for r in result.results:
      for key in ("task_id", "status", "action", "answer", "expected",
                  "latency_ms", "matched", "tool_events"):
        assert key in r

  def test_all_ok_scores_1(self):
    suite = self._small_suite()
    runner = _fake_runner_by_text({
      "开灯": {"status": "ok", "action": "light_on"},
      "锁门": {"status": "ok", "action": "lock_close"},
    })
    scores = score_suite(run_suite(suite, runner=runner))
    assert scores["overall"] == 1.0
    assert scores["count"] == {"ok": 2, "total": 2}

  def test_half_fail_scores_05(self):
    suite = self._small_suite()
    # 两个任务都返回 light_on：t1 命中，t2 失败 -> 1/2
    scores = score_suite(run_suite(suite, runner=_fake_action_runner("light_on")))
    assert scores["overall"] == 0.5
    assert scores["count"] == {"ok": 1, "total": 2}

  def test_weighted_score(self):
    suite = TaskSuite(
      name="w",
      tasks=[
        BenchmarkTask("t1", "重", "开灯", "light_on", "decision", [], 3.0),
        BenchmarkTask("t2", "轻", "锁门", "lock_close", "decision", [], 1.0),
      ],
    )
    # 重任务失败、轻任务命中 -> 1/(3+1) = 0.25
    runner = _fake_runner_by_text({
      "开灯": {"status": "ok", "action": "lock_close"},
      "锁门": {"status": "ok", "action": "lock_close"},
    })
    scores = score_suite(run_suite(suite, runner=runner))
    assert scores["overall"] == 0.25

  def test_per_category_scores(self):
    suite = TaskSuite(
      name="cat",
      tasks=[
        BenchmarkTask("t1", "d1", "开灯", "light_on", "decision"),
        BenchmarkTask("t2", "d2", "锁门", "lock_close", "decision"),
        BenchmarkTask("t3", "w1", "复合", "light_off", "workflow"),
      ],
    )
    runner = _fake_runner_by_text({
      "开灯": {"status": "ok", "action": "light_on"},
      "锁门": {"status": "ok", "action": "light_on"},  # 失败
      "复合": {"status": "ok", "actions": ["light_off", "nod"]},
    })
    scores = score_suite(run_suite(suite, runner=runner))
    assert scores["per_category"]["decision"] == 0.5
    assert scores["per_category"]["workflow"] == 1.0

  def test_runner_exception_degrades_to_fail(self):
    def _boom(text):
      raise RuntimeError("模拟 runner 崩溃")

    suite = self._small_suite()
    result = run_suite(suite, runner=_boom)  # 不应抛异常
    scores = score_suite(result)
    assert scores["count"] == {"ok": 0, "total": 2}
    assert all(r["status"] == "fail" and r["error"] for r in result.results)

  def test_latency_and_tool_events_recorded(self):
    suite = TaskSuite(
      name="tools",
      tasks=[BenchmarkTask("t1", "d", "开灯", "light_on", "decision")],
    )
    runner = lambda text: {"status": "ok", "action": "light_on",
                           "answer": "", "trace": ["llm->search_memory", "tool:search_memory"]}
    result = run_suite(suite, runner=runner)
    assert result.results[0]["tool_events"] == 2
    assert result.results[0]["latency_ms"] >= 0
    scores = score_suite(result)
    assert scores["avg_tool_events"] == 2
    assert scores["tool_efficiency"] == pytest.approx(1 / 3, abs=1e-3)


# ========== 报告 ==========

class TestReport:
  def _result(self):
    suite = TaskSuite(
      name="mini",
      description="报告用小套件",
      tasks=[
        BenchmarkTask("dec-01", "d1", "开灯", "light_on", "decision"),
        BenchmarkTask("dec-02", "d2", "锁门", "lock_close", "decision"),
      ],
    )
    runner = _fake_action_runner("light_on")  # 第二个任务失败
    return run_suite(suite, runner=runner)

  def test_text_report_contains_pass_and_task_ids(self):
    text = report(self._result(), fmt="text")
    assert "PASS" in text and "FAIL" in text
    assert "dec-01" in text and "dec-02" in text
    assert "mini" in text
    assert "总体得分" in text

  def test_json_report_parsable(self):
    raw = report(self._result(), fmt="json")
    payload = json.loads(raw)
    assert payload["suite"] == "mini"
    assert payload["scores"]["overall"] == 0.5
    assert len(payload["results"]) == 2
    assert payload["results"][0]["task_id"] == "dec-01"


# ========== 基线对比 ==========

class TestCompare:
  def test_compare_produces_delta_table(self):
    suite = TaskSuite(
      name="cmp-suite",
      tasks=[
        BenchmarkTask("t1", "d1", "开灯", "light_on", "decision"),
        BenchmarkTask("t2", "d2", "锁门", "lock_close", "decision"),
      ],
    )
    # 基线只对一半，agent 内核全对 -> overall 差值 +0.5
    res_a = run_suite(suite, runner=_fake_action_runner("light_on"))
    res_b = run_suite(suite, runner=_fake_runner_by_text({
      "开灯": {"status": "ok", "action": "light_on"},
      "锁门": {"status": "ok", "action": "lock_close"},
    }))
    table = compare("cmp-suite", res_a, res_b)
    assert "cmp-suite" in table
    assert "overall" in table and "delta" in table
    assert "+0.5" in table  # 0.5 -> 1.0 的差值
    assert "avg_latency_ms" in table

  def test_compare_latency_delta(self):
    suite = TaskSuite(
      name="lat",
      tasks=[BenchmarkTask("t1", "d", "开灯", "light_on", "decision")],
    )
    res_a = run_suite(suite, runner=_fake_action_runner("light_on"))
    res_b = run_suite(suite, runner=_fake_action_runner("light_on"))
    table = compare("lat", res_a, res_b)
    assert "0.0000" in table  # overall 差值为 0


# ========== 单发基线 runner ==========

class TestSingleShotRunner:
  def test_env_toggled_and_restored(self, monkeypatch):
    seen = {}

    def _fake_brain(text, trace_id="harness", **kwargs):
      seen["agent"] = os.environ.get("RAK_AGENT")
      return {"status": "ok", "action": "idle", "answer": ""}

    monkeypatch.setattr("src.harness.brain.run_brain", _fake_brain)

    # 原环境无 RAK_AGENT：调用中为 "0"，调用后应被移除
    monkeypatch.delenv("RAK_AGENT", raising=False)
    run_brain_single_shot("测试")
    assert seen["agent"] == "0"
    assert "RAK_AGENT" not in os.environ

    # 原环境有 RAK_AGENT=1：调用后应恢复为 "1"
    monkeypatch.setenv("RAK_AGENT", "1")
    run_brain_single_shot("测试")
    assert seen["agent"] == "0"
    assert os.environ["RAK_AGENT"] == "1"


# ========== 跨会话记忆 runner ==========

class TestMemoryRunner:
  def test_seeds_and_recalls_from_temp_db(self, tmp_path):
    db = str(tmp_path / "super_long.db")
    result = memory_runner("早上 开灯 的 习惯", db_path=db)
    assert result["status"] == "ok"
    assert "早上 7 点开灯" in result["answer"]
    assert result["hits"], "应有召回命中"

  def test_cross_session_persistence(self, tmp_path):
    """会话 1 播种后关闭连接，会话 2 新开连接仍能召回。"""
    from src.core.memory_longterm import SuperMemory

    db = str(tmp_path / "cross.db")
    # 会话 1：播种后关闭
    session1 = SuperMemory(db_path=db)
    session1.remember("用户每天早上 7 点开灯", "semantic", scope="bench",
                      importance=0.8)
    session1.close()
    # 会话 2：新连接（模拟进程重启）
    result = memory_runner("早上 开灯", db_path=db)
    assert "早上 7 点开灯" in result["answer"]

  def test_memory_suite_offline_run(self, tmp_path):
    """整个记忆套件用临时库离线跑通且全命中。"""
    suite = build_memory_suite()
    db = str(tmp_path / "suite.db")
    runner = lambda text: memory_runner(text, db_path=db)
    result = run_suite(suite, runner=runner)
    scores = score_suite(result)
    assert scores["overall"] == 1.0, report(result)
    assert scores["count"] == {"ok": 8, "total": 8}

  def test_unknown_query_returns_empty_answer(self, tmp_path):
    db = str(tmp_path / "empty.db")
    result = memory_runner("完全不相关的查询词组", db_path=db)
    assert result["status"] == "ok"
    assert result["answer"] == ""


# ========== 工作流匹配（actions 列表形态） ==========

class TestWorkflowMatching:
  def test_actions_list_matching(self):
    suite = build_workflow_suite()
    runner = _fake_runner_by_text({
      "先开灯，然后把门锁上": {
        "status": "ok",
        "actions": [{"action": "light_on"}, {"action": "lock_close"}],
        "answer": "好的，先开灯再锁门",
      },
      "先关灯再后退": {"status": "ok", "action": "light_off"},  # 只返回首个 -> 失败
    })
    # 只跑前两个任务验证匹配逻辑
    sub = TaskSuite(name="wf-sub", tasks=suite.tasks[:2])
    result = run_suite(sub, runner=runner)
    by_id = {r["task_id"]: r for r in result.results}
    assert by_id["wf-01"]["matched"] is True
    assert by_id["wf-01"]["actions"] == ["light_on", "lock_close"]
    assert by_id["wf-02"]["matched"] is False

  def test_answer_substring_matching(self):
    """非动作期望段走 answer 子串匹配。"""
    suite = TaskSuite(
      name="ans",
      tasks=[BenchmarkTask("t1", "问答", "今天天气怎么样", "晴天", "workflow")],
    )
    runner = lambda text: {"status": "ok", "action": "idle",
                           "answer": "今天是晴天，适合出门。"}
    scores = score_suite(run_suite(suite, runner=runner))
    assert scores["overall"] == 1.0


# ========== 外部 MCP 工具套件（G6/G19） ==========

class TestExternalToolsSuite:
  def test_suite_valids(self, monkeypatch):
    """套件字段校验 + 期望=36 子串（外部工具调用结果）。"""
    from benchmarks.external_tools_suite import build_suite
    suite = build_suite()
    assert suite.name == "external-tools-suite"
    t = suite.tasks[0]
    assert t.category == "external_tools"
    assert t.expected == "36"

  def test_runner_invokes_external_tool(self, monkeypatch):
    """config 后 runner 应物化 mcp_stub_square 且 invoke 返回 36（零网络 stdio）。"""
    # runner 内部设置 RAK_MCP_SERVERS 并用 sys.executable spawn stub
    from benchmarks.external_tools_suite import build_suite, external_tools_runner
    result = external_tools_runner("调用 stub square")
    assert result["status"] == "ok"
    assert result["answer"].strip() == "36"
    assert "mcp_stub_square" in result.get("tools", [])

  def test_suite_offline_run(self, monkeypatch):
    """整套件离线跑通且全命中。"""
    from benchmarks.external_tools_suite import build_suite, external_tools_runner
    suite = build_suite()
    result = run_suite(suite, runner=external_tools_runner, trace_prefix="ext")
    scores = score_suite(result)
    assert scores["overall"] == 1.0, report(result)
    assert scores["count"] == {"ok": 1, "total": 1}

  def test_load_suites_includes_external_tools(self):
    """load_suites('all') 应含 external_tools 套件。"""
    from src.harness.benchmark import load_suites
    loaded = load_suites("all")
    names = {s.name for s, _ in loaded}
    assert "external-tools-suite" in names

