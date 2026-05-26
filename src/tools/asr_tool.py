# src/tools/asr_tool.py
import numpy as np
import whisper
from typing import Tuple

class ASRTool:
    """
    Rak Runtime 本地实时语音转写工具
    符合原仓库工具类规范：无状态、纯功能、可独立调用
    """
    def __init__(self, model_name: str = "tiny", language: str = "zh"):
        """
        初始化ASR模型
        :param model_name: Whisper模型大小，可选 tiny/base/small/medium/large
                           Mac Air 推荐用 tiny，延迟<300ms
        :param language: 语言，默认中文
        """
        self.model = whisper.load_model(model_name)
        self.language = language
        self.sample_rate = 16000  # Whisper强制要求的采样率
        self.channels = 1         # 单声道
        
        # 音频缓冲区：保存最近2秒音频，保证转写连续性
        self._buffer = np.array([], dtype=np.float32)
        self._max_buffer_length = int(self.sample_rate * 2.0)

    def add_audio_chunk(self, audio_bytes: bytes) -> None:
        """
        添加一个音频块到缓冲区
        :param audio_bytes: 16kHz 16bit 单声道 PCM 格式的字节流
        """
        # 将16位整数转换为Whisper要求的[-1.0, 1.0]浮点数
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        # 添加到缓冲区
        self._buffer = np.concatenate([self._buffer, audio_array])
        
        # 只保留最近2秒的音频，防止内存溢出
        if len(self._buffer) > self._max_buffer_length:
            self._buffer = self._buffer[-self._max_buffer_length:]

    def transcribe(self) -> Tuple[str, float]:
        """
        转写当前缓冲区的音频
        :return: (转写文本, 置信度0.0-1.0)
        """
        # 音频太短不转写（小于0.1秒）
        if len(self._buffer) < int(self.sample_rate * 0.1):
            return "", 0.0
        
        # 执行转写，固定参数保证结果稳定
        result = self.model.transcribe(
            self._buffer,
            language=self.language,
            verbose=False,
            temperature=0.0,
            condition_on_previous_text=True
        )
        
        # 提取结果
        text = result["text"].strip()
        confidence = result.get("segments", [{}])[0].get("confidence", 0.0)
        
        return text, confidence

    def reset(self) -> None:
        """重置音频缓冲区，用于新的会话"""
        self._buffer = np.array([], dtype=np.float32)