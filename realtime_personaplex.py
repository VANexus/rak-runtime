import asyncio
import paho.mqtt.client as mqtt
from src.tools.personaplex_client import PersonaPlexASRClient

"""
PersonaPlex 端到端实时语音转写客户端
基于NVIDIA PersonaPlex的WebSocket接口，实现低延迟的语音转写
转写结果自动发布到MQTT主题 `rak/command/text`，供ESP32设备接收
"""

# -------------------------- config --------------------------
# MQTT服务器地址
MQTT_BROKER = "8.129.26.180"
MQTT_PORT = 1883
MQTT_TOPIC = "rak/command/text"
MQTT_CLIENT_ID = "rak-asr-personaplex-client"

# PersonaPlex服务器地址
PERSONAPLEX_SERVER = "ws://8.129.26.180:8998/ws"
# ---------------------------------------------------------

# MQTT客户端初始化
mqtt_client = mqtt.Client(MQTT_CLIENT_ID)
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

async def mqtt_publish_task(text_queue):
    """把转写结果发布到MQTT"""
    while True:
        text = await text_queue.get()
        mqtt_client.publish(MQTT_TOPIC, text)
        print(f"已发送到MQTT主题 {MQTT_TOPIC}: {text}")

async def main():
    print("PersonaPlex 实时语音转写客户端已启动")
    print("按 Ctrl+C 停止")
    
    client = PersonaPlexASRClient(PERSONAPLEX_SERVER)
    
    # 启动MQTT发布任务
    publish_task = asyncio.create_task(mqtt_publish_task(client.text_queue))
    
    try:
        await client.run()
    except KeyboardInterrupt:
        print("\n停止转写，断开MQTT连接")
        client.stop()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())