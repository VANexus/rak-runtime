"""
权限门（Permission Gate）— 大脑动作类工具的 allow/ask/deny 模型。

分级：
- cognitive（读记忆/情绪/需求/设备查询）：默认 allow
- meta（finalize 等内部决策）：默认 allow
- device（execute_action 等物理动作）：默认 allow，但 emergency_stop 永远放行；
  可配置升级为 ask，高压力情绪自动升级 ask
- outbound（MQTT/A2A 派发）：默认 deny，RAK_OUTBOUND=1 才放行

设计来源：Claude Code 的分层权限管线（bypass 免疫的安全路径）、CodeWhale 的
单调授权管线（后续层只能收紧）、CLI-Anything 的 exit-code 语义。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rak.permissions")


@dataclass
class PermissionDecision:
    """权限评估结果"""
    action: str          # 动作/工具名
    category: str        # cognitive / meta / device / outbound
    verdict: str         # allow / ask / deny
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


class PermissionPolicy:
    """权限策略：分类 + 默认判定 + 覆盖规则 + 情绪联动"""

    DEFAULT_CATEGORY = {
        "search_memory": "cognitive", "query_device": "cognitive",
        "get_emotion": "cognitive", "get_needs": "cognitive",
        "get_self_info": "cognitive", "get_graph_stats": "cognitive",
        "reflect": "cognitive", "diffuse_memory": "cognitive",
        "get_inner_thoughts": "cognitive", "get_narrative": "cognitive",
        "get_cognitive_stats": "cognitive", "get_insights": "cognitive",
        "finalize": "meta",
        "execute_action": "device",
        "publish_action": "outbound", "speak": "outbound", "alert": "outbound",
    }

    DEFAULT_VERDICT = {
        "cognitive": "allow",
        "meta": "allow",
        "device": "allow",     # 默认放行；配置/高压力可升级 ask
        "outbound": "allow",   # 机制默认放行，但 RAK_OUTBOUND 门控（未启用 → deny）
    }

    # 物理安全硬约束：永远放行
    ALWAYS_ALLOW = {"emergency_stop"}

    def __init__(self, config: Optional[dict] = None):
        self._category = dict(self.DEFAULT_CATEGORY)
        self._verdict = dict(self.DEFAULT_VERDICT)
        self._overrides: dict[str, str] = {}  # action → verdict（配置）
        if config:
            self.load_config(config)

    def load_config(self, config: dict):
        """加载配置：{"categories": {...}, "actions": {"lock_open": "ask"}}"""
        if "categories" in config:
            self._category.update(config["categories"])
        if "actions" in config:
            for action, verdict in config["actions"].items():
                if verdict in ("allow", "ask", "deny"):
                    self._overrides[action] = verdict

    def categorize(self, action: str) -> str:
        return self._category.get(action, "device")

    def evaluate(self, action: str, context: Optional[dict] = None) -> PermissionDecision:
        """评估动作权限。context 可带 {"stress": 0-1, "confidence": 0-1} 触发情绪联动。"""
        # 1. 物理安全硬约束
        if action in self.ALWAYS_ALLOW:
            return PermissionDecision(action, "device", "allow",
                                      "emergency_stop 永远放行（物理安全）")

        category = self.categorize(action)
        verdict = self._overrides.get(action) or self._verdict.get(category, "ask")
        reason = f"{category} 类动作默认 {verdict}"

        # 2. 情绪联动：高压力 → device 动作升级 ask（CodeWhale 单调：只收紧不放宽）
        context = context or {}
        if (verdict == "allow" and category == "device"
                and context.get("stress", 0) > 0.6):
            verdict, reason = "ask", "高压力（stress>0.6）时物理动作升级为需确认"

        # 3. 出站门控：outbound 必须 RAK_OUTBOUND=1
        if category == "outbound" and os.getenv("RAK_OUTBOUND", "0") != "1":
            verdict, reason = "deny", "出站通道未启用（RAK_OUTBOUND=1 才放行）"

        return PermissionDecision(action, category, verdict, reason)

    def allow(self, action: str):
        self._overrides[action] = "allow"

    def ask(self, action: str):
        self._overrides[action] = "ask"

    def deny(self, action: str):
        self._overrides[action] = "deny"

    def stats(self) -> dict:
        return {
            "categories": dict(self._category),
            "defaults": dict(self._verdict),
            "overrides": dict(self._overrides),
            "always_allow": sorted(self.ALWAYS_ALLOW),
        }


_policy = None


def get_permission_policy() -> PermissionPolicy:
    """懒加载单例"""
    global _policy
    if _policy is None:
        _policy = PermissionPolicy()
    return _policy
