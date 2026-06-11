"""
主动智能引擎 — 不再只是被动响应。

核心能力：
1. 异常监控：持续检查设备状态，发现异常主动告警
2. 需求预测：基于用户行为模式预测下一步需求
3. 自我改进：发现知识盲区时触发学习
4. 环境感知：结合时间、设备状态推断场景

设计哲学：
- 主动 ≠ 烦人。只在真正有价值时才打扰用户
- 每次主动干预都必须有明确的理由
- 用户可以关闭主动性，回到纯被动模式
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("rak.proactive")


# ── 数据结构 ──────────────────────────────────────────────

class AlertLevel:
    """告警等级"""
    CRITICAL = "critical"   # 必须立即通知：门锁异常、安全问题
    WARNING = "warning"     # 建议通知：电量低、设备离线
    INFO = "info"           # 可以不通知：状态变化、模式识别


@dataclass
class ProactiveAlert:
    """主动告警"""
    level: str
    title: str
    message: str
    source: str             # 来源: "anomaly" / "prediction" / "learning"
    action_suggested: str   # 建议的动作
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False


@dataclass
class PredictedNeed:
    """预测的用户需求"""
    action: str             # 建议的动作
    device: str             # 目标设备
    confidence: float       # 预测置信度
    reasoning: str          # 预测依据
    trigger_time: float     # 预计触发时间


# ── 核心类 ────────────────────────────────────────────────

class ProactiveEngine:
    """主动智能引擎"""

    def __init__(self):
        self._enabled = True
        self._alerts: list[ProactiveAlert] = []
        self._max_alerts = 100
        self._check_interval = 30  # 秒
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 外部依赖（运行时注入）
        self._world_model = None
        self._user_model = None
        self._learning_loop = None

        # 回调
        self._alert_callback: Optional[Callable[[ProactiveAlert], Awaitable[None]]] = None

        # 统计
        self._stats = {
            "total_checks": 0,
            "anomalies_detected": 0,
            "needs_predicted": 0,
            "alerts_sent": 0,
        }

    # ── 生命周期 ──────────────────────────────────────────

    def set_dependencies(self, world_model=None, user_model=None,
                         learning_loop=None):
        """注入依赖模块"""
        self._world_model = world_model
        self._user_model = user_model
        self._learning_loop = learning_loop

    def set_alert_callback(self, callback: Callable[[ProactiveAlert], Awaitable[None]]):
        """设置告警回调（用于推送到 go-kernel）"""
        self._alert_callback = callback

    async def start(self):
        """启动主动监控循环"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("主动智能引擎已启动（检查间隔 %ds）", self._check_interval)

    async def stop(self):
        """停止监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("主动智能引擎已停止")

    # ── 主监控循环 ────────────────────────────────────────

    async def _monitor_loop(self):
        """持续监控循环"""
        while self._running:
            try:
                await self._check_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("主动监控异常: %s", e)
            await asyncio.sleep(self._check_interval)

    async def _check_cycle(self):
        """单次检查周期"""
        self._stats["total_checks"] += 1

        # 1. 检查异常
        anomalies = await self._check_anomalies()
        for anomaly in anomalies:
            await self._process_alert(anomaly)

        # 2. 预测需求
        needs = await self._predict_needs()
        for need in needs:
            await self._process_predicted_need(need)

        # 3. 检查学习机会
        if self._learning_loop:
            insights = self._learning_loop.get_recent_insights()
            if insights:
                logger.debug("学习洞察已更新: %d 条", len(insights))

    # ── 异常检测 ──────────────────────────────────────────

    async def _check_anomalies(self) -> list[ProactiveAlert]:
        """检查设备异常"""
        alerts = []
        if not self._world_model:
            return alerts

        anomalies = self._world_model.detect_all_anomalies()
        for anomaly in anomalies:
            device = anomaly.get("device_id", "未知设备")
            issue = anomaly.get("issue", "未知问题")

            # 确定告警等级
            if "安全" in issue or "入侵" in issue or "异常" in issue:
                level = AlertLevel.CRITICAL
            elif "离线" in issue or "电量" in issue or "低" in issue:
                level = AlertLevel.WARNING
            else:
                level = AlertLevel.INFO

            alert = ProactiveAlert(
                level=level,
                title=f"设备异常: {device}",
                message=issue,
                source="anomaly",
                action_suggested=self._suggest_action_for_anomaly(anomaly),
            )
            alerts.append(alert)
            self._stats["anomalies_detected"] += 1

        return alerts

    def _suggest_action_for_anomaly(self, anomaly: dict) -> str:
        """根据异常类型建议动作"""
        issue = anomaly.get("issue", "")
        if "电量" in issue and "低" in issue:
            return "建议更换电池"
        if "离线" in issue:
            return "检查设备电源和网络连接"
        if "异常状态" in issue:
            return "建议检查设备是否正常工作"
        return "请检查设备状态"

    # ── 需求预测 ──────────────────────────────────────────

    async def _predict_needs(self) -> list[PredictedNeed]:
        """基于用户行为模式预测需求"""
        needs = []
        if not self._user_model:
            return needs

        import datetime
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")

        # 检查时间规律
        for routine_time, actions in self._user_model.behavior.time_routines.items():
            diff = self._time_diff_minutes(current_time, routine_time)

            # 提前 5 分钟准备
            if 0 < diff <= 5:
                for action in actions:
                    need = PredictedNeed(
                        action=action,
                        device=action,
                        confidence=0.7,
                        reasoning=f"用户通常在 {routine_time} 执行 {action}",
                        trigger_time=time.time() + diff * 60,
                    )
                    needs.append(need)
                    self._stats["needs_predicted"] += 1

        return needs

    async def _process_predicted_need(self, need: PredictedNeed):
        """处理预测的需求"""
        if need.confidence < 0.6:
            return

        alert = ProactiveAlert(
            level=AlertLevel.INFO,
            title="需求预测",
            message=f"用户通常在现在执行 {need.action}（置信度 {need.confidence:.0%}）",
            source="prediction",
            action_suggested=need.action,
        )
        await self._process_alert(alert)

    # ── 告警处理 ──────────────────────────────────────────

    async def _process_alert(self, alert: ProactiveAlert):
        """处理告警 — 决定是否通知用户"""
        if not self._enabled:
            return

        # 存储告警
        self._alerts.append(alert)
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

        # 只有 WARNING 和 CRITICAL 才通知用户
        if alert.level in (AlertLevel.CRITICAL, AlertLevel.WARNING):
            if self._alert_callback:
                try:
                    await self._alert_callback(alert)
                    self._stats["alerts_sent"] += 1
                except Exception as e:
                    logger.error("告警回调失败: %s", e)
            else:
                logger.warning("告警[%s] %s: %s", alert.level, alert.title, alert.message)
        else:
            logger.info("信息[%s] %s: %s", alert.level, alert.title, alert.message)

    # ── 外部接口 ──────────────────────────────────────────

    def enable(self):
        """启用主动智能"""
        self._enabled = True
        logger.info("主动智能已启用")

    def disable(self):
        """禁用主动智能（回到纯被动模式）"""
        self._enabled = False
        logger.info("主动智能已禁用")

    def acknowledge_alert(self, alert_index: int) -> bool:
        """确认告警"""
        if 0 <= alert_index < len(self._alerts):
            self._alerts[alert_index].acknowledged = True
            return True
        return False

    def get_pending_alerts(self) -> list[dict]:
        """获取未确认的告警"""
        return [
            {
                "level": a.level,
                "title": a.title,
                "message": a.message,
                "source": a.source,
                "action_suggested": a.action_suggested,
                "timestamp": a.timestamp,
            }
            for a in self._alerts if not a.acknowledged
        ]

    def get_stats(self) -> dict:
        """获取统计"""
        return {
            **self._stats,
            "enabled": self._enabled,
            "pending_alerts": sum(1 for a in self._alerts if not a.acknowledged),
            "total_alerts": len(self._alerts),
        }

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _time_diff_minutes(t1: str, t2: str) -> int:
        """计算两个 HH:MM 时间的分钟差"""
        try:
            h1, m1 = map(int, t1.split(":"))
            h2, m2 = map(int, t2.split(":"))
            return (h2 * 60 + m2) - (h1 * 60 + m1)
        except Exception:
            return -999
