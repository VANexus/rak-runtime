"""
Agent 会话（Agent Session）— 可诊断/可重放的决策记录。

每次 run_agent 生成一个 AgentSession：
- 记录 LLM 消息、工具调用轨迹（参数/结果/耗时/状态）、最终决策
- JSONL 持久化到 data/sessions/<session_id>.jsonl
- 供审计、重放、学习闭环（工具轨迹进学习）

设计借鉴：hermes 的 SQLite+FTS5 会话、Claude Code 的 JSONL transcript。
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("rak.session")


@dataclass
class ToolTraceEvent:
    """一次工具调用轨迹"""
    tool: str
    args: dict
    result: str
    duration_ms: float
    status: str                 # ok / error
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionMessage:
    """一条会话消息"""
    role: str                   # system / user / assistant / tool
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentSession:
    """一次 agent 决策会话"""
    session_id: str
    trace_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "running"     # running / completed / error
    messages: list = field(default_factory=list)       # list[SessionMessage]
    tool_traces: list = field(default_factory=list)    # list[ToolTraceEvent]
    final_decision: dict = field(default_factory=dict)

    def append_message(self, role: str, content: str):
        self.messages.append(SessionMessage(role=role, content=content))
        self.updated_at = time.time()

    def append_tool_trace(self, trace: ToolTraceEvent):
        self.tool_traces.append(trace)
        self.updated_at = time.time()

    def mark_completed(self, decision: dict):
        self.final_decision = decision
        self.status = "completed"
        self.updated_at = time.time()

    def mark_error(self, message: str = ""):
        self.status = "error"
        self.updated_at = time.time()
        if message:
            self.append_message("assistant", f"[error] {message}")

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "messages": [asdict(m) for m in self.messages],
            "tool_traces": [asdict(t) for t in self.tool_traces],
            "final_decision": self.final_decision,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSession":
        session = cls(
            session_id=data["session_id"], trace_id=data.get("trace_id", ""),
            created_at=data.get("created_at", 0),
            updated_at=data.get("updated_at", 0),
            status=data.get("status", "running"),
            final_decision=data.get("final_decision", {}),
        )
        session.messages = [SessionMessage(**m) for m in data.get("messages", [])]
        session.tool_traces = [ToolTraceEvent(**t) for t in data.get("tool_traces", [])]
        return session

    def summary(self) -> dict:
        """会话摘要（供 stats/监控）"""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "messages": len(self.messages),
            "tool_calls": len(self.tool_traces),
            "tools_used": sorted({t.tool for t in self.tool_traces}),
            "action": self.final_decision.get("action", ""),
            "duration_sec": round(self.updated_at - self.created_at, 2),
        }


class SessionStore:
    """会话持久化（JSONL 每会话一文件）"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sessions")
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def _path(self, session_id: str) -> str:
        return os.path.join(self.data_dir, f"{session_id}.json")

    def save(self, session: AgentSession):
        path = self._path(session.session_id)
        try:
            from src.core._utils import atomic_write_json
            atomic_write_json(path, session.to_dict())
        except Exception as e:
            logger.warning("[Session] 保存失败 %s: %s", session.session_id, e)

    def load(self, session_id: str) -> Optional[AgentSession]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return AgentSession.from_dict(json.load(f))
        except Exception as e:
            logger.warning("[Session] 加载失败 %s: %s", session_id, e)
            return None

    def list_recent(self, n: int = 10) -> list[dict]:
        """最近 n 个会话的摘要"""
        try:
            files = sorted(
                (f for f in os.listdir(self.data_dir) if f.endswith(".json")),
                key=lambda f: os.path.getmtime(os.path.join(self.data_dir, f)),
                reverse=True,
            )
        except OSError:
            return []
        summaries = []
        for f in files[:n]:
            session = self.load(f[:-5])  # 去掉 .json
            if session:
                summaries.append(session.summary())
        return summaries


_store = None


def get_session_store() -> SessionStore:
    """懒加载单例"""
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
