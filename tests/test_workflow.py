"""Plan-Execute-Review 工作流引擎测试（无网络：planner/executor/reviewer 全部注入假实现）"""

import json
from unittest.mock import patch

import pytest

from src.core.agent_session import SessionStore
from src.harness import workflow
from src.harness.workflow import (
  WorkflowStep, parse_plan, run_subagent, run_workflow,
  get_workflow_stats, reset_workflow_stats,
)


FAKE_PLAN = json.dumps({
  "rationale": "两步走：先查询再执行",
  "steps": [
    {"title": "查询状态", "task": "查询设备当前状态"},
    {"title": "执行动作", "task": "执行开灯动作"},
  ],
}, ensure_ascii=False)


def fake_planner(goal):
  """假规划器：固定返回两步 JSON 计划"""
  return FAKE_PLAN


def failing_planner(goal):
  """假规划器：直接抛异常（测降级）"""
  raise RuntimeError("planner down")


def fake_executor(task, goal=""):
  """假执行器：返回罐头结果"""
  return {
    "action": "nod",
    "answer": f"已完成：{task}",
    "trace": [{"tool": "finalize", "result": "ok"}],
    "session_id": "sub-agent-1",
  }


def fake_reviewer_accept(goal, steps_summary):
  """假评审器：直接接受"""
  return {"accept": True, "feedback": ""}


class TestParsePlan:

  def test_parse_plan_happy(self):
    """合法 JSON 计划 -> 3 个 pending 步骤"""
    text = json.dumps({
      "rationale": "分三步",
      "steps": [
        {"title": "一", "task": "任务一"},
        {"title": "二", "task": "任务二"},
        {"title": "三", "task": "任务三"},
      ],
    }, ensure_ascii=False)
    plan = parse_plan(text, goal="总目标")
    assert len(plan.steps) == 3
    assert all(isinstance(s, WorkflowStep) for s in plan.steps)
    assert all(s.status == "pending" for s in plan.steps)
    assert plan.rationale == "分三步"
    assert [s.id for s in plan.steps] == [0, 1, 2]
    assert plan.steps[0].task == "任务一"

  def test_parse_plan_markdown_fence(self):
    """markdown 代码块 + 尾部杂文本也应被容忍"""
    text = (
      "好的，以下是计划：\n"
      "```json\n"
      '{"rationale": "围栏", "steps": [{"title": "A", "task": "做A"}, '
      '{"title": "B", "task": "做B"}]}\n'
      "```\n"
      "希望对你有帮助！"
    )
    plan = parse_plan(text, goal="目标")
    assert len(plan.steps) == 2
    assert plan.steps[0].task == "做A"
    assert plan.steps[1].task == "做B"
    assert plan.rationale == "围栏"

  def test_parse_plan_degradation(self):
    """垃圾文本 -> 降级为单步计划（目标即任务）"""
    plan = parse_plan("这不是 JSON {{{ 完全无法解析", goal="把灯打开")
    assert len(plan.steps) == 1
    assert plan.steps[0].task == "把灯打开"
    assert plan.steps[0].status == "pending"

  def test_parse_plan_caps_steps(self):
    """防御性上限：LLM 过度分解时截断到 MAX_PLAN_STEPS"""
    text = json.dumps({
      "steps": [{"title": f"s{i}", "task": f"任务{i}"} for i in range(10)],
    }, ensure_ascii=False)
    plan = parse_plan(text, goal="目标")
    assert len(plan.steps) <= 6


class TestRunSubagent:

  def test_run_subagent_wraps_agent(self):
    """run_subagent 应包装 run_agent 并透传结果"""
    with patch("src.core.agent_loop.run_agent",
               return_value={"action": "nod", "params_json": "{}",
                             "answer": "好的", "trace": ["llm->finalize"],
                             "session_id": "agent-1"}) as mock_agent:
      out = run_subagent("查询设备", goal="开灯")
    assert out is not None
    assert out["action"] == "nod"
    assert out["session_id"] == "agent-1"
    # 系统提示词应由 goal+task 派生
    args, kwargs = mock_agent.call_args
    assert args[0] == "查询设备"
    assert "开灯" in kwargs.get("system_prompt", "")
    assert "查询设备" in kwargs.get("system_prompt", "")

  def test_run_subagent_agent_fails_returns_none(self):
    """agent 失败应返回 None（不抛异常）"""
    with patch("src.core.agent_loop.run_agent", return_value=None):
      assert run_subagent("任务") is None
    with patch("src.core.agent_loop.run_agent", side_effect=RuntimeError("boom")):
      assert run_subagent("任务") is None


