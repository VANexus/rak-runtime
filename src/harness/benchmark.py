"""
基准测试基础设施 - rak-runtime 认知引擎评测框架。

职责：
- 定义 BenchmarkTask / TaskSuite / SuiteResult 数据结构
- run_suite：跑一个套件，产出每任务结果（动作/回答/延迟/工具次数/是否命中）
- score_suite：加权打分（总体 + 分类 + 延迟 + 工具效率）
- report：人类可读表格（text）或 JSON
- compare：基线对比（单发 JSON 路径 vs Agent 内核路径）
- CLI 入口：python -m src.harness.benchmark --suite all|decision|memory|workflow

设计原则：
- runner 可注入（默认走 DecisionEngine 完整链路），测试用 fake runner 离线跑
- 任何单任务失败只记为 fail，绝不让基准进程崩溃（优雅降级）
- expected 支持 "a|b" 多段：每段是已知动作名（匹配 action/actions），
  或非动作字符串（匹配 answer 子串），全部命中才算 PASS
"""

import argparse
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

from src.harness.brain import run_brain, run_brain_single_shot, DEFAULT_ACTIONS

# 14 动作 MVP 集（与 go-kernel / rak-esp 契约一致）
AVAILABLE_ACTIONS = list(DEFAULT_ACTIONS)

_ACTION_SET = set(AVAILABLE_ACTIONS)


# ========== 数据结构 ==========

@dataclass
class BenchmarkTask:
  """一个基准任务：中文自然语言输入 + 期望（动作名或回答子串，支持 | 多段）。"""
  task_id: str
  description: str
  input: str
  expected: str
  category: str  # decision / memory / workflow
  tags: List[str] = field(default_factory=list)
  weight: float = 1.0


@dataclass
class TaskSuite:
  """一组同类任务。"""
  name: str
  tasks: List[BenchmarkTask]
  description: str = ""


@dataclass
class SuiteResult:
  """一次套件运行的结果（每任务一条 outcome dict）。"""
  suite_name: str
  description: str
  results: List[dict] = field(default_factory=list)
  total_ms: float = 0.0

  def to_dict(self) -> dict:
    return {
      "suite": self.suite_name,
      "description": self.description,
      "total_ms": round(self.total_ms, 2),
      "results": self.results,
    }


# ========== 匹配逻辑 ==========

def _extract_actions(result: dict) -> List[str]:
  """从决策结果里抽取全部动作名（action 单值 + actions 列表，兼容 dict 项）。"""
  actions: List[str] = []
  if not isinstance(result, dict):
    return actions
  a = result.get("action")
  if isinstance(a, str) and a:
    actions.append(a)
  for item in result.get("actions") or []:
    if isinstance(item, str) and item:
      actions.append(item)
    elif isinstance(item, dict):
      v = item.get("action")
      if isinstance(v, str) and v:
        actions.append(v)
  return actions


def _split_expected(expected: str) -> List[str]:
  """期望值拆段：'|' 分隔，每段独立匹配。"""
  return [p.strip() for p in (expected or "").split("|") if p.strip()]


def _match(task: BenchmarkTask, result: Optional[dict]) -> bool:
  """
  判定任务是否命中：
  - 期望段是已知动作名 -> 必须出现在抽取出的动作集合里（含 actions 列表）
  - 期望段是普通字符串 -> 必须是 answer 的子串
  - 全部段命中才算命中；异常/空结果一律不命中
  """
  if not isinstance(result, dict):
    return False
  actions = _extract_actions(result)
  answer = str(result.get("answer") or "")
  for part in _split_expected(task.expected):
    if part in _ACTION_SET:
      if part not in actions:
        return False
    elif part not in answer:
      return False
  return bool(_split_expected(task.expected))


def _count_tool_events(result: Optional[dict]) -> int:
  """统计工具调用次数：显式 tool_events > agent 内核 trace 轨迹 > tool_calls。"""
  if not isinstance(result, dict):
    return 0
  explicit = result.get("tool_events")
  if isinstance(explicit, int) and explicit >= 0:
    return explicit
  trace = result.get("trace")
  if isinstance(trace, (list, tuple)):
    return len(trace)
  calls = result.get("tool_calls")
  if isinstance(calls, (list, tuple)):
    return len(calls)
  return 0


