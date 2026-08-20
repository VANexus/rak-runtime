"""
上下文压缩（Compaction）— 会话/记忆上下文接近上限时结构化摘要。

设计借鉴：
- opencode `SUMMARY_TEMPLATE`：Objective / Work State / Next Move / Relevant Files
  → 本实现用 Objective / Work State / Next Move / Relevant Devices（具身版）
- CodeWhale `CompactionLiveState`：压缩后重锚当前连接设备/执行中动作/待审批项
  → 后继 agent 不靠散文重建状态

触发：上下文超预算时；LLM 失败 → 返回 None，调用方截断兜底（不阻断决策）。
"""

import json
import logging
import os
from typing import Optional
from src.core._utils import get_model

logger = logging.getLogger("rak.compaction")

SUMMARY_TEMPLATE = """## Objective
{objective}

## Work State (Completed / Active / Blocked)
{work_state}

## Next Move
{next_move}

## Relevant Devices
{devices}"""


def build_compaction_prompt(memory_context: str, keep_tail: int = 300) -> str:
    """构造压缩提示词：让 LLM 从长上下文中提炼结构化摘要，尾部原文保留"""
    tail = memory_context[-keep_tail:] if len(memory_context) > keep_tail else ""
    return f"""压缩以下上下文为结构化摘要，保留关键事实、未决问题、用户偏好、设备状态。

## 上下文（可能很长）
{memory_context[:8000]}

{f"## 最近内容（原样保留）\n{tail}" if tail else ""}

输出 JSON：
{{
  "objective": "当前任务目标",
  "work_state": "已完成/进行中/阻塞",
  "next_move": "下一步",
  "devices": "涉及设备及状态"
}}"""


def parse_summary(text: str) -> Optional[dict]:
    """解析 LLM 输出的 JSON 摘要（容忍 markdown 代码块）"""
    from src.core._utils import safe_json_parse
    parsed = safe_json_parse(text)
    if isinstance(parsed, dict) and any(
        k in parsed for k in ("objective", "work_state", "next_move", "devices")
    ):
        return parsed
    return None


def compact_context(memory_context: str, max_chars: int = 3000,
                    keep_tail: int = 300) -> Optional[str]:
    """
    上下文超预算时压缩为结构化摘要（保留尾部原文）。

    Returns:
        压缩后的字符串；LLM 不可用/失败返回 None（调用方截断兜底）。
    """
    if not memory_context or len(memory_context) <= max_chars:
        return memory_context

    try:
        from src.core._utils import make_llm_client
        client = make_llm_client(timeout=15.0)
        if client is None:
            return None
        prompt = build_compaction_prompt(memory_context, keep_tail)
        resp = client.messages.create(
            model=get_model(),
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        summary = parse_summary(text)
        if not summary:
            return None
        logger.info("[Compaction] 压缩 %d → %d 字符",
                    len(memory_context), len(json.dumps(summary, ensure_ascii=False)))
        return SUMMARY_TEMPLATE.format(**summary)
    except Exception as e:
        logger.warning("[Compaction] 压缩失败（调用方截断兜底）: %s", e)
        return None
