"""
出站通道 — 大脑主动表达的出口。

InnerLoop 的主动说话（speak）与 ProactiveEngine 的告警（alert）
通过 MQTT 发布到硬件层，让大脑从"被动响应"变成"主动表达"。

开关：RAK_OUTBOUND=1 才真正发布，否则只记日志（安全默认）。
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("rak.outbound")


class Outbound:
    """出站通道：说话、告警、动作派发"""

    def __init__(self, publisher=None, enabled: Optional[bool] = None):
        self._publisher = publisher
        self._enabled = (
            os.getenv("RAK_OUTBOUND", "0") == "1" if enabled is None else enabled
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def speak(self, text: str, device_id: str = "default"):
        """主动说话（InnerLoop 调用）"""
        if not self._enabled:
            logger.info("[Outbound] 出站禁用，主动表达: %s", text[:60])
            return
        if self._publisher:
            self._publisher.publish_state(device_id, {"speech": text})
        else:
            logger.info("[Outbound] 主动表达: %s", text[:60])

    def alert(self, alert, device_id: str = "default"):
        """主动告警（ProactiveEngine 调用）"""
        if not self._enabled:
            logger.info("[Outbound] 出站禁用，告警[%s]: %s",
                        getattr(alert, "level", "?"),
                        getattr(alert, "message", "")[:60])
            return
        if self._publisher:
            self._publisher.publish_state(device_id, {
                "alert_level": getattr(alert, "level", "info"),
                "title": getattr(alert, "title", ""),
                "message": getattr(alert, "message", ""),
            })
        else:
            logger.info("[Outbound] 告警[%s]: %s",
                        getattr(alert, "level", "?"),
                        getattr(alert, "message", "")[:60])

    def publish_action(self, device_id: str, action: str, params_json: str = "") -> bool:
        """动作派发到硬件层"""
        if self._publisher:
            return self._publisher.publish_action(device_id, action, params_json)
        logger.info("[Outbound] 动作(未发布): %s -> %s", device_id, action)
        return False


_outbound = None


def get_outbound() -> Outbound:
    """懒加载单例"""
    global _outbound
    if _outbound is None:
        from src.tools.mqtt_publisher import get_mqtt_publisher
        _outbound = Outbound(publisher=get_mqtt_publisher())
    return _outbound
