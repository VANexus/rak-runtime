"""
跨会话记忆基准套件 - 验证超长期记忆（SuperMemory）的写入与回忆。

流程（模拟两个会话）：
- 会话 1（seed）：把 SEED_FACTS 写入一个临时 SQLite 记忆库
- 会话 2（memory_runner）：新开一个 SuperMemory 连接（模拟进程重启后的新会话），
  用任务查询召回，验证种子事实能被回忆 -> 证明跨会话持久化

memory_runner 不依赖 LLM（离线安全）；brain_memory_runner 为可选的活体
路径：把种子记忆注入全局单例后走完整大脑链路（DecisionEngine 会通过
_build_memory_context 注入超长期记忆），仅在手动 --live 场景使用。
"""

import logging
import os
import tempfile
import threading

from src.harness.benchmark import BenchmarkTask, TaskSuite

logger = logging.getLogger(__name__)

_SCOPE = "bench"

# 种子事实：会话 1 写入，会话 2 验证可召回
SEED_FACTS = [
  "用户每天早上 7 点开灯",
  "用户喜欢在晚上听音乐",
  "门锁在 22:00 自动锁定",
  "用户的生日是 3 月 15 日",
  "用户家里养了一只叫小白的猫",
  "用户偏好简洁的中文回复",
  "客厅的空调温度通常设定为 26 度",
  "用户周末喜欢打扫房间",
]

# (task_id, 查询, 期望子串=种子事实的片段, 标签)
_TASK_SPECS = [
  ("mem-01", "早上 开灯 的 习惯", "早上 7 点开灯", ["habit", "time"]),
  ("mem-02", "晚上 听音乐 的 喜好", "喜欢在晚上听音乐", ["preference"]),
  ("mem-03", "门锁 自动 锁定 时间", "22:00 自动锁定", ["device", "time"]),
  ("mem-04", "生日 是 哪一天", "3 月 15 日", ["profile"]),
  ("mem-05", "家里 养 的 宠物", "小白", ["profile", "pet"]),
  ("mem-06", "回复 风格 的 偏好", "简洁", ["preference", "style"]),
  ("mem-07", "客厅 空调 温度 设定", "26 度", ["device", "env"]),
  ("mem-08", "周末 通常 做 什么", "打扫房间", ["habit"]),
]

_MEM_STATE = {"db_path": None}
_MEM_LOCK = threading.Lock()


def _seed_into(db_path: str) -> None:
  """把全部种子事实写入指定记忆库（幂等，可重复调用）。"""
  from src.core.memory_longterm import SuperMemory

  mem = SuperMemory(db_path=db_path)
  try:
    for fact in SEED_FACTS:
      mem.remember(fact, memory_type="semantic", scope=_SCOPE, importance=0.8)
  finally:
    mem.close()


def _ensure_seeded() -> str:
  """懒加载共享临时记忆库（只播种一次），返回 db 路径。"""
  with _MEM_LOCK:
    if _MEM_STATE["db_path"] is None:
      db_path = os.path.join(
        tempfile.mkdtemp(prefix="rak-bench-mem-"), "super_long.db")
      try:
        _seed_into(db_path)
        _MEM_STATE["db_path"] = db_path
        logger.info("[Bench-Mem] 种子记忆库已就绪: %s", db_path)
      except Exception as e:  # 优雅降级：播种失败不崩溃
        logger.warning("[Bench-Mem] 种子记忆库初始化失败: %s", e)
    return _MEM_STATE["db_path"]


def reset_seeded_state() -> None:
  """重置共享状态（测试用：下次调用会重新播种新临时库）。"""
  with _MEM_LOCK:
    _MEM_STATE["db_path"] = None


def memory_runner(text: str, db_path: str = None) -> dict:
  """
  离线记忆 runner：新开 SuperMemory 连接（模拟新会话）召回种子事实。

  返回与大脑决策同构的 dict：answer 为命中片段拼接，
  expected 子串匹配逻辑由 src.harness.benchmark._match 完成。
  """
  from src.core.memory_longterm import SuperMemory

  if db_path is None:
    db_path = _ensure_seeded()
  else:
    _seed_into(db_path)  # 幂等：显式路径也可以重复播种

  hits = []
  try:
    mem = SuperMemory(db_path=db_path)
    try:
      hits = mem.recall(text, scope=_SCOPE, top_k=5)
    finally:
      mem.close()
  except Exception as e:  # 优雅降级：记忆失败返回空结果而非崩溃
    logger.warning("[Bench-Mem] 召回失败: %s", e)
    return {"status": "error", "error_code": "MEMORY_RECALL_FAILED",
            "error_message": str(e), "action": "", "answer": "",
            "hits": [], "tool_events": 0}

  answer = "；".join(h.content for h in hits)
  return {
    "status": "ok",
    "action": "idle",
    "answer": answer,
    "hits": [h.to_dict() for h in hits],
    "tool_events": 1,  # 一次 recall 视作一次工具调用
  }


def brain_memory_runner(text: str, db_path: str = None) -> dict:
  """
  活体记忆 runner（需 LLM）：把种子记忆注入全局单例，走完整大脑链路。

  DecisionEngine._build_memory_context 会读取超长期记忆单例，注入提示词，
  期望种子事实出现在最终 answer 中。用完恢复原单例，不污染线上状态。
  """
  from src.core.memory_longterm import SuperMemory
  from src.harness.benchmark import run_brain

  db_path = db_path or _ensure_seeded()
  _seed_into(db_path)
  seeded = SuperMemory(db_path=db_path)

  import src.core.decision_engine as de
  import src.core.memory_longterm as mlt
  saved_mlt = mlt._instance
  saved_de = getattr(de, "_super_memory", None)
  mlt._instance = seeded
  if hasattr(de, "_super_memory"):
    de._super_memory = seeded
  try:
    return run_brain(text, trace_id="bench-memory-live")
  finally:
    mlt._instance = saved_mlt
    if hasattr(de, "_super_memory"):
      de._super_memory = saved_de
    try:
      seeded.close()
    except Exception:
      pass


def build_suite() -> TaskSuite:
  """构建跨会话记忆套件。"""
  tasks = [
    BenchmarkTask(
      task_id=tid,
      description="先写入一条事实，再在后续查询中验证它能被回忆",
      input=query,
      expected=expected,
      category="memory",
      tags=tags + ["cross-session"],
    )
    for tid, query, expected, tags in _TASK_SPECS
  ]
  return TaskSuite(
    name="memory-suite",
    tasks=tasks,
    description="跨会话记忆：会话 1 写入种子事实，会话 2 召回验证（期望=事实子串）",
  )
