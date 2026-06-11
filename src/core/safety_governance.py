"""
Safety Governance: LLM 驱动的运行时安全治理

灵感来源：
- VIGIL (arXiv:2512.07094, Dec 2025): 反思式运行时自愈
- Bridging Symbolic Control and Neural Reasoning (arXiv:2511.17673, Nov 2025)

核心思想：安全判断由 LLM 根据上下文动态决策，不写死任何规则。
唯一的硬约束：emergency_stop 永远允许（物理安全）。

LLM 评估的维度：
- 设备当前状态是否允许此操作
- 当前时间是否适合此操作
- 最近的操作历史是否存在矛盾
- 用户的意图是否被正确理解
"""

import json
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SafetyViolation:
    """安全违规记录"""
    action: str
    reason: str
    severity: str  # "block" | "warn"
    timestamp: float = field(default_factory=time.time)


class SafetyGovernance:
    """
    LLM 驱动的安全治理层。

    不写死规则，每次安全检查都由 LLM 根据完整上下文判断。
    """

    def __init__(self):
        self._action_history: List[Tuple[str, str, float]] = []
        self._max_history = 100
        self._device_states: Dict[str, Dict] = {}
        self._violations: List[SafetyViolation] = []
        self._max_violations = 200
        self._llm_client = None

        # 统计
        self._total_checks = 0
        self._total_blocks = 0

    def check(self, action: str, query: str = "",
              device_id: str = None, params: Dict = None) -> Tuple[bool, str]:
        """
        LLM 驱动的安全检查。返回 (allowed, reason)。
        """
        self._total_checks += 1

        # emergency_stop 永远允许（唯一的硬约束）
        if action == "emergency_stop":
            return True, ""

        # 构建安全评估上下文
        context = self._build_context(action, query, device_id, params)

        # LLM 评估
        llm = self._get_llm_client()
        if not llm:
            # LLM 不可用时，默认允许（不阻塞）
            return True, ""

        try:
            response = llm.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=128,
                system="你是安全评估模块。根据上下文判断操作是否安全。只输出 JSON。",
                messages=[{"role": "user", "content": context}],
                extra_body={"thinking": {"type": "disabled"}},
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    break

            parsed = self._parse_json(text)
            if parsed:
                allowed = parsed.get("safe", True)
                reason = parsed.get("reason", "")
                severity = parsed.get("severity", "warn")

                if not allowed:
                    violation = SafetyViolation(
                        action=action, reason=reason, severity=severity,
                    )
                    self._record_violation(violation)
                    self._total_blocks += 1
                    logger.warning("[Safety] LLM 阻止 %s: %s", action, reason)
                    return severity == "block", reason

        except Exception as e:
            logger.warning("[Safety] LLM 评估失败: %s，默认允许", e)

        return True, ""

    def _build_context(self, action: str, query: str,
                        device_id: str, params: Dict) -> str:
        """构建安全评估的完整上下文"""
        import datetime
        now = datetime.datetime.now()

        parts = [f"## 待执行操作\n动作: {action}"]

        if query:
            parts.append(f"用户指令: {query}")
        if device_id:
            parts.append(f"目标设备: {device_id}")
        if params:
            parts.append(f"参数: {json.dumps(params, ensure_ascii=False)}")

        parts.append(f"\n## 当前环境")
        parts.append(f"时间: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')})")

        # 设备状态
        if device_id and device_id in self._device_states:
            state = self._device_states[device_id]
            parts.append(f"设备状态: {json.dumps(state, ensure_ascii=False)}")
        elif self._device_states:
            parts.append("所有设备状态:")
            for did, state in self._device_states.items():
                parts.append(f"  {did}: {json.dumps(state, ensure_ascii=False)}")

        # 最近操作历史
        if self._action_history:
            recent = self._action_history[-10:]
            parts.append("\n## 最近操作历史")
            for a, d, t in recent:
                elapsed = time.time() - t
                parts.append(f"  {elapsed:.0f}秒前: {a} (设备: {d or '未知'})")

        parts.append(f"""
## 评估要求
判断操作 "{action}" 是否安全。考虑：
1. 设备状态是否允许此操作（如已锁定的门不需要再锁）
2. 当前时间是否适合此操作（如深夜噪音）
3. 是否与最近操作矛盾（如刚开灯又关灯）
4. 是否存在重复发送风险
5. 用户意图是否被正确理解

输出 JSON:
{{"safe": true/false, "reason": "原因", "severity": "block/warn"}}""")

        return "\n".join(parts)

    def update_device_state(self, device_id: str, state: Dict):
        """更新设备状态"""
        self._device_states[device_id] = {**state, "updated_at": time.time()}

    def record_action(self, action: str, device_id: str = None):
        """记录已执行的动作"""
        self._action_history.append((action, device_id, time.time()))
        if len(self._action_history) > self._max_history:
            self._action_history = self._action_history[-self._max_history:]

    def learn_from_violation(self, action: str, reason: str):
        """从违规中学习（记录到历史供 LLM 参考）"""
        self._violations.append(SafetyViolation(
            action=action, reason=reason, severity="block",
        ))
        if len(self._violations) > self._max_violations:
            self._violations = self._violations[-self._max_violations:]

    def _record_violation(self, violation: SafetyViolation):
        self._violations.append(violation)
        if len(self._violations) > self._max_violations:
            self._violations = self._violations[-self._max_violations:]

    def _parse_json(self, text: str) -> Optional[Dict]:
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def _get_llm_client(self):
        if self._llm_client is None:
            try:
                import anthropic
                import os
                self._llm_client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
                    base_url=os.getenv(
                        "ANTHROPIC_BASE_URL",
                        "https://token-plan-cn.xiaomimimo.com/anthropic",
                    ),
                    timeout=5.0,
                )
            except Exception as e:
                logger.warning("[Safety] LLM 初始化失败: %s", e)
        return self._llm_client

    def get_stats(self) -> Dict:
        return {
            "total_checks": self._total_checks,
            "total_blocks": self._total_blocks,
            "block_rate": f"{self._total_blocks / max(self._total_checks, 1):.1%}",
            "recent_violations": [
                {"action": v.action, "reason": v.reason[:50]}
                for v in self._violations[-5:]
            ],
        }