# ========== 套件执行 ==========

def _make_default_runner(trace_prefix: str) -> Callable[[str], dict]:
  """默认 runner：走完整大脑链路（LLM 由项目 .env 决定）。"""
  counter = {"n": 0}
  lock = threading.Lock()

  def _runner(text: str) -> dict:
    with lock:
      counter["n"] += 1
      tid = f"{trace_prefix}-{counter['n']}"
    return run_brain(text, trace_id=tid)

  return _runner


def run_suite(suite: TaskSuite, runner: Optional[Callable[[str], dict]] = None,
              trace_prefix: str = "bench") -> SuiteResult:
  """
  跑一个套件。

  runner: (text) -> dict，默认走 run_brain（完整大脑链路）。
  每任务产出 outcome：{task_id, status, action, answer, expected,
                       latency_ms, matched, tool_events, error, category, weight}
  单任务异常只记 fail，不中断整个套件。
  """
  if runner is None:
    runner = _make_default_runner(trace_prefix)

  outcomes: List[dict] = []
  start = time.perf_counter()
  for task in suite.tasks:
    t0 = time.perf_counter()
    result = None
    error = ""
    try:
      result = runner(task.input)
    except Exception as e:  # 优雅降级：单任务失败不影响套件
      logger.warning("[Bench] 任务 %s runner 异常: %s", task.task_id, e)
      error = str(e)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    matched = _match(task, result)
    actions = _extract_actions(result)
    answer = str(result.get("answer") or "") if isinstance(result, dict) else ""
    outcomes.append({
      "task_id": task.task_id,
      "status": "ok" if matched else "fail",
      "action": actions[0] if actions else "",
      "actions": actions,
      "answer": answer,
      "expected": task.expected,
      "latency_ms": latency_ms,
      "matched": matched,
      "tool_events": _count_tool_events(result),
      "error": error,
      "category": task.category,
      "weight": task.weight,
    })
  total_ms = round((time.perf_counter() - start) * 1000, 2)
  return SuiteResult(
    suite_name=suite.name,
    description=suite.description,
    results=outcomes,
    total_ms=total_ms,
  )


# ========== 打分与报告 ==========

def score_suite(result: SuiteResult) -> dict:
  """
  打分：
  - overall: 加权命中率（0-1）
  - per_category: 各分类命中率
  - avg_latency_ms: 平均延迟
  - avg_tool_events: 平均工具调用次数（越低越好）
  - tool_efficiency: 1/(1+平均工具次数)，越高越好（工具越少越高效）
  - count: {ok, total}
  """
  results = result.results if isinstance(result, SuiteResult) else list(result)
  if not results:
    return {"overall": 0.0, "per_category": {}, "avg_latency_ms": 0.0,
            "avg_tool_events": 0.0, "tool_efficiency": 1.0,
            "count": {"ok": 0, "total": 0}}

  total_weight = sum(r.get("weight", 1.0) for r in results) or 1.0
  hit_weight = sum(r.get("weight", 1.0) for r in results if r.get("matched"))

  per_category: Dict[str, dict] = {}
  for r in results:
    cat = r.get("category") or "unknown"
    c = per_category.setdefault(cat, {"hit_w": 0.0, "total_w": 0.0})
    c["total_w"] += r.get("weight", 1.0)
    if r.get("matched"):
      c["hit_w"] += r.get("weight", 1.0)

  n = len(results)
  avg_lat = sum(r.get("latency_ms", 0.0) for r in results) / n
  avg_tools = sum(r.get("tool_events", 0) for r in results) / n

  return {
    "overall": round(hit_weight / total_weight, 4),
    "per_category": {
      cat: round(v["hit_w"] / v["total_w"], 4) if v["total_w"] else 0.0
      for cat, v in per_category.items()
    },
    "avg_latency_ms": round(avg_lat, 2),
    "avg_tool_events": round(avg_tools, 2),
    "tool_efficiency": round(1.0 / (1.0 + avg_tools), 4),
    "count": {"ok": sum(1 for r in results if r.get("matched")), "total": n},
  }