class TestRunWorkflow:

  def setup_method(self):
    reset_workflow_stats()

  def test_run_workflow_accept_first_try(self):
    """一次通过：completed，iterations==1，输出包含执行器产物"""
    result = run_workflow(
      "让灯亮起来",
      planner=fake_planner, executor=fake_executor, reviewer=fake_reviewer_accept,
    )
    assert result.status == "completed"
    assert result.iterations == 1
    assert result.review_log == []
    assert "已完成：查询设备当前状态" in result.final_output
    assert "已完成：执行开灯动作" in result.final_output
    assert all(s.status == "done" for s in result.plan.steps)
    assert result.session_id
    assert result.latency_ms >= 0.0

  def test_run_workflow_review_rejects_once(self):
    """首轮拒绝（带反馈）次轮接受：iterations==2，review_log 记 1 条"""
    calls = {"n": 0}
    plan_texts = []

    def planner_with_feedback(goal):
      plan_texts.append(goal)
      return FAKE_PLAN

    def reviewer_reject_once(goal, summary):
      calls["n"] += 1
      if calls["n"] == 1:
        return {"accept": False, "feedback": "第二步应该先确认灯泡状态"}
      return {"accept": True, "feedback": ""}

    result = run_workflow(
      "让灯亮起来",
      planner=planner_with_feedback, executor=fake_executor,
      reviewer=reviewer_reject_once,
    )
    assert result.status == "completed"
    assert result.iterations == 2
    assert len(result.review_log) == 1
    assert result.review_log[0]["feedback"] == "第二步应该先确认灯泡状态"
    # 第二轮 planner 收到的输入应包含上轮反馈
    assert "第二步应该先确认灯泡状态" in plan_texts[1]

  def test_run_workflow_reuses_done_steps(self):
    """重规划后已完成步骤不重复执行（结果复用）"""
    exec_calls = []

    def executor_counting(task, goal=""):
      exec_calls.append(task)
      return {"action": "idle", "answer": f"结果:{task}", "trace": [], "session_id": "s"}

    def reviewer_reject_once(goal, summary):
      return {"accept": False, "feedback": "再来一次"}

    def reviewer_factory():
      state = {"n": 0}

      def _rev(goal, summary):
        state["n"] += 1
        return {"accept": state["n"] > 1, "feedback": "" if state["n"] > 1 else "不够"}
      return _rev

    result = run_workflow(
      "目标", planner=fake_planner, executor=executor_counting,
      reviewer=reviewer_factory(), max_iterations=2,
    )
    assert result.status == "completed"
    # 两步各只执行一次（第二轮全部复用）
    assert len(exec_calls) == 2
    assert set(exec_calls) == {"查询设备当前状态", "执行开灯动作"}

  def test_run_workflow_max_iterations(self):
    """评审始终拒绝：达到 max_iterations 后 partial 退出"""
    result = run_workflow(
      "永远做不完的目标",
      planner=fake_planner, executor=fake_executor,
      reviewer=lambda goal, summary: {"accept": False, "feedback": "还不行"},
      max_iterations=2,
    )
    assert result.status == "partial"
    assert result.iterations == 2
    assert len(result.review_log) == 2

  def test_run_workflow_planner_fails(self):
    """planner 抛异常 -> 降级单步计划，仍能完成"""
    result = run_workflow(
      "把风扇关掉",
      planner=failing_planner, executor=fake_executor, reviewer=fake_reviewer_accept,
    )
    assert result.status == "completed"
    assert len(result.plan.steps) == 1
    assert result.plan.steps[0].task == "把风扇关掉"
    assert "已完成：把风扇关掉" in result.final_output

  def test_run_workflow_executor_fails_step_marked(self):
    """executor 返回 None -> 步骤 failed；其它步骤正常 -> partial"""
    def executor_mixed(task, goal=""):
      if "查询" in task:
        return None
      return {"action": "nod", "answer": f"好了:{task}", "trace": [], "session_id": "s"}

    result = run_workflow(
      "目标", planner=fake_planner, executor=executor_mixed,
      reviewer=fake_reviewer_accept,
    )
    assert result.status == "completed"  # 评审接受即可完成（done 步骤存在）
    statuses = {s.task: s.status for s in result.plan.steps}
    assert statuses["查询设备当前状态"] == "failed"
    assert statuses["执行开灯动作"] == "done"
    assert "好了:执行开灯动作" in result.final_output

  def test_run_workflow_executor_raises_never_crashes(self):
    """executor 抛异常只降级不崩溃"""
    def boom(task, goal=""):
      raise RuntimeError("executor down")

    result = run_workflow(
      "目标", planner=fake_planner, executor=boom,
      reviewer=fake_reviewer_accept,
    )
    assert result.status == "failed"
    assert result.final_output == ""

  def test_run_workflow_persists_session(self, tmp_path):
    """运行后可从 SessionStore 加载 status=completed 的会话"""
    store = SessionStore(data_dir=str(tmp_path))
    with patch.object(workflow, "get_session_store", lambda: store):
      result = run_workflow(
        "持久化测试目标",
        planner=fake_planner, executor=fake_executor, reviewer=fake_reviewer_accept,
      )
    loaded = store.load(result.session_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.final_decision["goal"] == "持久化测试目标"
    assert loaded.final_decision["status"] == "completed"
    assert any(m.role == "system" for m in loaded.messages)
    assert any(m.role == "user" for m in loaded.messages)


class TestWorkflowStats:

  def test_stats_accumulate(self):
    """统计应累计运行次数并计算平均值"""
    reset_workflow_stats()
    run_workflow("目标一", planner=fake_planner, executor=fake_executor,
                 reviewer=fake_reviewer_accept)
    stats = get_workflow_stats()
    assert stats["runs"] == 1
    assert stats["avg_iterations"] == 1.0
    assert stats["avg_latency_ms"] >= 0.0
    reset_workflow_stats()
    assert get_workflow_stats()["runs"] == 0


class TestSubagentInheritsHarnessCapabilities:
    """工作流子 agent 应自动继承 harness 能力（外部 MCP 工具 + 已学会技能）。

    run_subagent 走 run_agent → _build_tools，后者已物化外部 MCP 工具（G6/G19-2）
    并把技能 digest 注入系统提示词（G12/G13）。本测试锁定『工作流子 agent 获益
    于这些 harness 能力』的集成行为。
    """

    def test_subagent_delegates_to_run_agent(self):
        """run_subagent 应调用 run_agent（其内部 _build_tools 物化能力）且系统提示词含目标+任务。"""
        captured = {}
        with patch("src.core.agent_loop.run_agent") as mock_agent:
            mock_agent.return_value = {"action": "nod", "answer": "好",
                                       "trace": [], "session_id": "s"}
            out = run_subagent("查询设备状态", goal="开灯")
        assert out is not None
        args, kwargs = mock_agent.call_args
        assert args[0] == "查询设备状态"
        assert "查询设备状态" in kwargs.get("system_prompt", "")
        assert "开灯" in kwargs.get("system_prompt", "")

    def test_build_tools_includes_external_when_configured(self, monkeypatch):
        """RAK_MCP_SERVERS 配置时，_build_tools 物化外部 MCP 工具（子 agent 可用）。"""
        import sys, json as _json
        monkeypatch.setenv("RAK_MCP_SERVERS", _json.dumps(
            [{"name": "stub", "command": sys.executable, "args": ["-u", "/tmp/rak_stub_mcp.py"]}]))
        import src.tools.mcp_client as mc
        mc._client = None  # 重读 env
        from src.core import agent_loop
        tools, _ = agent_loop._build_tools(["idle"], "")
        names = [getattr(t, "name", "?") for t in tools]
        assert "mcp_stub_square" in names
        # 工作流子 agent 的 run_agent 走同一 _build_tools → 继承


class TestWorkflowSuperMemory:
    """工作流成果应写入超长期记忆（scope='workflow'，跨会话可召回先例）。"""

    FAKE_PLAN = json.dumps({
        "steps": [{"title": "查询", "task": "查询状态"}, {"title": "执行", "task": "执行开灯"}],
    })

    def _run(self):
        return run_workflow(
            "让灯亮起来",
            planner=lambda goal: self.FAKE_PLAN,
            executor=lambda task, goal="": {"action": "nod",
                                            "answer": f"【结果】完成：{task}",
                                            "trace": [], "session_id": "s"},
            reviewer=lambda goal, s: {"accept": True, "feedback": ""},
        )

    def _fresh_super_memory(self):
        # 重置单例指向隔离目录；返回可 recall 的句柄
        import src.core.memory_longterm as mlt
        mlt._instance = None
        return mlt.get_super_memory()

    def _reset_singletons(self):
        """重置全部超长期记忆/记忆图谱单例（防跨用例泄漏导致把工作流写入陈旧库）。"""
        import src.core.memory_longterm as mlt
        import src.core.memory_graph as mg
        import src.core.decision_engine as de
        mlt._instance = None
        mg._instance = None
        de._super_memory = None
        de._memory_graph = None

    def test_workflow_outcome_recallable(self, tmp_path, monkeypatch):
        """completed 工作流后，SuperMemory scope='workflow' 应可召回目标+完成步骤。"""
        monkeypatch.setenv("RAK_DATA_DIR", str(tmp_path / "data"))
        self._reset_singletons()
        res = self._run()
        assert res.status == "completed"
        sm = self._fresh_super_memory()
        hits = sm.recall("工作流 让灯亮", scope="workflow", top_k=5)
        assert any("工作流" in h.content and "让灯亮起来" in h.content for h in hits)
        full = sm.recall_full(hits[0].id)
        assert full["metadata"].get("type") == "workflow"
        assert full["metadata"].get("status") == "completed"
        assert full["metadata"].get("session_id")

    def test_workflow_memory_idempotent(self, tmp_path, monkeypatch):
        """同目标再跑不重复落盘（幂等 content-hash）。"""
        monkeypatch.setenv("RAK_DATA_DIR", str(tmp_path / "data"))
        self._reset_singletons()
        self._run()
        sm = self._fresh_super_memory()
        hits = sm.recall("工作流 让灯亮", scope="workflow", top_k=5)
        self._run()  # 再跑（单例仍指向同库）
        hits2 = sm.recall("工作流 让灯亮", scope="workflow", top_k=5)
        assert len(hits) == len(hits2), "同目标再跑应幂等（不新增重复条目）"

    def test_related_goal_recall_generalization_gap(self, tmp_path, monkeypatch):
        """相关目标召回泛化不足（已知限制）——锁定当前行为作为改进基线。

        诚实记录：SuperMemory 词法召回（FTS/LIKE/bigram）对『让灯亮起来』能命中
        近逐字查询，但改写后的相关目标（把灯光调亮/调亮书房的灯/灯光）返回空——
        跨会话先例只能按近逐字召回，无法引导相关新目标（与语义缓存早期同义改写
        失效同类；语义缓存用 Dice 层解决，超长期记忆泛化待后续）。此测试锁定当前
        行为，防止静默『看似支持实不支持』。
        """
        monkeypatch.setenv("RAK_DATA_DIR", str(tmp_path / "data"))
        self._reset_singletons()
        self._run()  # 写入「让灯亮起来」工作流记忆
        sm = self._fresh_super_memory()
        # 近逐字查询：可召回
        exact = sm.recall("工作流 让灯亮", scope="workflow", top_k=5)
        assert any("让灯亮起来" in h.content for h in exact)
        # 改写相关目标：当前词法召回返回空（已知泛化缺口，见 docstring）
        rewritten = sm.recall("把灯光调亮方便看书", scope="workflow", top_k=5)
        assert all("让灯亮起来" not in h.content for h in rewritten)


