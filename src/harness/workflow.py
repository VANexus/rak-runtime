"""
Plan-Execute-Review 多智能体工作流引擎。

在单轮 agent 内核（src.core.agent_loop.run_agent）之上叠加结构化工作流：

  1. PLAN    - planner(goal) 产出 JSON 计划（多步分解），解析失败降级为单步计划
  2. EXECUTE - 每步经 executor（默认 run_subagent，包装 run_agent）执行
  3. REVIEW  - reviewer(goal, steps_summary) 判断是否达成目标；
               拒绝 -> 携带反馈重新规划，只重跑失败/未完成步骤，复用已完成结果
  4. OUTPUT  - 由已接受步骤的结果组装最终输出

硬性不变量：
- 任何 planner/executor/reviewer 异常只记录日志并降级，绝不抛出到 run_workflow 之外
- 会话持久化到 data/sessions/（复用 AgentSession/SessionStore），可诊断可重放
"""

import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from src.core._utils import safe_json_parse
from src.core.agent_session import (
  AgentSession, ToolTraceEvent, get_session_store,
)

logger = logging.getLogger(__name__)

# 防御性上限：计划步骤数（防 LLM 过度分解）
MAX_PLAN_STEPS = 6

# MVP 动作集（与 runtime 契约一致）
DEFAULT_AVAILABLE_ACTIONS = [
  "shake_head", "wave_hand", "lock_open", "lock_close",
  "move_forward", "move_back", "turn_left", "turn_right",
  "dance", "nod", "light_on", "light_off",
  "emergency_stop", "idle",
]


@dataclass
class WorkflowStep:
  """工作流中的一个步骤"""
  id: int
  title: str
  task: str
  status: str = "pending"          # pending / running / done / failed / skipped
  result: str = ""
  tool_trace: list = field(default_factory=list)


@dataclass
class WorkflowPlan:
  """工作流计划（planner 产物）"""
  goal: str
  steps: list                       # list[WorkflowStep]
  rationale: str = ""


@dataclass
class WorkflowResult:
  """工作流执行结果"""
  plan: WorkflowPlan
  final_output: str
  status: str                       # completed / partial / failed
  iterations: int
  review_log: list = field(default_factory=list)   # 每轮被拒绝的评审反馈
  latency_ms: float = 0.0
  session_id: str = ""


# ---------------------------------------------------------------------------
# 计划解析
# ---------------------------------------------------------------------------

def _degradation_plan(goal: str) -> WorkflowPlan:
  """降级计划：目标本身作为唯一一步（planner 不可用时仍可执行）"""
  task = (goal or "").strip() or "未命名目标"
  return WorkflowPlan(
    goal=task,
    steps=[WorkflowStep(id=0, title="直接执行", task=task, status="pending")],
    rationale="（planner 不可用，降级为单步直接执行）",
  )


def parse_plan(llm_text: str, goal: str = "") -> WorkflowPlan:
  """
  解析 planner 输出为 WorkflowPlan。

  容忍 markdown 代码块与前后杂文本；steps 项可以是
  {"title","task"} dict 或纯字符串。解析失败 -> 降级单步计划（goal 即任务）。
  """
  text = llm_text or ""
  data = safe_json_parse(text)
  steps: list[WorkflowStep] = []
  rationale = ""

  raw_steps = []
  if isinstance(data, dict):
    rationale = str(data.get("rationale", "") or "")
    raw_steps = data.get("steps") or data.get("plan") or []
  elif isinstance(data, list):
    raw_steps = data

  if isinstance(raw_steps, list):
    for idx, item in enumerate(raw_steps):
      if isinstance(item, str):
        title, task = item, item
      elif isinstance(item, dict):
        title = str(item.get("title") or f"步骤{idx + 1}")
        task = str(item.get("task") or item.get("description") or "").strip()
      else:
        continue
      task = (task or "").strip()
      if not task:
        continue
      steps.append(WorkflowStep(
        id=len(steps), title=(title or task).strip()[:120],
        task=task[:2000], status="pending",
      ))
      if len(steps) >= MAX_PLAN_STEPS:  # 防御性上限：防 LLM 过度分解
        break

  if not steps:
    return _degradation_plan(goal or text)

  plan_goal = (goal or "").strip() or (plan_goal_text(data) if isinstance(data, dict) else "")
  return WorkflowPlan(goal=plan_goal or "未命名目标", steps=steps, rationale=rationale)


def plan_goal_text(data: dict) -> str:
  """从计划 JSON 中提取 goal 字段（若有）"""
  return str(data.get("goal", "") or "").strip()


# ---------------------------------------------------------------------------
# 子智能体执行
# ---------------------------------------------------------------------------