def report(result: SuiteResult, fmt: str = "text") -> str:
  """输出报告：text=人类可读表格（PASS/FAIL），json=json.dumps 字符串。"""
  if fmt == "json":
    payload = {"suite": result.suite_name, "scores": score_suite(result),
               **result.to_dict()}
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

  scores = score_suite(result)
  lines = []
  lines.append("=" * 78)
  lines.append(f"基准报告: {result.suite_name}")
  if result.description:
    lines.append(f"描述: {result.description}")
  lines.append("-" * 78)
  lines.append(f"{'任务':<14}{'结果':<8}{'动作':<18}{'期望':<24}{'延迟ms':>9}{'工具':>6}")
  lines.append("-" * 78)
  for r in result.results:
    status = "PASS" if r.get("matched") else "FAIL"
    act = ",".join(r.get("actions") or ([r.get("action")] if r.get("action") else []))
    lines.append(
      f"{r['task_id']:<14}{status:<8}{(act or '-'):<18}{r['expected']:<24}"
      f"{r['latency_ms']:>9}{r['tool_events']:>6}"
    )
    if r.get("error"):
      lines.append(f"{'':>14}错误: {r['error']}")
  lines.append("-" * 78)
  c = scores["count"]
  lines.append(
    f"总体得分: {scores['overall']:.4f} | 通过: {c['ok']}/{c['total']} | "
    f"平均延迟: {scores['avg_latency_ms']:.2f}ms | "
    f"平均工具次数: {scores['avg_tool_events']:.2f}（越低越好）"
  )
  cat = " ".join(f"{k}={v}" for k, v in scores["per_category"].items())
  if cat:
    lines.append(f"分类得分: {cat}")
  lines.append("=" * 78)
  return "\n".join(lines)


def _fmt(v, signed: bool = False) -> str:
  """数值格式化（compare 表格用）。"""
  try:
    f = float(v)
  except (TypeError, ValueError):
    return str(v)
  if signed:
    return f"{f:+.4f}" if abs(f) < 10 else f"{f:+.2f}"
  return f"{f:.4f}" if abs(f) < 10 else f"{f:.2f}"


def compare(suite_name: str, results_a: SuiteResult, results_b: SuiteResult) -> str:
  """
  基线对比表：metric | 基线(a) | 对比(b) | 差值(b-a)。

  a 通常为单发 JSON 基线（RAK_AGENT=0），b 为 Agent 内核路径。
  """
  sa = score_suite(results_a)
  sb = score_suite(results_b)
  rows = []

  def _row(metric: str, va, vb, signed=True):
    try:
      delta = float(vb) - float(va)
      delta_s = _fmt(delta, signed=True)
    except (TypeError, ValueError):
      delta_s = "-"
    rows.append((metric, _fmt(va), _fmt(vb), delta_s))

  _row("overall", sa["overall"], sb["overall"])
  for cat in sorted(set(sa["per_category"]) | set(sb["per_category"])):
    _row(f"category:{cat}", sa["per_category"].get(cat, 0.0),
         sb["per_category"].get(cat, 0.0))
  _row("avg_latency_ms", sa["avg_latency_ms"], sb["avg_latency_ms"])
  _row("avg_tool_events", sa["avg_tool_events"], sb["avg_tool_events"])
  _row("tool_efficiency", sa["tool_efficiency"], sb["tool_efficiency"])
  rows.append(("ok/total",
               f"{sa['count']['ok']}/{sa['count']['total']}",
               f"{sb['count']['ok']}/{sb['count']['total']}", "-"))

  lines = []
  lines.append("=" * 70)
  lines.append(f"基线对比: {suite_name}  (a=单发JSON基线, b=Agent内核, delta=b-a)")
  lines.append("-" * 70)
  lines.append(f"{'指标':<26}{'a(基线)':>14}{'b(对比)':>14}{'delta':>12}")
  lines.append("-" * 70)
  for metric, va, vb, d in rows:
    lines.append(f"{metric:<26}{va:>14}{vb:>14}{d:>12}")
  lines.append("=" * 70)
  return "\n".join(lines)


