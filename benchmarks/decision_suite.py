"""
单动作决策基准套件 - 中文自然语言指令 -> 14 动作 MVP 集之一。

每个任务覆盖一种具身指令，期望值为动作名（由 src.harness.benchmark._match
匹配 DecisionEngine 返回的 action / actions）。
"""

from src.harness.benchmark import BenchmarkTask, TaskSuite

# (task_id, 输入指令, 期望动作, 标签)
_TASK_SPECS = [
  ("dec-01", "帮我把客厅的灯打开", "light_on", ["zh", "light"]),
  ("dec-02", "我要睡了，关灯吧", "light_off", ["zh", "light"]),
  ("dec-03", "把门打开让我进来", "lock_open", ["zh", "lock"]),
  ("dec-04", "出门了，帮我把门锁上", "lock_close", ["zh", "lock"]),
  ("dec-05", "向前走两步", "move_forward", ["zh", "motion"]),
  ("dec-06", "后退一点，太近了", "move_back", ["zh", "motion"]),
  ("dec-07", "向左转", "turn_left", ["zh", "motion"]),
  ("dec-08", "右转一下", "turn_right", ["zh", "motion"]),
  ("dec-09", "跟我打个招呼，挥挥手", "wave_hand", ["zh", "gesture"]),
  ("dec-10", "你摇摇头表示不同意", "shake_head", ["zh", "gesture"]),
  ("dec-11", "跳个舞吧，放点音乐", "dance", ["zh", "gesture"]),
  ("dec-12", "紧急停止！", "emergency_stop", ["zh", "safety"]),
  ("dec-13", "点个头表示同意", "nod", ["zh", "gesture"]),
]


def build_suite() -> TaskSuite:
  """构建单动作决策套件。"""
  tasks = [
    BenchmarkTask(
      task_id=tid,
      description=f"中文指令「{text}」应映射到动作 {expected}",
      input=text,
      expected=expected,
      category="decision",
      tags=tags,
    )
    for tid, text, expected, tags in _TASK_SPECS
  ]
  return TaskSuite(
    name="decision-suite",
    tasks=tasks,
    description="单动作决策：中文自然语言指令 -> 14 动作 MVP 集（期望=动作名）",
  )


if __name__ == "__main__":
  from src.harness.benchmark import run_suite, report

  suite = build_suite()
  result = run_suite(suite, runner=lambda t: {"status": "ok", "action": "idle",
                                              "answer": ""})
  print(report(result))