def run_subagent(task: str, goal: str = "", available_actions=None) -> dict:
  """
  用 agent 内核执行单个步骤（不重复实现 agent 循环）。

  返回 {action, answer, trace, session_id}；失败返回 None（供上层降级标记 failed）。
  """
  try:
    from src.core.agent_loop import run_agent
    actions = available_actions or DEFAULT_AVAILABLE_ACTIONS
    system_prompt = (
      f"你是工作流中的子智能体，负责完成一个具体步骤。\n"
      f"总目标：{goal or '（未提供）'}\n"
      f"当前任务：{task}\n"
      f"聚焦当前任务，简洁完成并调用 finalize 给出结论。"
    )
    return run_agent(task, actions, system_prompt=system_prompt,
                     trace_id="workflow")
  except Exception as e:
    logger.warning("[Workflow] 子智能体执行失败（任务: %s）: %s", task[:80], e)
    return None


def _invoke_executor(executor, task: str, goal: str):
  """兼容 (task) / (task, goal) 两种执行器签名的调用包装"""
  try:
    params = list(inspect.signature(executor).parameters.values())
    if len(params) >= 2:
      return executor(task, goal)
    return executor(task)
  except (ValueError, TypeError):
    return executor(task)


# ---------------------------------------------------------------------------
# 默认 planner / reviewer（LLM 调用，测试中会被注入的假实现替换）
# ---------------------------------------------------------------------------

def _default_planner(goal: str) -> str:
  """默认规划器：LLM 生成 JSON 计划。失败时抛异常，由 run_workflow 降级。"""
  from src.core._utils import make_llm_client, get_model, thinking_extra
  client = make_llm_client(timeout=30.0)
  prompt = (
    f"目标：{goal}\n\n"
    f"请把这个目标分解为 2-4 个可独立执行的步骤。宁少勿多：简单目标 1-2 步即可，"
    f"只有真正需要分工时才增加步骤。最多 4 步。只输出 JSON，格式：\n"
    f'{{"rationale": "为何这样分解", '
    f'"steps": [{{"title": "步骤简称", "task": "具体要做的事"}}]}}'
  )
  resp = client.messages.create(
    model=get_model(),
    max_tokens=1024,
    system="你是严谨的任务规划器，只输出合法 JSON，不要输出其它文本。步骤数必须 1-4 个。",
    messages=[{"role": "user", "content": prompt}],
    extra_body=thinking_extra(),
  )
  return "".join(getattr(b, "text", "") for b in resp.content)


def _default_reviewer(goal: str, steps_summary: str) -> dict:
  """默认评审器：LLM 判断已执行步骤是否达成目标。失败降级为接受（避免死循环）。"""
  from src.core._utils import make_llm_client, get_model, thinking_extra, safe_json_parse as sjp
  try:
    client = make_llm_client(timeout=30.0)
    prompt = (
      f"目标：{goal}\n\n已执行步骤：\n{steps_summary}\n\n"
      f"这些步骤的执行结果是否达成了目标？只输出 JSON："
      f'{{"accept": true/false, "feedback": "若拒绝，给出具体修正建议"}}'
    )
    resp = client.messages.create(
      model=get_model(),
      max_tokens=512,
      system="你是严格但务实的评审者，只输出合法 JSON。",
      messages=[{"role": "user", "content": prompt}],
      extra_body=thinking_extra(),
    )
    text = "".join(getattr(b, "text", "") for b in resp.content)
    data = sjp(text)
    if isinstance(data, dict) and "accept" in data:
      return {"accept": bool(data.get("accept")),
              "feedback": str(data.get("feedback", "") or "")}
  except Exception as e:
    logger.warning("[Workflow] 评审器失败（降级为接受）: %s", e)
  return {"accept": True, "feedback": ""}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _merge_plans(old_plan: WorkflowPlan, new_plan: WorkflowPlan) -> WorkflowPlan:
  """合并新旧计划：复用已完成步骤的结果，只重跑失败/新增步骤。"""
  done_by_task = {s.task: s for s in old_plan.steps if s.status == "done"}
  merged: list[WorkflowStep] = []
  seen = set()
  for s in new_plan.steps:
    if s.task in seen:
      continue
    seen.add(s.task)
    if s.task in done_by_task:
      d = done_by_task[s.task]
      merged.append(WorkflowStep(
        id=len(merged), title=s.title, task=s.task,
        status="done", result=d.result, tool_trace=list(d.tool_trace),
      ))
    else:
      merged.append(WorkflowStep(
        id=len(merged), title=s.title, task=s.task, status="pending",
      ))
  # 旧已完成但新计划未提及的步骤也保留（结果不丢失）
  for task, d in done_by_task.items():
    if task not in seen:
      merged.append(WorkflowStep(
        id=len(merged), title=d.title, task=task,
        status="done", result=d.result, tool_trace=list(d.tool_trace),
      ))
  return WorkflowPlan(goal=new_plan.goal or old_plan.goal,
                      steps=merged, rationale=new_plan.rationale)


