# src/tools/__init__.py
"""
工具模块 — 纯远程依赖，零本地推理。

所有外部服务调用（MQTT、PersonaPlex 等）通过此模块暴露。
ASR 已移除本地 Whisper，改由外部 PersonaPlex API 处理。
"""
from src.tools.mqtt_publisher import MQTTPublisher, mqtt_publisher
