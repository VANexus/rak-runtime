"""A2A 服务器测试 — 官方 SDK 客户端 → 大脑往返"""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn

from src.a2a.server import create_app, create_agent_card, run_brain_decision
from a2a.client import create_client
from a2a.types.a2a_pb2 import Message, Part, Role, SendMessageRequest

PORT = 18002


@pytest.fixture(scope="module")
def server():
    card = create_agent_card()
    card.supported_interfaces[0].url = f"http://127.0.0.1:{PORT}"
    app = create_app(card)
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    yield srv
    srv.should_exit = True
    thread.join(timeout=5)


class TestAgentCard:
    def test_agent_card_fields(self):
        """Agent Card 应包含大脑的身份、能力与技能"""
        card = create_agent_card()
        assert card.name == "Rak"
        assert len(card.skills) >= 3
        assert card.capabilities.streaming is True


class TestA2ARoundTrip:
    def test_send_message_completes(self, server):
        """A2A 客户端发送任务 → 大脑决策 → COMPLETED"""
        async def _run():
            client = await create_client(f"http://127.0.0.1:{PORT}")
            req = SendMessageRequest(message=Message(
                message_id="test-msg-1",
                role=Role.ROLE_USER, parts=[Part(text="帮我开灯")]
            ))
            replies = []
            states = []
            async for resp in client.send_message(req):
                if resp.HasField("status_update"):
                    states.append(resp.status_update.status.state)
                    su = resp.status_update.status.message
                    if su is not None and su.parts:
                        text = "".join(p.text for p in su.parts if p.HasField("text"))
                        if text:
                            replies.append(text)
            return replies, states

        replies, states = asyncio.run(_run())
        assert any(s == 3 for s in states), f"应到达 COMPLETED，实际 {states}"
        assert any(replies), "应有非空语音回复"


class TestRunBrain:
    def test_run_brain_decision(self):
        """大脑决策应产出动作（不依赖外部 LLM，规则兜底）"""
        result = run_brain_decision("向前走", trace_id="test")
        assert result.get("status") in ("ok", "confirm")
