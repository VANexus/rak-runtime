"""
Core Memory 块（借鉴 Letta/MemGPT 实证架构）— 稳定、有界、总是注入模型的记忆。

Letta 的 memory architecture 区分三层：core memory（总是 in-context，按 label 分子块
persona/user/session/scratch，每块有字符上限 + 只读配置）、recall memory（全文历史）与
archival memory（无限存储但需显式检索）。rak-runtime 已有 recall（short-term/episodic）
与 archival（SuperMemory/MemoryGraph）层；本模块补齐『core memory』层：labeled、有界、
always-in-context 的稳定快照，注入 agent/brain 的系统提示词。

块：
- persona：我是谁（默认取 SelfModel.who_am_i 抽象）
- user：用户画像（默认取 UserModel 摘要）
- session：当前会话/任务状态
- scratch：临时工作记忆（每轮可覆写）

每块字符上限用 env 可配（RAK_CORE_BLOCK_LIMIT，默认 400），防止上下文膨胀。
任何块读取失败降级为空串（窄腰原则），不阻断决策。
"""

import logging
import os
import threading

logger = logging.getLogger("rak.core_memory")


def _block_limit(default: int = 400) -> int:
    """单块字符上限（env 可配，防上下文膨胀）。"""
    try:
        return max(64, int(os.getenv("RAK_CORE_BLOCK_LIMIT", str(default))))
    except (TypeError, ValueError):
        return default


class CoreMemory:
    """labeled + bounded 的 core memory 块集合（Letta 实证模式）。"""

    def __init__(self):
        self._limit = _block_limit()
        self._blocks = {
            "persona": "",
            "user": "",
            "session": "",
            "scratch": "",
        }

    def set(self, label: str, value: str) -> None:
        """写入某块（超限截断以保上下文有界）。"""
        label = label if label in self._blocks else "scratch"
        value = (value or "").strip()
        if len(value) > self._limit:
            value = value[: self._limit]  # 有界：防上下文膨胀
        self._blocks[label] = value

    def get(self, label: str) -> str:
        return self._blocks.get(label, "")

    def digest(self) -> str:
        """把有内容的块组装成 labeled 文本注入提示词（空块跳过）。"""
        parts = []
        for label in ("persona", "user", "session", "scratch"):
            v = self._blocks.get(label, "").strip()
            if v:
                parts.append(f"[{label}] {v[: self._limit]}")
        if not parts:
            return ""
        return "## 核心记忆（Core Memory）\n" + "\n".join(parts)

    def stats(self) -> dict:
        return {
            "block_limit": self._limit,
            "blocks": {k: len(v) for k, v in self._blocks.items()},
        }


_instance = None
_lock = threading.Lock()


def get_core_memory() -> CoreMemory:
    """懒加载全局单例。"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = CoreMemory()
    return _instance
