"""MQTT 发布器测试"""

import json

from src.tools.mqtt_publisher import MQTTPublisher, get_mqtt_publisher


class TestMQTTPublisher:
    def test_lazy_singleton_does_not_connect(self):
        """懒加载单例获取时不应建立连接"""
        pub = get_mqtt_publisher()
        assert pub is not None
        assert pub._client is None  # 未发布前不连接

    def test_action_topic_rakmessage(self):
        """动作发布 topic 应为 rak/{device}/cmd"""
        pub = MQTTPublisher(broker_host="localhost", broker_port=1883)
        assert pub._topic_for("cmd", "esp32-001") == "rak/esp32-001/cmd"

    def test_state_topic(self):
        """状态发布 topic 应为 rak/{device}/state"""
        pub = MQTTPublisher()
        assert pub._topic_for("state", "esp32-001") == "rak/esp32-001/state"

    def test_envelope_v0_fields(self):
        """RakMessage v0 信封应包含必要字段"""
        pub = MQTTPublisher()
        env = pub._build_envelope("lock_open", '{"speed":1}', "esp32-001")
        assert env["version"] == "v0"
        assert env["type"] == "action"
        assert env["action"] == "lock_open"
        assert env["target"] == "device:esp32-001"
        assert env["params"] == {"speed": 1}
        assert env["timestamp"] > 0

    def test_publish_disabled_returns_false(self):
        """出站禁用时发布应返回 False 且不连接"""
        pub = MQTTPublisher(enabled=False)
        ok = pub.publish_action("esp32-001", "lock_open", "{}")
        assert ok is False
        assert pub._client is None
