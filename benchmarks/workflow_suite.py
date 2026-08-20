"""
复合指令基准套件 - 多步骤命令的动作分解。

每个任务是"先 A 再 B"式复合指令，期望值为 "action_a|action_b" 多段：
DecisionEngine 检测到复合指令后走 decide_from_text 分解路径，返回
actions 列表；_match 要求每个期望动作都出现在 action/actions 里。
"""

from src.harness.benchmark import BenchmarkTask, TaskSuite

# (task_id, 复合指令, 期望动作序列, 标签)
_TASK_SPECS = [
  ("wf-01", "先开灯，然后把门锁上", "light_on|lock_close", ["compound", "security"]),
  ("wf-02", "先关灯再后退", "light_off|move_back", ["compound", "motion"]),
  ("wf-03", "左转然后向前走", "turn_left|move_forward", ["compound", "motion"]),
  ("wf-04", "挥挥手并点点头", "wave_hand|nod", ["compound", "gesture"]),
  ("wf-05", "跳完舞以后把灯关掉", "dance|light_off", ["compound", "gesture"]),
  ("wf-06", "先右转再后退", "turn_right|move_back", ["compound", "motion"]),
  ("wf-07", "把门打开然后前进", "lock_open|move_forward", ["compound", "motion"]),
  ("wf-08", "先摇头再点头", "shake_head|nod", ["compound", "gesture"]),
]


def build_suite() -> TaskSuite:
  """构建复合指令套件。"""
  tasks = [
    BenchmarkTask(
      task_id=tid,
      description=f"复合指令「{text}」应分解出动作序列 {expected.replace('|', ' -> ')}",
      input=text,
      expected=expected,
      category="workflow",
      tags=tags,
    )
    for tid, text, expected, tags in _TASK_SPECS
  ]
  return TaskSuite(
    name="workflow-suite",
    tasks=tasks,
    description="复合指令：多步骤命令分解（期望=多动作，'|' 分隔，全部命中才算过）",
  )
