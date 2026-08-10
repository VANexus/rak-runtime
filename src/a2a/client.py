"""
A2A 客户端 — 大脑主动向硬件驱动/外部 Agent 派发任务。

把官方 a2a-sdk 的 client 封装成同步调用，供 outbound 出站通道使用。
"""

import asyncio
import logging
import time

logger = logging.getLogger("rak.a2a.client")

from a2a.client import create_client
from a2a.types.a2a_pb2 import Message, Part, Role, SendMessageRequest


async def _dispatch_async(agent_url: str, text: str, timeout: float) -> str:
    """向 A2A Agent 派发文本任务，收集回复（异步）"""
    client = await create_client(agent_url)
    req = SendMessageRequest(message=Message(
        message_id=f"rak-{int(time.time() * 1000)}",
        role=Role.ROLE_USER, parts=[Part(text=text)],
    ))
    replies = []
    async for resp in client.send_message(req):
        if resp.HasField("status_update"):
            su = resp.status_update.status
            if su.message is not None:
                for p in su.message.parts:
                    if p.HasField("text") and p.text:
                        replies.append(p.text)
    return "\n".join(replies)


def dispatch_task(agent_url: str, text: str, timeout: float = 30.0) -> str:
    """向一个 A2A Agent 派发文本任务（同步封装），返回回复文本。

    失败抛异常，由调用方降级（如 MQTT 兜底）。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            asyncio.wait_for(_dispatch_async(agent_url, text, timeout), timeout)
        )
    finally:
        loop.close()
