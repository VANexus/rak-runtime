import asyncio
import json
import websockets
import numpy as np
import soundcard as sc

"""
PersonaPlex ASR客户端类
通过WebSocket连接服务器端的PersonaPlex服务，实现实时音频流传输入和转写结果输出
支持16kHz采样率、16位整数、单声道的PCM音频格式
"""


class PersonaPlexASRClient:
    def __init__(self, server_url="ws://8.129.26.180:8998/ws"):
        self.server_url = server_url
        self.audio_queue = asyncio.Queue()
        self.text_queue = asyncio.Queue()
        self.running = False

    async def audio_capture_task(self):
        """此处复用原有的麦克风采集代码"""
        mic = sc.default_microphone()
        # PersonaPlex要求16kHz采样率，16位整数，单声道
        with mic.recorder(samplerate=16000, channels=1, blocksize=512) as recorder:
            while self.running:
                audio_chunk = recorder.record(numframes=512)
                # 转换为16位整数格式
                audio_chunk = (audio_chunk * 32767).astype(np.int16).tobytes()
                await self.audio_queue.put(audio_chunk)

    async def send_audio_task(self, websocket):
        """把音频流发送给服务器上的PersonaPlex服务"""
        while self.running:
            audio_chunk = await self.audio_queue.get()
            await websocket.send(json.dumps({
                "type": "audio_input",
                "data": audio_chunk.hex(),
                "format": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1
            }))

    async def receive_transcript_task(self, websocket):
        """接收PersonaPlex的转写结果"""
        while self.running:
            message = await websocket.recv()
            data = json.loads(message)
            
            # 处理最终转写结果（和Whisper的输出格式一致）
            if data.get("type") == "transcript_final":
                text = data.get("text", "").strip()
                if text:
                    print(f"你说：{text}")
                    await self.text_queue.put(text)
            
            # 处理部分转写结果（可选，用于实时显示）
            elif data.get("type") == "transcript_partial":
                partial_text = data.get("text", "").strip()
                if partial_text:
                    print(f"\r正在识别：{partial_text}", end="", flush=True)

    async def run(self):
        """启动客户端"""
        self.running = True
        print(f"正在连接PersonaPlex服务器：{self.server_url}")
        
        try:
            async with websockets.connect(self.server_url) as websocket:
                print("连接成功！开始实时语音转写")
                
                # 启动三个异步任务
                capture_task = asyncio.create_task(self.audio_capture_task())
                send_task = asyncio.create_task(self.send_audio_task(websocket))
                receive_task = asyncio.create_task(self.receive_transcript_task(websocket))
                
                # 等待任务完成
                await asyncio.gather(capture_task, send_task, receive_task)
                
        except Exception as e:
            print(f"连接失败：{e}")
            print("请确保服务器上的PersonaPlex服务已经启动")
            self.running = False

    def stop(self):
        """停止客户端"""
        self.running = False
        print("\n停止转写")