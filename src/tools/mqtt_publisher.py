# src/tools/mqtt_publisher.py
"""MQTT 发布器 — 大脑的出站通道。

- topic 对齐 go-kernel 契约：rak/{device_id}/{cmd,state,audio}
- payload 使用 RakMessage v0 信封
- 懒连接：构造/获取单例不碰 broker，首次发布才 connect_async
- 出站开关：RAK_OUTBOUND=1 才真正发布（默认只记日志）
"""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)


class MQTTPublisher:
    def __init__(self, broker_host=None, broker_port=None,
                 topic_prefix="rak", enabled=False):
        self.broker_host = broker_host or os.getenv("MQTT_BROKER_HOST", "localhost")
        self.broker_port = broker_port or int(os.getenv("MQTT_BROKER_PORT", 1883))
        self.topic_prefix = topic_prefix
        self.enabled = enabled
        self._client = None

    def _ensure_connected(self):
        """首次发布时懒建立连接"""
        if self._client is not None:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.warning("[MQTT] paho-mqtt 未安装，出站通道不可用")
            return

        self._client = mqtt.Client()

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info("[MQTT] 连接成功: %s:%s", self.broker_host, self.broker_port)
            else:
                logger.error("[MQTT] 连接失败，错误码: %d", rc)

        self._client.on_connect = on_connect
        self._client.connect_async(self.broker_host, self.broker_port)
        self._client.loop_start()

    def _topic_for(self, kind: str, device_id: str) -> str:
        return f"{self.topic_prefix}/{device_id}/{kind}"

    def _build_envelope(self, action: str, params_json: str, device_id: str,
                        trace_id: str = "") -> dict:
        """RakMessage v0 动作信封"""
        try:
            params = json.loads(params_json) if params_json else {}
        except json.JSONDecodeError:
            params = {}
        return {
            "version": "v0",
            "type": "action",
            "trace_id": trace_id,
            "source": "runtime:default",
            "target": f"device:{device_id}",
            "action": action,
            "params": params,
            "data": {},
            "timestamp": int(time.time()),
        }

    def publish_action(self, device_id: str, action: str, params_json: str = "{}",
                       trace_id: str = "", qos: int = 1) -> bool:
        """发布动作命令到 rak/{device_id}/cmd"""
        if not self.enabled:
            logger.info("[MQTT] 出站禁用（RAK_OUTBOUND=1 启用），跳过 %s -> %s",
                        device_id, action)
            return False
        self._ensure_connected()
        if self._client is None:
            return False
        try:
            payload = json.dumps(
                self._build_envelope(action, params_json, device_id, trace_id),
                ensure_ascii=False,
            )
            info = self._client.publish(
                self._topic_for("cmd", device_id), payload, qos=qos
            )
            logger.info("[MQTT] 下发 %s: %s", self._topic_for("cmd", device_id), action)
            return True
        except Exception as e:
            logger.error("[MQTT] 发布异常: %s", e)
            return False

    def publish_state(self, device_id: str, state: dict, trace_id: str = "") -> bool:
        """发布设备状态到 rak/{device_id}/state"""
        if not self.enabled:
            return False
        self._ensure_connected()
        if self._client is None:
            return False
        try:
            payload = json.dumps({
                "version": "v0",
                "type": "state",
                "trace_id": trace_id,
                "source": "runtime:default",
                "target": f"device:{device_id}",
                "data": state,
                "timestamp": int(time.time()),
            }, ensure_ascii=False)
            self._client.publish(self._topic_for("state", device_id), payload, qos=0)
            return True
        except Exception as e:
            logger.error("[MQTT] 状态发布异常: %s", e)
            return False


_publisher = None


def get_mqtt_publisher() -> MQTTPublisher:
    """懒加载单例（出站开关由 RAK_OUTBOUND 决定）"""
    global _publisher
    if _publisher is None:
        enabled = os.getenv("RAK_OUTBOUND", "0") == "1"
        _publisher = MQTTPublisher(enabled=enabled)
    return _publisher
