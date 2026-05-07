# src/tools/mqtt_publisher.py
import os
import json
import paho.mqtt.client as mqtt
import logging

logger = logging.getLogger(__name__)

class MQTTPublisher:
    def __init__(self, broker_host=None, broker_port=None, topic_prefix="robot"):
        # 从环境变量读取配置，方便容器化部署
        self.broker_host = broker_host or os.getenv("MQTT_BROKER_HOST", "localhost")
        self.broker_port = broker_port or int(os.getenv("MQTT_BROKER_PORT", 1883))
        self.topic_prefix = topic_prefix
        self.client = mqtt.Client()
        
        # 设置连接回调
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info(f"MQTT 连接成功: {self.broker_host}:{self.broker_port}")
            else:
                logger.error(f"MQTT 连接失败，错误码: {rc}")

        self.client.on_connect = on_connect
        self.client.connect_async(self.broker_host, self.broker_port)
        self.client.loop_start()  # 启动后台线程

    def publish_action(self, target: str, action: str, params_json: str):
        """发布动作到指定设备"""
        topic = f"{self.topic_prefix}/{target}/control"
        try:
            payload = {
                "action": action,
                "params": json.loads(params_json)  # 将 JSON 字符串转为字典
            }
            result = self.client.publish(topic, json.dumps(payload), qos=1)
            
            # 等待消息发送结果
            result.wait_for_publish()
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"MQTT 下发成功: Topic='{topic}', Payload={payload}")
                return True
            else:
                logger.error(f"MQTT 发布失败，错误码: {result.rc}")
                return False
        except Exception as e:
            logger.error(f"MQTT 发布异常: {e}")
            return False

# 全局单例
mqtt_publisher = MQTTPublisher()