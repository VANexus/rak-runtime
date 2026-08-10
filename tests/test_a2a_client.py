"""A2A 客户端 + 设备驱动适配器 + 出站通道测试"""

import json
from unittest.mock import patch

from src.a2a import device_agent
from src.a2a.client import dispatch_task
from src.core.outbound import Outbound


class TestDeviceAgent:
    def test_load_device_agents_empty(self, monkeypatch):
        monkeypatch.delenv("RAK_DEVICE_AGENTS", raising=False)
        assert device_agent.load_device_agents() == []

    def test_load_device_agents_parse(self, monkeypatch):
        monkeypatch.setenv("RAK_DEVICE_AGENTS", json.dumps([
            {"name": "esp32-001", "a2a_url": "http://h:8000", "device_id": "esp32-001"}
        ]))
        agents = device_agent.load_device_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "esp32-001"

    def test_dispatch_no_agent(self, monkeypatch):
        """无 A2A agent 时应走 MQTT 兜底（无 publisher 则 none）"""
        monkeypatch.delenv("RAK_DEVICE_AGENTS", raising=False)
        with patch("src.tools.mqtt_publisher.get_mqtt_publisher", return_value=None):
            channel, _ = device_agent.dispatch_action("light_on", "{}", "esp32-001")
        assert channel in ("none", "mqtt")

    def test_dispatch_a2a_success(self, monkeypatch):
        """命中 A2A agent 且派发成功 → channel=a2a"""
        monkeypatch.setenv("RAK_DEVICE_AGENTS", json.dumps([
            {"name": "esp32-001", "a2a_url": "http://h:8000", "device_id": "esp32-001"}
        ]))
        with patch("src.a2a.client.dispatch_task", return_value="好的，开灯"):
            channel, reply = device_agent.dispatch_action("light_on", "{}", "esp32-001")
        assert channel == "a2a"
        assert "好的" in reply

    def test_dispatch_a2a_failure_falls_back(self, monkeypatch):
        """A2A 派发失败 → 兜底（不崩）"""
        monkeypatch.setenv("RAK_DEVICE_AGENTS", json.dumps([
            {"name": "esp32-001", "a2a_url": "http://h:8000", "device_id": "esp32-001"}
        ]))
        with patch("src.a2a.client.dispatch_task", side_effect=RuntimeError("down")):
            with patch("src.tools.mqtt_publisher.get_mqtt_publisher", return_value=None):
                channel, _ = device_agent.dispatch_action("light_on", "{}", "esp32-001")
        assert channel in ("mqtt", "none")


class TestDispatchTask:
    def test_dispatch_task_collects_reply(self):
        """dispatch_task 应收集状态消息中的回复文本"""
        from a2a.types.a2a_pb2 import (
            Message, Part, Role, StreamResponse,
            TaskState, TaskStatus, TaskStatusUpdateEvent,
        )

        class FakeClient:
            async def send_message(self, req):
                su = TaskStatusUpdateEvent(
                    task_id="t1",
                    status=TaskStatus(
                        state=TaskState.Value("TASK_STATE_COMPLETED"),
                        message=Message(
                            role=Role.ROLE_AGENT, parts=[Part(text="好的，开灯")]
                        ),
                    ),
                )
                yield StreamResponse(status_update=su)

        async def fake_create_client(url):
            return FakeClient()

        with patch("src.a2a.client.create_client", side_effect=fake_create_client):
            reply = dispatch_task("http://x", "帮我开灯")
        assert "好的" in reply


class TestOutboundIntegration:
    def test_outbound_disabled(self):
        """出站禁用时 publish_action 返回 False"""
        ob = Outbound(enabled=False)
        assert ob.publish_action("esp32-001", "light_on") is False

    def test_outbound_enabled_dispatches(self):
        """出站启用时经设备 agent 派发"""
        ob = Outbound(enabled=True)
        with patch("src.a2a.device_agent.dispatch_action",
                   return_value=("a2a", "好的")):
            assert ob.publish_action("esp32-001", "light_on") is True

    def test_outbound_speak_disabled_logs(self):
        """speak 在出站禁用时只记日志"""
        ob = Outbound(enabled=False)
        ob.speak("我想说句话")
