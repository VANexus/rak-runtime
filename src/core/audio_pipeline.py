"""
音频管线 — 纯远程 ASR + LLM 决策

设计：
  - PersonaPlex 管线：远程 ASR 转写（WebSocket API）
  - LLM 管线：深度动作决策（外部 LLM API）
  - 提示词反哺：LLM 生成上下文提示给 PersonaPlex

数据流：
  音频输入 → PersonaPlex(远程ASR) → 文本 → LLM(外部API) → 原子动作列表
                                   ↘ 即时语音回复

零本地推理：不依赖 torch/whisper/sounddevice。
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional, List, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """管线处理结果"""
    asr_text: str = ""
    voice_response: str = ""
    voice_audio: bytes = b""
    actions: List[Dict] = field(default_factory=list)
    trace_id: str = ""
    llm_prompt_used: str = ""
    latency_asr_ms: float = 0
    latency_llm_ms: float = 0


class PersonaPlexStream:
    """
    PersonaPlex WebSocket 流处理器。
    调用远程 PersonaPlex 服务进行 ASR 转写和语音回复。
    """

    def __init__(self, server_url: str = None):
        self.server_url = server_url or os.getenv(
            "PERSONAPLEX_SERVER", "ws://8.129.26.180:8998/ws"
        )
        self.ws = None
        self.connected = False
        self._prompt_context = ""

    async def connect(self):
        """连接 PersonaPlex 服务器"""
        try:
            import websockets
            self.ws = await websockets.connect(self.server_url)
            self.connected = True
            logger.info(f"PersonaPlex 已连接: {self.server_url}")
        except Exception as e:
            logger.warning(f"PersonaPlex 连接失败: {e}")
            self.connected = False

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.connected = False

    def update_prompt(self, prompt: str):
        self._prompt_context = prompt

    async def send_audio(self, audio_pcm: bytes):
        """发送音频到 PersonaPlex（PCM 16kHz 16bit mono）"""
        if not self.connected or not self.ws:
            return

        try:
            await self.ws.send(json.dumps({
                "type": "audio_input",
                "data": audio_pcm.hex(),
                "format": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1,
                "context": self._prompt_context,
            }))
        except Exception as e:
            logger.error(f"PersonaPlex 发送失败: {e}")
            self.connected = False

    async def receive(self) -> Optional[Dict]:
        if not self.connected or not self.ws:
            return None
        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            return json.loads(msg)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"PersonaPlex 接收失败: {e}")
            self.connected = False
            return None


class DualPipelineProcessor:
    """
    双管线音频处理器。

    管线 1: PersonaPlex → 即时语音回复（超快路径）
    管线 2: PersonaPlex ASR → LLM 深度决策 → 原子动作列表

    两条管线共享 PersonaPlex 连接，但职责不同：
    - 管线 1 关注语音回复速度
    - 管线 2 关注动作规划准确性
    """

    def __init__(self, decision_engine=None, **_kwargs):
        from src.core.decision_engine import DecisionEngine
        self.decision_engine = decision_engine or DecisionEngine()
        self.personaplex = PersonaPlexStream()

    async def process_audio(
        self,
        audio_pcm: bytes,
        available_actions: List[str],
        trace_id: str = "",
        device_id: str = "",
    ) -> PipelineResult:
        """处理音频输入，双管线并行执行。"""
        result = PipelineResult(trace_id=trace_id)

        if not self.personaplex.connected:
            await self.personaplex.connect()

        if not self.personaplex.connected:
            # PersonaPlex 不可用，返回空结果
            logger.warning(f"[TraceID: {trace_id}] PersonaPlex 不可用")
            return result

        # 管线 1: PersonaPlex 语音回复
        pp_task = asyncio.create_task(
            self._personaplex_pipeline(audio_pcm, result)
        )

        # 管线 2: ASR + LLM 动作决策
        llm_task = asyncio.create_task(
            self._asr_llm_pipeline(audio_pcm, available_actions, result, device_id)
        )

        await asyncio.gather(pp_task, llm_task, return_exceptions=True)
        return result

    async def _personaplex_pipeline(self, audio_pcm: bytes, result: PipelineResult):
        """管线 1: PersonaPlex 即时语音回复"""
        try:
            await self.personaplex.send_audio(audio_pcm)
            response = await self.personaplex.receive()

            if response:
                if response.get("type") == "transcript_final":
                    result.voice_response = response.get("text", "").strip()
                if response.get("type") == "audio_output":
                    result.voice_audio = bytes.fromhex(response.get("data", ""))
        except Exception as e:
            logger.error(f"[PersonaPlex] 管线错误: {e}")

    async def _asr_llm_pipeline(
        self,
        audio_pcm: bytes,
        available_actions: List[str],
        result: PipelineResult,
        device_id: str,
    ):
        """管线 2: ASR 转写 + LLM 深度决策"""
        t0 = time.time()

        # ASR 阶段：通过 PersonaPlex 获取转写文本
        asr_text = await self._remote_asr(audio_pcm)
        result.asr_text = asr_text
        result.latency_asr_ms = (time.time() - t0) * 1000

        if not asr_text:
            logger.warning("[ASR+LLM] ASR 转写为空")
            return

        logger.info(f"[ASR+LLM] ASR 转写: '{asr_text}'")

        # LLM 阶段：深度动作决策
        t1 = time.time()

        llm_result = await self._run_llm_decision(
            asr_text, available_actions, device_id
        )

        result.latency_llm_ms = (time.time() - t1) * 1000

        if llm_result:
            result.actions = llm_result.get("actions", [])
            result.llm_prompt_used = llm_result.get("prompt_for_personaplex", "")
            if result.llm_prompt_used:
                self.personaplex.update_prompt(result.llm_prompt_used)

    async def _remote_asr(self, audio_pcm: bytes) -> str:
        """
        通过 PersonaPlex 远程 ASR 获取转写文本。
        发送音频，等待 transcript_final 响应。
        """
        try:
            await self.personaplex.send_audio(audio_pcm)

            # 等待最终转写结果（最多 5 秒）
            deadline = time.time() + 5.0
            while time.time() < deadline:
                response = await self.personaplex.receive()
                if response is None:
                    continue
                if response.get("type") == "transcript_final":
                    return response.get("text", "").strip()
                # 部分结果继续等
        except Exception as e:
            logger.error(f"[RemoteASR] 转写失败: {e}")

        return ""

    async def _run_llm_decision(
        self,
        text: str,
        available_actions: List[str],
        device_id: str,
    ) -> Optional[Dict]:
        """运行 LLM 决策"""
        # 使用 DecisionEngine 的文本决策方法
        loop = asyncio.get_event_loop()

        def _decide():
            return self.decision_engine.decide_from_text(
                text=text,
                available_actions=available_actions,
                trace_id="",
                device_state=device_id,
            )

        result = await loop.run_in_executor(None, _decide)

        if result and result.get("status") == "ok":
            return {
                "actions": result.get("actions", []),
                "voice_reply": "",
                "prompt_for_personaplex": "",
            }
        return None
