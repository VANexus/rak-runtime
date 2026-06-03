# src/core/audio_pipeline.py
"""
双管线音频处理器 — 核心架构

分流设计：
  - PersonaPlex 管线：超低延迟语音回复（用户立刻听到回应）
  - ASR+LLM 管线：深度思考动作决策（认真规划要执行什么）
  - 提示词反哺：LLM 生成上下文提示给 PersonaPlex，让语音回复更智能

数据流：
  音频输入 → ┌─ PersonaPlex ──→ 语音回复（即时）
              └─ ASR → LLM ──→ 动作列表（规划）+ 提示词反哺给 PersonaPlex
"""
import asyncio
import json
import logging
import os
import threading
import time
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """双管线处理结果"""
    # ASR 结果
    asr_text: str = ""

    # PersonaPlex 语音回复（超快路径）
    voice_response: str = ""       # 语音回复文本
    voice_audio: bytes = b""       # 语音回复音频（如果 PersonaPlex 支持 TTS）

    # LLM 动作决策（主力路径）
    actions: List[Dict] = field(default_factory=list)  # 原子动作列表

    # 元数据
    trace_id: str = ""
    llm_prompt_used: str = ""      # 反哺给 PersonaPlex 的提示词
    latency_personaplex_ms: float = 0
    latency_asr_ms: float = 0
    latency_llm_ms: float = 0


class PersonaPlexStream:
    """
    PersonaPlex WebSocket 流处理器。
    负责超低延迟的语音转写和语音回复。
    """

    def __init__(self, server_url: str = None):
        self.server_url = server_url or os.getenv(
            "PERSONAPLEX_SERVER", "ws://8.129.26.180:8998/ws"
        )
        self.ws = None
        self.connected = False
        self._prompt_context = ""  # LLM 反哺的提示词
        self._transcript_queue = None
        self._voice_queue = None

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
        """断开连接"""
        if self.ws:
            await self.ws.close()
            self.connected = False

    def update_prompt(self, prompt: str):
        """接收 LLM 反哺的提示词"""
        self._prompt_context = prompt
        logger.info(f"PersonaPlex 提示词已更新: {prompt[:50]}...")

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
                # 如果 PersonaPlex 支持提示词，附加上下文
                "context": self._prompt_context,
            }))
        except Exception as e:
            logger.error(f"PersonaPlex 发送失败: {e}")
            self.connected = False

    async def receive(self) -> Optional[Dict]:
        """接收 PersonaPlex 的响应"""
        if not self.connected or not self.ws:
            return None

        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
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

    同时运行两条管线：
    1. PersonaPlex：超低延迟语音转写 → 即时语音回复
    2. ASR+LLM：Whisper 语音识别 → LLM 深度决策 → 原子动作列表

    LLM 生成的上下文提示词会反哺给 PersonaPlex，让语音回复更智能。
    """

    def __init__(self, decision_engine=None, asr_tool=None):
        from src.core.decision_engine import DecisionEngine

        self.decision_engine = decision_engine or DecisionEngine()
        self.asr_tool = asr_tool
        self.personaplex = PersonaPlexStream()

        # 提示词模板
        self._system_context = """你是一个智能助手。用户正在通过语音与你交互。
