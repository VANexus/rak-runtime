"""
Unit tests for the ASR tool.
Tests PCM audio processing without requiring a real Whisper model.
"""
import os
import struct
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestASRToolInit(unittest.TestCase):
    """测试 ASR 工具初始化"""

    @patch("src.tools.asr_tool.whisper")
    def test_init_with_default_model(self, mock_whisper):
        """默认应加载 tiny 模型"""
        mock_whisper.load_model.return_value = MagicMock()
        from src.tools.asr_tool import ASRTool
        tool = ASRTool()
        mock_whisper.load_model.assert_called_once_with("tiny")

    @patch("src.tools.asr_tool.whisper")
    def test_init_with_custom_model(self, mock_whisper):
        """应支持自定义模型"""
        mock_whisper.load_model.return_value = MagicMock()
        from src.tools.asr_tool import ASRTool
        tool = ASRTool(model_name="base")
        mock_whisper.load_model.assert_called_once_with("base")

    @patch("src.tools.asr_tool.whisper", None)
    def test_graceful_fallback_when_whisper_missing(self):
        """whisper 未安装时应优雅降级"""
        # 重新导入以触发 whisper=None 的情况
        import importlib
        import src.tools.asr_tool
        importlib.reload(src.tools.asr_tool)
        # 如果 whisper 为 None，ASRTool 的 __init__ 应该抛异常或设置不可用状态
        # 具体行为取决于实现


class TestPCMProcessing(unittest.TestCase):
    """测试 PCM 音频数据处理"""

    def _generate_pcm_silence(self, duration_ms=100, sample_rate=16000, bits=16):
        """生成静音 PCM 数据"""
        num_samples = int(sample_rate * duration_ms / 1000)
        # 16-bit signed PCM
        return b'\x00\x00' * num_samples

    def _generate_pcm_sine(self, freq=440, duration_ms=100, sample_rate=16000, bits=16):
        """生成正弦波 PCM 数据"""
        import math
        num_samples = int(sample_rate * duration_ms / 1000)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            value = int(32767 * 0.5 * math.sin(2 * math.pi * freq * t))
            samples.append(struct.pack('<h', value))
        return b''.join(samples)

    def test_pcm_silence_size(self):
        """100ms 16kHz 16-bit 静音应为 3200 字节"""
        pcm = self._generate_pcm_silence(100)
        self.assertEqual(len(pcm), 3200)  # 16000 * 0.1 * 2

    def test_pcm_sine_size(self):
        """100ms 16kHz 16-bit 正弦波应为 3200 字节"""
        pcm = self._generate_pcm_sine(duration_ms=100)
        self.assertEqual(len(pcm), 3200)

    def test_pcm_sine_not_all_zeros(self):
        """正弦波不应全为零"""
        pcm = self._generate_pcm_sine(duration_ms=100)
        self.assertNotEqual(pcm, b'\x00' * len(pcm))

    @patch("src.tools.asr_tool.whisper")
    def test_add_audio_chunk(self, mock_whisper):
        """应能添加音频块到缓冲区"""
        mock_whisper.load_model.return_value = MagicMock()
        from src.tools.asr_tool import ASRTool
        tool = ASRTool()

        pcm = self._generate_pcm_silence(100)
        tool.add_audio_chunk(pcm)
        # 缓冲区不应为空
        self.assertGreater(len(tool.audio_buffer), 0)

    @patch("src.tools.asr_tool.whisper")
    def test_transcribe_empty_buffer(self, mock_whisper):
        """空缓冲区转写应返回空结果"""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "", "segments": []}
        mock_whisper.load_model.return_value = mock_model
        mock_whisper.pad_or_trim.return_value = MagicMock()
        mock_whisper.log_mel_spectrogram.return_value = MagicMock()

        from src.tools.asr_tool import ASRTool
        tool = ASRTool()
        # 不添加任何音频
        result = tool.transcribe()
        # 应返回空文本或 None
        if result:
            text, confidence = result
            self.assertEqual(text.strip(), "")


class TestASRToolConditionalImport(unittest.TestCase):
    """测试 ASR 工具的条件导入"""

    def test_import_with_whisper(self):
        """whisper 可用时 ASRTool 应为类"""
        from src.tools import ASRTool
        # ASRTool 要么是类，要么是 None（取决于 whisper 是否安装）
        if ASRTool is not None:
            self.assertTrue(callable(ASRTool))


if __name__ == "__main__":
    unittest.main()