def _steps_summary(plan: WorkflowPlan) -> str:
  """给 reviewer 的步骤执行摘要"""
  lines = []
  for s in plan.steps:
    result = (s.result or "").replace("\n", " ")[:200]
    lines.append(f"- [{s.status}] {s.title}：{s.task} -> {result}")
  return "\n".join(lines) or "（无步骤）"


def _compose_output(goal: str, done_steps: list) -> str:
  """由已接受步骤的结果组装最终输出"""
  if not done_steps:
    return ""
  parts = [f"目标：{goal}"]
  for s in done_steps:
    parts.append(f"## {s.title}\n{s.result}")
  return "\n\n".join(parts)


def _record_tool_trace(session: AgentSession, trace: list):
  """把步骤的工具轨迹转存到会话（字符串或 dict 都容忍）"""
  for t in trace or []:
    try:
      if isinstance(t, dict):
        session.append_tool_trace(ToolTraceEvent(
          tool=str(t.get("tool", "step")), args={},
          result=str(t.get("result", ""))[:200],
          duration_ms=float(t.get("duration_ms", 0.0)), status="ok",
        ))
      else:
        session.append_tool_trace(ToolTraceEvent(
          tool=str(t), args={}, result="", duration_ms=0.0, status="ok",
        ))
    except Exception as e:
      logger.warning("[Workflow] 工具轨迹记录失败: %s", e)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

_stats = {"runs": 0, "total_iterations": 0, "total_latency_ms": 0.0}


def get_workflow_stats() -> dict:
  """工作流运行统计（运行次数 / 平均迭代轮数 / 平均延迟）"""
  runs = _stats["runs"]
  return {
    "runs": runs,
    "avg_iterations": round(_stats["total_iterations"] / runs, 2) if runs else 0.0,
    "avg_latency_ms": round(_stats["total_latency_ms"] / runs, 1) if runs else 0.0,
  }


def reset_workflow_stats():
  """清零统计（测试用）"""
  _stats.update({"runs": 0, "total_iterations": 0, "total_latency_ms": 0.0})


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _remember_workflow(goal: str, status: str, iterations: int,
                       steps: list, session_id: str) -> None:
    """
    把工作流成果写入超长期记忆（G10/超长期记忆主题）：未来跨会话可召回先例。

    scope 用 'workflow'（多工作流不串）；content 幂等（sha256），同目标再跑
    只更新 importance/metadata；失败降级不抛出（窄腰原则）。
    """
    try:
        # 只沉淀有内容的步骤结果，避免空噪音
        done = [s for s in steps if s.get("status") == "done" and s.get("result")]
        if not done:
            return
        content = (f"工作流『{goal[:60]}』完成（{status}，{iterations} 轮）：\n"
                   + "\n".join(f"- {s['title']}: {s['result'][:120]}" for s in done[:5]))
        from src.core.memory_longterm import get_super_memory
        from src.core.decision_engine import _get_memory_graph
        sm = get_super_memory()
        if sm is None:
            return
        importance = 0.8 if status == "completed" else 0.6
        mem_id = sm.remember(
            content=content, memory_type="procedural", scope="workflow",
            importance=importance,
            metadata={"type": "workflow", "goal": goal, "status": status,
                      "iterations": iterations, "session_id": session_id},
        )
        # 把工作流记忆注册进记忆图谱（可多跳联想召回）
        if mem_id:
            g = _get_memory_graph()
            if g is not None:
                try:
                    g.index(mem_id, content, scope="workflow")
                except Exception:
                    pass
    except Exception as e:
        logger.warning("[Workflow] 工作流记忆沉淀失败（降级）: %s", e)


