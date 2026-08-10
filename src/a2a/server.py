"""
A2A 服务器 — 标准 Agent2Agent v1.0（官方 a2a-sdk，protobuf 数据面）。

大脑作为 A2A Agent：暴露 Agent Card（/.well-known/agent.json）、
JSON-RPC、REST 与 SSE 流式传输。任何 A2A 客户端/硬件驱动 agent
都能通过 tasks/send 向大脑派发任务。

任务处理：消息文本 → decision_engine.decide()（含 agent 内核深思）
→ 产出动作 + 自然语言回复 → TASK_STATE_COMPLETED。

用法：
    python -m src.a2a.server                 # uvicorn :8000
"""

import asyncio
import logging
import os
import time
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.request_handlers.default_request_handler_v2 import (
    DefaultRequestHandlerV2,
)
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from a2a.helpers.proto_helpers import (
    new_task,
    new_text_artifact_update_event,
    new_text_status_update_event,
)
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

logger = logging.getLogger("rak.a2a")

AVAILABLE_ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "move_forward", "move_back", "turn_left", "turn_right",
    "dance", "nod", "light_on", "light_off",
    "emergency_stop", "idle",
]


def run_brain_decision(text: str, trace_id: str = "") -> dict:
    """把 A2A 消息交给大脑决策（与 gRPC Execute 同路径，含 agent 内核）"""
    from src.core.decision_engine import DecisionEngine
    engine = DecisionEngine()
    req = SimpleNamespace(
        version="v0",
        trace_id=trace_id or f"a2a-{int(time.time() * 1000)}",
        source="a2a:client", target="runtime:default",
        action="", state=text, available_actions=AVAILABLE_ACTIONS,
        params_json="{}",
    )
    return engine.decide(req)


class RakExecutor(AgentExecutor):
    """大脑的 A2A 执行器：消息 → 决策 → 完成事件"""

    async def execute(self, context, event_queue):
        request = getattr(context, "request", None)
        task_id = getattr(context, "task_id", None) or f"task-{int(time.time()*1000)}"
        context_id = getattr(context, "context_id", None) or ""
        text = ""
        user_msg = None
        if request is not None and request.message is not None:
            user_msg = request.message
            for part in user_msg.parts:
                if part.HasField("text"):
                    text += part.text
        logger.info("[A2A] 任务 %s: %s", task_id, text[:50])

        try:
            # 框架要求：先入队 Task 对象，再发状态事件
            await event_queue.enqueue_event(new_task(
                task_id=task_id, context_id=context_id,
                state=TaskState.Value("TASK_STATE_WORKING"),
                history=[user_msg] if user_msg else None,
            ))

            # 决策在独立线程执行（避免阻塞事件循环）
            result = await asyncio.to_thread(run_brain_decision, text, task_id)
            action = result.get("action", "idle")
            answer = result.get("answer") or (f"好的，执行 {action}" if action else "收到")

            # 完成状态 + 语音回复 + 动作 artifact
            await event_queue.enqueue_event(new_text_status_update_event(
                task_id=task_id, context_id=context_id,
                state=TaskState.Value("TASK_STATE_COMPLETED"), text=answer,
            ))
            await event_queue.enqueue_event(new_text_artifact_update_event(
                task_id=task_id, context_id=context_id,
                name="action", text=action,
            ))
            logger.info("[A2A] 任务 %s 完成: action=%s", task_id, action)
        except Exception as e:
            logger.error("[A2A] 任务 %s 失败: %s", task_id, e)
            await event_queue.enqueue_event(new_text_status_update_event(
                task_id=task_id, context_id=context_id,
                state=TaskState.Value("TASK_STATE_FAILED"),
                text=f"任务失败: {e}",
            ))

    async def cancel(self, context, event_queue):
        task_id = getattr(context, "task_id", None) or ""
        context_id = getattr(context, "context_id", None) or ""
        await event_queue.enqueue_event(new_text_status_update_event(
            task_id=task_id, context_id=context_id,
            state=TaskState.Value("TASK_STATE_CANCELED"), text="任务已取消",
        ))


def create_agent_card() -> AgentCard:
    """大脑的 A2A Agent Card"""
    port = os.getenv("RAK_A2A_PORT", "8000")
    base = f"http://localhost:{port}"
    return AgentCard(
        name="Rak",
        description="Rak 具身智能大脑：理解自然语言指令、检索记忆、控制物理设备。",
        version="0.3.0",
        supported_interfaces=[
            AgentInterface(
                url=base,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
            AgentInterface(
                url=base,
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
            ),
        ],
        provider=AgentProvider(organization="RakTec", url="https://open.xrak.xyz"),
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=False,
        ),
        skills=[
            AgentSkill(
                id="decision",
                name="决策执行",
                description="理解自然语言指令并产出可执行的原子动作",
                tags=["decision"],
            ),
            AgentSkill(
                id="memory",
                name="记忆检索",
                description="检索长期记忆、经验与用户偏好",
                tags=["memory"],
            ),
            AgentSkill(
                id="embodiment",
                name="设备控制",
                description="查询与预测物理设备状态，派发动作",
                tags=["iot"],
            ),
        ],
    )


def create_app(card: "AgentCard | None" = None) -> FastAPI:
    """构建 A2A FastAPI 应用（agent card + JSON-RPC + REST + SSE）"""
    card = card or create_agent_card()
    executor = RakExecutor()
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandlerV2(
        agent_executor=executor, task_store=task_store, agent_card=card,
    )

    app = FastAPI(title="Rak A2A Server", version="1.0")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
        rest_routes=create_rest_routes(handler),
    )
    return app


def main():
    port = int(os.getenv("RAK_A2A_PORT", "8000"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Rak A2A 服务器启动 :%d", port)
    uvicorn.run(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