请根据用户的语音内容，生成简短自然的回复。
同时分析用户是否需要执行物理动作。"""

    async def process_audio(
        self,
        audio_pcm: bytes,
        available_actions: List[str],
        trace_id: str = "",
        device_id: str = "",
    ) -> PipelineResult:
        """
        处理音频输入，双管线并行执行。

        返回：
        - voice_response: PersonaPlex 生成的即时语音回复
        - actions: LLM 规划的原子动作列表
        """
        result = PipelineResult(trace_id=trace_id)

        # 确保 PersonaPlex 已连接
        if not self.personaplex.connected:
            await self.personaplex.connect()

        # ========== 双管线并行执行 ==========

        # 管线 1: PersonaPlex（超快语音回复）
        personaplex_task = asyncio.create_task(
            self._personaplex_pipeline(audio_pcm, result)
        )

        # 管线 2: ASR + LLM（深度动作决策）
        asr_llm_task = asyncio.create_task(
            self._asr_llm_pipeline(audio_pcm, available_actions, result, device_id)
        )

        # 等待两条管线完成
        await asyncio.gather(personaplex_task, asr_llm_task, return_exceptions=True)

        return result

    async def _personaplex_pipeline(self, audio_pcm: bytes, result: PipelineResult):
        """管线 1: PersonaPlex 超低延迟语音转写"""
        t0 = time.time()

        try:
            await self.personaplex.send_audio(audio_pcm)
            response = await self.personaplex.receive()

            if response:
                if response.get("type") == "transcript_final":
                    text = response.get("text", "").strip()
                    result.voice_response = text
                    logger.info(f"[PersonaPlex] 语音回复: {text}")

                elif response.get("type") == "transcript_partial":
                    # 部分结果也可以用于实时显示
                    pass

                # 如果 PersonaPlex 返回音频（TTS）
                if response.get("type") == "audio_output":
                    result.voice_audio = bytes.fromhex(response.get("data", ""))

        except Exception as e:
            logger.error(f"[PersonaPlex] 管线错误: {e}")

        result.latency_personaplex_ms = (time.time() - t0) * 1000

    async def _asr_llm_pipeline(
        self,
        audio_pcm: bytes,
        available_actions: List[str],
        result: PipelineResult,
        device_id: str,
    ):
        """管线 2: ASR + LLM 深度动作决策"""
        t0 = time.time()

        # --- ASR 阶段 ---
        asr_text = await self._run_asr(audio_pcm)
        result.asr_text = asr_text
        result.latency_asr_ms = (time.time() - t0) * 1000

        if not asr_text:
            logger.warning("[ASR+LLM] ASR 转写为空，跳过 LLM")
            return

        logger.info(f"[ASR+LLM] ASR 转写: '{asr_text}'")

        # --- LLM 阶段：动作决策 + 提示词生成 ---
        t1 = time.time()

        llm_result = await self._run_llm_decision(
            asr_text, available_actions, device_id
        )

        result.latency_llm_ms = (time.time() - t1) * 1000

        if llm_result:
            result.actions = llm_result.get("actions", [])
            result.llm_prompt_used = llm_result.get("prompt_for_personaplex", "")

            # 反哺提示词给 PersonaPlex
            if result.llm_prompt_used:
                self.personaplex.update_prompt(result.llm_prompt_used)

            logger.info(
                f"[ASR+LLM] 决策完成: {len(result.actions)} 个动作, "
                f"提示词已反哺"
            )

    async def _run_asr(self, audio_pcm: bytes) -> str:
        """运行 ASR（在线程中执行，避免阻塞事件循环）"""
        if not self.asr_tool:
            # 尝试延迟加载
            try:
                from src.tools import ASRTool
                if ASRTool:
                    self.asr_tool = ASRTool()
                else:
                    return ""
            except Exception:
                return ""

        def _transcribe():
            try:
                # 重置缓冲区，避免旧数据污染
                self.asr_tool.reset()
                self.asr_tool.add_audio_chunk(audio_pcm)
                text, conf = self.asr_tool.transcribe()
                return text
            except Exception as e:
                logger.error(f"[ASR] 转写失败: {e}")
                return ""

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _transcribe)
        return text

    async def _run_llm_decision(
        self,
        text: str,
        available_actions: List[str],
        device_id: str,
    ) -> Optional[Dict]:
        """运行 LLM 决策（在线程中执行）"""
        import anthropic

        client = self.decision_engine._get_llm_client() if hasattr(self.decision_engine, '_get_llm_client') else None
        if not client:
            # 回退到规则引擎
            actions = self.decision_engine._rule_decompose(text, available_actions)
            return {"actions": actions, "prompt_for_personaplex": ""}

        model = os.getenv("ANTHROPIC_MODEL", "mimo-v2.5-pro")

        actions_desc = "\n".join(f"- {a}" for a in available_actions)

        system_prompt = f"""你是一个智能机器人控制系统的核心决策引擎。

## 双重职责
1. **动作决策**：分析用户语音指令，分解为可执行的原子动作
2. **回复生成**：为 PersonaPlex（语音合成系统）生成简短自然的回复提示词

## 可用原子动作
{actions_desc}

## 输出格式
返回 JSON：
{{
  "actions": [
    {{"action": "动作名", "params_json": "{{}}", "priority": 0, "reason": "原因"}}
  ],
  "voice_reply": "对用户说的话（简短自然，15字以内）",
  "prompt_for_personaplex": "给PersonaPlex的上下文提示（让后续语音回复更智能）"
}}

## 规则
- 动作必须在可用列表中
- voice_reply 要自然、简洁、友好
- 如果用户只是聊天不需要动作，actions 为空
- priority: 0=实时(Q0), 1=交互(Q1), 2=管理(Q2)"""

        def _llm_call():
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=512,
                    system=system_prompt,
                    messages=[{"role": "user", "content": f"用户说: {text}\n设备: {device_id}"}],
                    timeout=15.0,
                )

                raw = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        raw = block.text.strip()
                        break

                if not raw:
                    return None

                # 提取 JSON
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]

                parsed = json.loads(raw)

                # 验证动作
                valid_actions = []
                for a in parsed.get("actions", []):
                    if a.get("action") in available_actions:
                        valid_actions.append({
                            "action": a["action"],
                            "params_json": a.get("params_json", "{}"),
                            "priority": a.get("priority", 2),
                        })

                return {
                    "actions": valid_actions,
                    "voice_reply": parsed.get("voice_reply", ""),
                    "prompt_for_personaplex": parsed.get("prompt_for_personaplex", ""),
                }

            except Exception as e:
                logger.error(f"[LLM] 决策失败: {e}")
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _llm_call)


def process_audio_sync(
    audio_pcm: bytes,
    available_actions: List[str],
    trace_id: str = "",
    device_id: str = "",
) -> PipelineResult:
    """
    同步接口：供 gRPC 服务端调用。
    内部创建事件循环运行异步双管线。
    """
    processor = DualPipelineProcessor()

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            processor.process_audio(audio_pcm, available_actions, trace_id, device_id)
        )
        return result
    finally:
        loop.close()
