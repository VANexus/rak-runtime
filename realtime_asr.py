import numpy as np
import whisper
import soundcard as sc
import threading
import queue
import time
import paho.mqtt.client as mqtt

# -------------------------- 配置区 --------------------------
SAMPLE_RATE = 16000
BLOCK_SIZE = 1024
MODEL_NAME = "tiny"
LANGUAGE = "zh"

# MQTT 服务器地址
MQTT_BROKER = "8.129.26.180"
MQTT_PORT = 1883
MQTT_TOPIC = "rak/command/text"  # 给ESP32订阅的主题
MQTT_CLIENT_ID = "rak-asr-mac-client"
# -----------------------------------------------------------

# 初始化Whisper模型
print("正在加载Whisper模型...")
model = whisper.load_model(MODEL_NAME)
print("模型加载完成！")

# 初始化MQTT客户端
mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()
print(f"已连接到MQTT服务器 {MQTT_BROKER}:{MQTT_PORT}")

# 音频队列
audio_queue = queue.Queue()
running = True

def audio_capture():
    """用soundcard库捕获麦克风音频"""
    mic = sc.default_microphone()
    print(f"正在使用麦克风: {mic.name}")
    
    with mic.recorder(samplerate=SAMPLE_RATE, channels=1) as recorder:
        while running:
            data = recorder.record(numframes=BLOCK_SIZE)
            data = data.flatten()
            audio_queue.put(data)

def transcribe_loop():
    """实时转写并发布到MQTT"""
    audio_buffer = np.array([], dtype=np.float32)
    last_text = ""
    
    while running:
        # 累积音频数据
        while not audio_queue.empty():
            chunk = audio_queue.get()
            audio_buffer = np.concatenate([audio_buffer, chunk])
        
        # 每0.5秒转写一次
        if len(audio_buffer) >= SAMPLE_RATE * 0.5:
            result = model.transcribe(
                audio_buffer,
                language=LANGUAGE,
                verbose=False,
                temperature=0.0
            )
            text = result["text"].strip()
            
            if text and text != last_text:
                print(f"你说: {text}")
                # 把转写结果发布到MQTT主题
                mqtt_client.publish(MQTT_TOPIC, text)
                print(f"已发送到MQTT主题 {MQTT_TOPIC}: {text}")
                last_text = text
            
            # 保留最后0.2秒音频，避免断句
            audio_buffer = audio_buffer[-int(SAMPLE_RATE * 0.2):]

if __name__ == "__main__":
    try:
        capture_thread = threading.Thread(target=audio_capture)
        capture_thread.start()
        
        transcribe_loop()
    except KeyboardInterrupt:
        running = False
        capture_thread.join()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("\n停止转写，断开MQTT连接")