# ========== 套件加载与 CLI ==========

def load_suites(name: str = "all"):
  """
  加载任务套件，返回 [(TaskSuite, runner or None)]。
  runner=None 表示用默认大脑链路；memory 套件用离线 memory_runner。
  """
  from benchmarks.decision_suite import build_suite as build_decision
  from benchmarks.memory_suite import build_suite as build_memory, memory_runner
  from benchmarks.workflow_suite import build_suite as build_workflow
  from benchmarks.external_tools_suite import (
      build_suite as build_external_tools, external_tools_runner,
  )

  registry = {
    "decision": (build_decision(), None),
    "memory": (build_memory(), memory_runner),
    "workflow": (build_workflow(), None),
    "external_tools": (build_external_tools(), external_tools_runner),
  }
  if name == "all":
    return list(registry.values())
  if name not in registry:
    raise ValueError(f"未知套件: {name}（可选 all|decision|memory|workflow|external_tools）")
  return [registry[name]]


def main(argv: Optional[List[str]] = None) -> int:
  """CLI 入口：python -m src.harness.benchmark --suite all [--json out.json] [--baseline] [--live]"""
  parser = argparse.ArgumentParser(
    prog="python -m src.harness.benchmark",
    description="rak-runtime 认知引擎基准测试",
  )
  parser.add_argument("--suite", default="all",
                      choices=["all", "decision", "memory", "workflow", "external_tools"],
                      help="要跑的套件（默认 all）")
  parser.add_argument("--json", metavar="OUT", default=None,
                      help="把报告写入指定 JSON 文件")
  parser.add_argument("--baseline", action="store_true",
                      help="同时跑单发 JSON 基线与 Agent 内核，输出对比表")
  parser.add_argument("--live", action="store_true",
                      help="显式声明活体模式（真实 LLM；默认同样走 run_brain）")
  args = parser.parse_args(argv)

  logging.basicConfig(level=logging.INFO,
                      format="%(asctime)s %(levelname)s %(name)s: %(message)s")
  if args.live:
    os.environ.setdefault("RAK_BENCH_LIVE", "1")
    logger.info("[Bench] 活体模式：将真实调用配置的 LLM（.env 决定）")
  else:
    logger.info("[Bench] 默认模式：仍走 run_brain（LLM 由项目配置决定）")

  suites = load_suites(args.suite)
  json_payload: List[dict] = []
  exit_code = 0

  for suite, runner in suites:
    logger.info("[Bench] 运行套件: %s（%d 任务）", suite.name, len(suite.tasks))
    if args.baseline:
      if runner is not None:
        # 记忆套件不走 LLM 深思路径，基线对比无差异，两边同 runner 跑
        res_a = run_suite(suite, runner=runner)
        res_b = run_suite(suite, runner=runner)
      else:
        res_a = run_suite(suite, runner=run_brain_single_shot,
                          trace_prefix=f"{suite.name}-baseline")
        res_b = run_suite(suite, runner=None, trace_prefix=f"{suite.name}-agent")
      print(compare(suite.name, res_a, res_b))
      json_payload.extend([res_a.to_dict(), res_b.to_dict()])
      if score_suite(res_b)["count"]["ok"] == 0:
        exit_code = 1
    else:
      res = run_suite(suite, runner=runner, trace_prefix=suite.name)
      print(report(res, fmt="text"))
      json_payload.append({**res.to_dict(), "scores": score_suite(res)})
      if score_suite(res)["count"]["ok"] == 0:
        exit_code = 1

  if args.json:
    with open(args.json, "w", encoding="utf-8") as f:
      json.dump(json_payload, f, ensure_ascii=False, indent=2, default=str)
    logger.info("[Bench] JSON 报告已写入: %s", args.json)

  return exit_code


if __name__ == "__main__":
  raise SystemExit(main())
