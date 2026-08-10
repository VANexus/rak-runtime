"""
设备驱动 Agent 适配器 — 大脑把动作派发到硬件层。

派发优先级：
1. 命中 RAK_DEVICE_AGENTS 中同名/同 device_id 的 A2A agent → A2A tasks/send
2. 否则 MQTT 发布（rak/{device_id}/cmd，RakMessage v0）
3. 都不可用 → 记日志

配置（env）：
    RAK_DEVICE_AGENTS = '[{"name":"esp32-001","a2a_url":"http://host:8000","device_id":"esp32-001"}]'
"""

import json
import logging
import os

logger = logging.getLogger("rak.a2a.device")


def load_device_agents() -> list:
    """从 RAK_DEVICE_AGENTS env 读取设备 agent 列表"""
    raw = os.getenv("RAK_DEVICE_AGENTS", "")
    if not raw:
        return []
    try:
        agents = json.loads(raw)
        return agents if isinstance(agents, list) else []
    except json.JSONDecodeError as e:
        logger.warning("[DeviceAgent] RAK_DEVICE_AGENTS 解析失败: %s", e)
        return []


def dispatch_action(action: str, params_json: str = "{}",
                    device_id: str = "", trace_id: str = "") -> tuple:
    """
    向设备派发动作。

    Returns:
        (channel, result)：channel ∈ {a2a, mqtt, none}
    """
    agents = load_device_agents()
    for ag in agents:
        if ag.get("device_id") == device_id or ag.get("name") == device_id:
            url = ag.get("a2a_url")
            if url:
                try:
                    from src.a2a.client import dispatch_task
                    reply = dispatch_task(
                        url,
                        f"执行动作 {action}，参数 {params_json}",
                        timeout=20,
                    )
                    logger.info("[DeviceAgent] A2A 派发 %s → %s: %s",
                                device_id, action, reply[:60])
                    return "a2a", reply
                except Exception as e:
                    logger.warning("[DeviceAgent] A2A 派发失败 %s: %s，MQTT 兜底", url, e)
            break

    # MQTT 兜底
    try:
        from src.tools.mqtt_publisher import get_mqtt_publisher
        pub = get_mqtt_publisher()
        if pub is not None:
            ok = pub.publish_action(device_id, action, params_json, trace_id)
            return "mqtt", ok
    except Exception as e:
        logger.warning("[DeviceAgent] MQTT 兜底失败: %s", e)

    logger.info("[DeviceAgent] 无可用通道，动作 %s -> %s", device_id, action)
    return "none", False
