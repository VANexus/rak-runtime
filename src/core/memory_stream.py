"""
联想记忆流 — 记忆不是数据库，是流动的。

人脑的记忆不是"查询→返回"，而是：
- 看到一个东西
- 想起另一件事
- 联想到上个月的经历
- 突然产生一个洞察

这个模块让记忆持续流动，即使没有用户输入也在联想。
"""

import logging
import random
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable

logger = logging.getLogger("rak.memory_stream")


@dataclass
class Association:
    """一次联想"""
    source_memory: str       # 触发联想的记忆
    associated_memory: str   # 联想到的记忆
    similarity: float        # 相似度
    insight: str = ""        # 产生的洞察（如果有）
    timestamp: float = field(default_factory=time.time)


@dataclass
class Insight:
    """从联想中涌现的洞察"""
    content: str             # 洞察内容
    source_memories: list    # 来源记忆
    confidence: float        # 置信度
    timestamp: float = field(default_factory=time.time)
    used: bool = False       # 是否已被使用


class MemoryStream:
    """
    联想记忆流 — 持续运行的联想引擎。

    即使没有用户输入，也在后台持续：
    1. 随机激活一条近期记忆
    2. 通过语义相似度联想相关记忆
    3. 如果发现有趣的关联，记录为洞察
    4. 洞察可以注入到决策中
    """

    def __init__(self, memory_engine=None):
        self._memory_engine = memory_engine
        self._running = False
        self._task: Optional[threading.Thread] = None
        self._interval = 60  # 联想间隔（秒）

        # 联想历史
        self._associations: list[Association] = []
        self._max_associations = 200

        # 涌现的洞察
        self._insights: list[Insight] = []
        self._max_insights = 50

        # 最近激活的记忆（用于避免重复联想）
        self._recent_activations: list[str] = []
        self._max_recent = 20

        # 统计
        self._stats = {
            "total_ticks": 0,
            "associations_made": 0,
            "insights_generated": 0,
            "insights_used": 0,
        }

    # ── 生命周期 ──────────────────────────────────────────

    def set_memory_engine(self, memory_engine):
        """设置记忆引擎（延迟注入）"""
        self._memory_engine = memory_engine

    def start(self):
        """启动联想流"""
        if self._running:
            return
        self._running = True
        self._task = threading.Thread(target=self._run_loop, daemon=True)
        self._task.start()
        logger.info("联想记忆流已启动（间隔 %ds）", self._interval)

    def stop(self):
        """停止联想流"""
        self._running = False
        logger.info("联想记忆流已停止")

    # ── 主循环 ────────────────────────────────────────────

    def _run_loop(self):
        """后台联想循环"""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("联想流异常: %s", e)
            time.sleep(self._interval)

    def _tick(self):
        """单次联想周期"""
        self._stats["total_ticks"] += 1

        if not self._memory_engine:
            return

        # 1. 随机激活一条近期记忆
        recent = self._get_random_recent_memory()
        if not recent:
            return

        # 避免重复激活
        if recent in self._recent_activations:
            return
        self._recent_activations.append(recent)
        if len(self._recent_activations) > self._max_recent:
            self._recent_activations = self._recent_activations[-self._max_recent:]

        # 2. 联想：用这条记忆去搜索相关记忆
        try:
            related = self._memory_engine.recall(recent, top_k=3)
        except Exception:
            return

        if not related:
            return

        # 3. 检查是否有有趣的关联
        for r in related:
            if r.entry.content == recent:
                continue
            if r.similarity < 0.5:
                continue

            association = Association(
                source_memory=recent,
                associated_memory=r.entry.content,
                similarity=r.similarity,
            )

            # 4. 如果关联足够强，生成洞察
            if r.similarity > 0.7:
                insight = self._generate_insight(recent, r.entry.content, r.similarity)
                if insight:
                    association.insight = insight.content
                    self._insights.append(insight)
                    if len(self._insights) > self._max_insights:
                        self._insights = self._insights[-self._max_insights:]
                    self._stats["insights_generated"] += 1
                    logger.info("联想洞察: %s", insight.content[:80])

            self._associations.append(association)
            self._stats["associations_made"] += 1

        # 截断历史
        if len(self._associations) > self._max_associations:
            self._associations = self._associations[-self._max_associations:]

    # ── 洞察生成 ──────────────────────────────────────────

    def _generate_insight(self, memory_a: str, memory_b: str,
                          similarity: float) -> Optional[Insight]:
        """从两条关联记忆中生成洞察"""
        # 简单规则：如果两条记忆都涉及同一个设备但不同结果，可能是教训
        # 更复杂的洞察生成可以调用 LLM，但这里先用规则

        # 检查是否包含成功/失败模式
        has_success = any(w in memory_a + memory_b for w in ["成功", "ok", "正确"])
        has_failure = any(w in memory_a + memory_b for w in ["失败", "error", "错误", "纠正"])

        if has_success and has_failure:
            return Insight(
                content=f"发现成功/失败对比模式: [{memory_a[:50]}] vs [{memory_b[:50]}]",
                source_memories=[memory_a, memory_b],
                confidence=similarity,
            )

        # 检查是否涉及同一设备不同动作
        devices = ["light", "lock", "motor", "servo", "灯", "锁"]
        mentioned = [d for d in devices if d in memory_a.lower() + memory_b.lower()]
        if len(set(mentioned)) == 1 and mentioned:
            return Insight(
                content=f"关于 {mentioned[0]} 的记忆关联: [{memory_a[:40]}] ↔ [{memory_b[:40]}]",
                source_memories=[memory_a, memory_b],
                confidence=similarity * 0.8,
            )

        return None

    # ── 记忆获取 ──────────────────────────────────────────

    def _get_random_recent_memory(self) -> Optional[str]:
        """随机获取一条近期记忆"""
        try:
            # 先尝试从工作记忆获取
            if hasattr(self._memory_engine, '_working_memory'):
                wm = self._memory_engine._working_memory
                if wm:
                    return random.choice(wm).content

            # 再尝试从长期记忆获取最近的
            if hasattr(self._memory_engine, '_ltm') and self._memory_engine._ltm:
                entries = self._memory_engine._ltm._get_all_entries()
                if entries:
                    # 优先选择最近的
                    recent = sorted(entries, key=lambda e: e.last_accessed, reverse=True)[:20]
                    return random.choice(recent).content
        except Exception:
            pass
        return None

    # ── 洞察消费 ──────────────────────────────────────────

    def get_unused_insight(self) -> Optional[Insight]:
        """获取一条未使用的洞察"""
        for insight in self._insights:
            if not insight.used:
                insight.used = True
                self._stats["insights_used"] += 1
                return insight
        return None

    def get_recent_insights(self, count: int = 5) -> list[dict]:
        """获取最近的洞察"""
        return [
            {
                "content": i.content,
                "confidence": round(i.confidence, 3),
                "used": i.used,
                "timestamp": i.timestamp,
            }
            for i in self._insights[-count:]
        ]

    def inject_memory(self, content: str):
        """外部注入一条记忆到联想池"""
        self._recent_activations.append(content)
        if len(self._recent_activations) > self._max_recent:
            self._recent_activations = self._recent_activations[-self._max_recent:]

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "running": self._running,
            "associations_count": len(self._associations),
            "insights_count": len(self._insights),
            "unused_insights": sum(1 for i in self._insights if not i.used),
        }
