"""
需求引擎 — Agent 的内部驱动力。

生命体不是等待用户指令，而是有自己的需求。

需求来自真实的系统信号，不是随机数：
- learning:    失败率高 → 需要学习
- stability:   纠正频率高 → 需要稳定
- exploration: 缓存命中率低 → 需要扩展知识
- rest:        连续运行时间长 → 需要整合记忆
- social:      长时间无交互 → 需要连接
- safety:      异常检测到问题 → 需要处理

需求驱动行为，不是用户驱动行为。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rak.need_engine")


@dataclass
class NeedVector:
    """需求向量 — 每个维度 0.0~1.0"""
    learning: float = 0.0      # 学习需求
    stability: float = 0.0     # 稳定需求
    exploration: float = 0.0   # 探索需求
    rest: float = 0.0          # 休息需求
    social: float = 0.0        # 社交需求
    safety: float = 0.0        # 安全需求

    def dominant(self) -> tuple[str, float]:
        """最强需求"""
        needs = {
            "learning": self.learning,
            "stability": self.stability,
            "exploration": self.exploration,
            "rest": self.rest,
            "social": self.social,
            "safety": self.safety,
        }
        top = max(needs.items(), key=lambda x: x[1])
        return top

    def to_dict(self) -> dict:
        return {
            "learning": round(self.learning, 3),
            "stability": round(self.stability, 3),
            "exploration": round(self.exploration, 3),
            "rest": round(self.rest, 3),
            "social": round(self.social, 3),
            "safety": round(self.safety, 3),
        }

    def describe(self) -> str:
        """自然语言描述当前需求状态"""
        parts = []
        if self.safety > 0.7:
            parts.append(f"⚠️ 安全需求高 ({self.safety:.0%})")
        if self.learning > 0.7:
            parts.append(f"📚 学习需求高 ({self.learning:.0%})")
        if self.stability > 0.7:
            parts.append(f"🔧 稳定需求高 ({self.stability:.0%})")
        if self.exploration > 0.7:
            parts.append(f"🔍 探索需求高 ({self.exploration:.0%})")
        if self.rest > 0.7:
            parts.append(f"😴 休息需求高 ({self.rest:.0%})")
        if self.social > 0.7:
            parts.append(f"💬 社交需求高 ({self.social:.0%})")
        return " | ".join(parts) if parts else "需求均衡"


class NeedEngine:
    """需求引擎 — 从真实系统信号生成内部需求"""

    def __init__(self):
        self.needs = NeedVector()
        self._last_update = time.time()
        self._session_start = time.time()
        self._last_interaction_time = time.time()

        # 信号源（外部注入）
        self._decision_count = 0
        self._failure_count = 0
        self._correction_count = 0
        self._cache_hit_count = 0
        self._cache_miss_count = 0
        self._anomaly_count = 0

    # ── 信号输入 ──────────────────────────────────────────

    def record_decision(self, success: bool):
        """记录一次决策结果"""
        self._decision_count += 1
        if not success:
            self._failure_count += 1

    def record_correction(self):
        """记录一次用户纠正"""
        self._correction_count += 1

    def record_cache_hit(self):
        """记录缓存命中"""
        self._cache_hit_count += 1

    def record_cache_miss(self):
        """记录缓存未命中"""
        self._cache_miss_count += 1

    def record_interaction(self):
        """记录一次用户交互"""
        self._last_interaction_time = time.time()

    def record_anomaly(self):
        """记录一次异常"""
        self._anomaly_count += 1

    # ── 需求计算 ──────────────────────────────────────────

    def update(self) -> NeedVector:
        """
        根据真实系统信号更新需求向量。

        这是核心方法——需求不是随机生成的，而是从系统状态推导出来的。
        """
        now = time.time()
        dt = now - self._last_update
        self._last_update = now

        # ── 学习需求：基于失败率 ──
        if self._decision_count > 0:
            failure_rate = self._failure_count / self._decision_count
            # 失败率 0% → learning=0, 失败率 30% → learning≈1
            self.needs.learning = min(1.0, failure_rate * 3.3)
        else:
            self.needs.learning = 0.0

        # ── 稳定需求：基于纠正频率 ──
        if self._decision_count > 0:
            correction_rate = self._correction_count / self._decision_count
            # 纠正率 0% → stability=0, 纠正率 20% → stability≈1
            self.needs.stability = min(1.0, correction_rate * 5.0)
        else:
            self.needs.stability = 0.0

        # ── 探索需求：基于缓存未命中率 ──
        total_cache = self._cache_hit_count + self._cache_miss_count
        if total_cache > 5:  # 至少 5 次缓存操作才有意义
            miss_rate = self._cache_miss_count / total_cache
            # 命中率高 → exploration 低, 命中率低 → exploration 高
            self.needs.exploration = min(1.0, miss_rate * 1.5)
        else:
            self.needs.exploration = 0.3  # 默认中等探索欲

        # ── 休息需求：基于连续运行时间 ──
        uptime_hours = (now - self._session_start) / 3600
        # 运行 0h → rest=0, 运行 4h → rest≈1
        self.needs.rest = min(1.0, uptime_hours / 4.0)

        # ── 社交需求：基于无交互时间 ──
        idle_minutes = (now - self._last_interaction_time) / 60
        # 无交互 0min → social=0, 无交互 30min → social≈1
        self.needs.social = min(1.0, idle_minutes / 30.0)

        # ── 安全需求：基于异常数量 ──
        # 异常越多，安全需求越高
        self.needs.safety = min(1.0, self._anomaly_count * 0.3)

        logger.debug("需求更新: %s", self.needs.to_dict())
        return self.needs

    # ── 行为建议 ──────────────────────────────────────────

    def suggest_action(self) -> Optional[dict]:
        """
        基于当前需求建议一个自主行为。

        返回 None 表示没有强烈需求，不需要主动行动。
        返回 dict 表示建议执行某个行为。
        """
        need_name, need_level = self.needs.dominant()

        # 需求不强时不建议行动
        if need_level < 0.6:
            return None

        suggestions = {
            "learning": {
                "action": "reflect_and_learn",
                "description": "反思最近的决策，提取教训",
                "priority": 2,
            },
            "stability": {
                "action": "review_corrections",
                "description": "回顾用户纠正，强化正确行为",
                "priority": 2,
            },
            "exploration": {
                "action": "explore_environment",
                "description": "探索设备状态，扩展知识图谱",
                "priority": 3,
            },
            "rest": {
                "action": "consolidate_memory",
                "description": "整合记忆，清理冗余，巩固经验",
                "priority": 1,
            },
            "social": {
                "action": "reach_out",
                "description": "主动问候用户，提供有用信息",
                "priority": 3,
            },
            "safety": {
                "action": "check_safety",
                "description": "检查设备安全状态，处理异常",
                "priority": 1,
            },
        }

        suggestion = suggestions.get(need_name)
        if suggestion:
            suggestion["need"] = need_name
            suggestion["need_level"] = round(need_level, 3)

        return suggestion

    # ── 接口 ──────────────────────────────────────────────

    def get_needs(self) -> NeedVector:
        """获取当前需求向量"""
        return self.needs

    def get_stats(self) -> dict:
        """统计信息"""
        return {
            "needs": self.needs.to_dict(),
            "dominant_need": self.needs.dominant(),
            "signals": {
                "decision_count": self._decision_count,
                "failure_count": self._failure_count,
                "correction_count": self._correction_count,
                "cache_hit": self._cache_hit_count,
                "cache_miss": self._cache_miss_count,
                "anomaly_count": self._anomaly_count,
            },
            "uptime_hours": round((time.time() - self._session_start) / 3600, 2),
            "idle_minutes": round((time.time() - self._last_interaction_time) / 60, 1),
        }

    def reset_signals(self):
        """重置信号计数器（周期性重置，避免旧数据影响）"""
        self._decision_count = 0
        self._failure_count = 0
        self._correction_count = 0
        self._cache_hit_count = 0
        self._cache_miss_count = 0
        self._anomaly_count = 0
