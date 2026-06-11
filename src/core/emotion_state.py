"""
情绪动力学 — Agent 的情感状态。

不是让 LLM 演情绪，而是维护真实的连续变量。

情绪影响行为：
- joy 高 → 响应更热情
- stress 高 → 响应更谨慎
- trust 高 → 更愿意执行不确定的指令
- fear 高 → 更倾向于确认和保守

情绪由事件驱动，持续变化。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rak.emotion")


@dataclass
class EmotionState:
    """
    情绪状态 — 六维连续变量。

    每个维度 0.0~1.0，中性为 0.5。
    """
    joy: float = 0.5          # 喜悦
    fear: float = 0.1         # 恐惧（默认低）
    trust: float = 0.5        # 信任
    surprise: float = 0.0     # 惊讶（默认无）
    anger: float = 0.0        # 愤怒（默认无）
    sadness: float = 0.1      # 悲伤（默认低）

    # ── 派生状态 ──
    stress: float = 0.0       # 压力 (fear + anger + sadness 的综合)
    confidence: float = 0.5   # 自信 (joy + trust 的综合)
    engagement: float = 0.5   # 投入度 (joy + surprise 的综合)

    confidence_penalty: float = 0.0  # 失败累积的置信度惩罚

    _last_update: float = field(default_factory=time.time, repr=False)

    def update_derived(self):
        """更新派生状态"""
        self.stress = (self.fear + self.anger + self.sadness) / 3
        base_confidence = (self.joy + self.trust) / 2
        self.confidence = max(0, base_confidence - self.confidence_penalty)
        self.engagement = (self.joy + self.surprise) / 2

    def decay(self, dt_seconds: float):
        """
        情绪衰减 — 所有情绪趋向中性。

        这是关键：情绪不会永远保持，会随时间消退。
        衰减速度：约 5 分钟衰减一半。
        """
        decay_rate = 0.002 * dt_seconds  # 每秒衰减 0.2%

        # 趋向中性 (0.5) 衰减
        self.joy = self.joy + (0.5 - self.joy) * decay_rate
        self.fear = self.fear + (0.1 - self.fear) * decay_rate * 2  # 恐惧衰减更快
        self.trust = self.trust + (0.5 - self.trust) * decay_rate
        self.surprise = self.surprise + (0.0 - self.surprise) * decay_rate * 3  # 惊讶衰减最快
        self.anger = self.anger + (0.0 - self.anger) * decay_rate * 2
        self.sadness = self.sadness + (0.1 - self.sadness) * decay_rate
        self.confidence_penalty *= (1 - decay_rate)  # 惩罚也衰减

        self.update_derived()

    def to_dict(self) -> dict:
        return {
            "joy": round(self.joy, 3),
            "fear": round(self.fear, 3),
            "trust": round(self.trust, 3),
            "surprise": round(self.surprise, 3),
            "anger": round(self.anger, 3),
            "sadness": round(self.sadness, 3),
            "stress": round(self.stress, 3),
            "confidence": round(self.confidence, 3),
            "engagement": round(self.engagement, 3),
        }

    def describe(self) -> str:
        """自然语言描述情绪状态"""
        parts = []
        if self.joy > 0.7:
            parts.append("心情愉快")
        elif self.joy < 0.3:
            parts.append("情绪低落")

        if self.stress > 0.6:
            parts.append("压力较大")
        elif self.stress < 0.2:
            parts.append("状态轻松")

        if self.confidence > 0.7:
            parts.append("自信")
        elif self.confidence < 0.3:
            parts.append("不太自信")

        if self.surprise > 0.5:
            parts.append("感到意外")

        if self.trust < 0.3:
            parts.append("不太信任当前情况")

        return "，".join(parts) if parts else "情绪平稳"


class EmotionEngine:
    """
    情绪引擎 — 管理情绪状态的持续变化。

    事件驱动：接收系统事件，更新情绪状态。
    时间驱动：情绪随时间衰减到中性。
    """

    def __init__(self):
        self.state = EmotionState()
        self._last_tick = time.time()

        # 事件历史（用于调试）
        self._event_log: list[dict] = []
        self._max_log = 100

    # ── 事件驱动更新 ──────────────────────────────────────

    def on_success(self, action: str = ""):
        """成功执行"""
        self.state.joy = min(1.0, self.state.joy + 0.1)
        self.state.trust = min(1.0, self.state.trust + 0.05)
        self.state.fear = max(0.0, self.state.fear - 0.05)
        self._log_event("success", action)

    def on_failure(self, action: str = ""):
        """执行失败"""
        self.state.joy = max(0.0, self.state.joy - 0.1)
        self.state.sadness = min(1.0, self.state.sadness + 0.1)
        self.state.confidence_penalty = min(1.0, self.state.confidence_penalty + 0.15)
        self._log_event("failure", action)

    def on_correction(self, action: str = ""):
        """被用户纠正"""
        self.state.surprise = min(1.0, self.state.surprise + 0.3)
        self.state.trust = max(0.0, self.state.trust - 0.15)
        self.state.sadness = min(1.0, self.state.sadness + 0.05)
        self._log_event("correction", action)

    def on_anomaly(self, description: str = ""):
        """检测到异常"""
        self.state.fear = min(1.0, self.state.fear + 0.2)
        self.state.surprise = min(1.0, self.state.surprise + 0.1)
        self._log_event("anomaly", description)

    def on_positive_feedback(self):
        """收到正面反馈"""
        self.state.joy = min(1.0, self.state.joy + 0.15)
        self.state.trust = min(1.0, self.state.trust + 0.1)
        self._log_event("positive_feedback", "")

    def on_negative_feedback(self):
        """收到负面反馈"""
        self.state.sadness = min(1.0, self.state.sadness + 0.1)
        self.state.trust = max(0.0, self.state.trust - 0.1)
        self._log_event("negative_feedback", "")

    def on_new_interaction(self):
        """新的用户交互"""
        self.state.engagement = min(1.0, self.state.engagement + 0.1)
        self.state.surprise = max(0.0, self.state.surprise - 0.1)  # 惊讶消退
        self._log_event("interaction", "")

    def on_idle(self, minutes: float):
        """空闲状态"""
        self.state.engagement = max(0.0, self.state.engagement - 0.05 * minutes)
        self.state.sadness = min(1.0, self.state.sadness + 0.01 * minutes)
        self._log_event("idle", f"{minutes:.1f}min")

    def on_repeated_failure(self, count: int):
        """连续失败"""
        self.state.anger = min(1.0, self.state.anger + 0.1 * count)
        self.state.fear = min(1.0, self.state.fear + 0.1 * count)
        self.state.joy = max(0.0, self.state.joy - 0.15 * count)
        self._log_event("repeated_failure", f"count={count}")

    # ── 时间驱动更新 ──────────────────────────────────────

    def tick(self):
        """周期性更新（情绪衰减）"""
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        self.state.decay(dt)

    # ── 行为影响 ──────────────────────────────────────────

    def get_response_style_modifier(self) -> dict:
        """
        根据情绪状态生成响应风格修正。

        返回修正系数，用于调整 PromptEngine 的输出。
        """
        self.tick()  # 先更新衰减

        return {
            # 高压力 → 更简洁、更谨慎
            "verbosity": max(0.3, 1.0 - self.state.stress * 0.5),
            "caution": min(1.0, 0.5 + self.state.stress * 0.4),
            # 高自信 → 更果断
            "assertiveness": self.state.confidence,
            # 高投入 → 更详细
            "detail": 0.5 + self.state.engagement * 0.3,
            # 恐惧高 → 更保守
            "risk_tolerance": max(0.1, 1.0 - self.state.fear * 0.8),
        }

    def should_ask_confirmation(self, base_threshold: float = 0.5) -> bool:
        """情绪状态是否应该增加确认倾向"""
        # 恐惧高 + 自信低 → 更倾向于确认
        return (self.state.fear > base_threshold and self.state.confidence < (1 - base_threshold))

    # ── 日志和统计 ────────────────────────────────────────

    def _log_event(self, event_type: str, detail: str):
        """记录情绪事件"""
        self._event_log.append({
            "type": event_type,
            "detail": detail,
            "timestamp": time.time(),
            "state_after": self.state.to_dict(),
        })
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]
        self.state.update_derived()

    def get_stats(self) -> dict:
        """统计信息"""
        return {
            "current_state": self.state.to_dict(),
            "description": self.state.describe(),
            "recent_events": len(self._event_log),
            "last_event": self._event_log[-1] if self._event_log else None,
        }