def run_workflow(goal: str, planner=None, executor=None, reviewer=None,
                 max_iterations: int = 3, verbose: bool = False) -> WorkflowResult:
  """
  运行 Plan-Execute-Review 工作流。

  - planner(goal)->str：默认 LLM 规划；失败降级单步计划
  - executor(task, goal)：默认 run_subagent
  - reviewer(goal, steps_summary)->{"accept":bool,"feedback":str}
  - 拒绝时携带反馈重新规划，只重跑失败/未完成步骤
  - 任何内部异常只降级不抛出；会话持久化，session_id 随结果返回
  """
  t0 = time.time()
  max_iterations = max(1, int(max_iterations))
  planner = planner or _default_planner
  executor = executor or run_subagent
  reviewer = reviewer or _default_reviewer

  session_id = f"workflow-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
  session = AgentSession(session_id=session_id, trace_id="workflow")
  session.append_message("system", f"[workflow] 目标：{goal}")

  plan = None
  review_log: list[dict] = []
  iterations = 0
  status = "failed"
  feedback = ""

  try:
    for iteration in range(1, max_iterations + 1):
      iterations = iteration

      # ---- PLAN ----
      try:
        planner_input = goal
        if feedback:
          planner_input = f"{goal}\n\n[上一轮评审反馈，请在计划中修正] {feedback}"
        plan_text = planner(planner_input)
        new_plan = parse_plan(plan_text, goal=goal)
      except Exception as e:
        logger.warning("[Workflow] planner 失败（降级单步计划）: %s", e)
        new_plan = _degradation_plan(goal)
      plan = _merge_plans(plan, new_plan) if plan is not None else new_plan
      session.append_message(
        "user", f"[iteration {iteration}] 计划 {len(plan.steps)} 步："
                + "；".join(s.title for s in plan.steps)[:1000])
      if verbose:
        logger.info("[Workflow] iteration=%d 计划 %d 步", iteration, len(plan.steps))

      # ---- EXECUTE ----
      for step in plan.steps:
        if step.status == "done":
          continue  # 复用已完成结果
        step.status = "running"
        try:
          out = _invoke_executor(executor, step.task, goal)
        except Exception as e:
          logger.warning("[Workflow] 步骤执行异常（%s）: %s", step.title, e)
          out = None
        if not isinstance(out, dict):
          step.status = "failed"
          step.result = ""
          continue
        answer = str(out.get("answer", "") or "")
        step.result = answer or json.dumps(out, ensure_ascii=False)
        step.tool_trace = list(out.get("trace") or [])
        step.status = "done"
        _record_tool_trace(session, step.tool_trace)

      # ---- REVIEW ----
      summary = _steps_summary(plan)
      try:
        review = reviewer(goal, summary) or {}
        accept = bool(review.get("accept"))
        fb = str(review.get("feedback", "") or "")
      except Exception as e:
        logger.warning("[Workflow] reviewer 失败（降级为接受）: %s", e)
        accept, fb = True, ""
      if verbose:
        logger.info("[Workflow] iteration=%d 评审 accept=%s", iteration, accept)

      if accept:
        status = "completed"
        break
      review_log.append({
        "iteration": iteration, "accept": False, "feedback": fb,
      })
      if iteration >= max_iterations:
        status = "partial"
        break
      feedback = fb

    # ---- OUTPUT ----
    done = [s for s in (plan.steps if plan else []) if s.status == "done"]
    final_output = _compose_output(goal, done)
    if status != "completed":
      status = "partial" if done else "failed"
    elif not done:
      # 评审接受但没有任何成功步骤 -> 不可能是 completed
      status = "failed"

  except Exception as e:
    # 兜底：任何未预期异常都降级为 failed，不抛出
    logger.warning("[Workflow] 工作流异常（降级 failed）: %s", e)
    status = "failed"
    plan = plan or _degradation_plan(goal)
    final_output = ""

  latency_ms = (time.time() - t0) * 1000

  # ---- 持久化会话 ----
  try:
    decision = {
      "goal": goal, "status": status, "iterations": iterations,
      "steps": [{"title": s.title, "task": s.task,
                 "status": s.status, "result": (s.result or "")[:500]}
                for s in plan.steps],
    }
    session.append_message(
      "assistant", f"[workflow] status={status} iterations={iterations}\n"
                   f"{(final_output or '')[:1000]}")
    if status == "failed":
      session.mark_error("工作流未产生任何完成的步骤")
      session.final_decision = decision
    else:
      session.mark_completed(decision)
    get_session_store().save(session)
  except Exception as e:
    logger.warning("[Workflow] 会话持久化失败: %s", e)

  # ---- 超长期记忆沉淀（G10 主题）：跨会话可召回工作流先例 ----
  try:
    step_dicts = [{"title": s.title, "task": s.task, "status": s.status,
                   "result": s.result} for s in plan.steps]
    _remember_workflow(goal, status, iterations, step_dicts, session_id)
  except Exception as e:
    logger.warning("[Workflow] 记忆沉淀调用失败（降级）: %s", e)

  # ---- 统计 ----
  _stats["runs"] += 1
  _stats["total_iterations"] += iterations
  _stats["total_latency_ms"] += latency_ms

  return WorkflowResult(
    plan=plan, final_output=final_output, status=status,
    iterations=iterations, review_log=review_log,
    latency_ms=round(latency_ms, 1), session_id=session_id,
  )
