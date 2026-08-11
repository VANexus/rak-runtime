"""
生命周期钩子（Hooks）— 让大脑在决策时也在学习。

机制借鉴 Claude Code：外部钩子在关键事件点触发，可拦截/注入/记录。
rak-runtime 的钩子是进程内注册表（Python 函数），同步顺序执行；
单个 handler 异常不阻断其余（降级原则）。

事件：
- session_start / session_end：Agent 会话生命周期
- pre_tool_use / post_tool_use：工具调用前后（post 喂学习闭环）
- pre_llm_call / post_llm_call：LLM 调用前后
- memory_update：记忆写入时
"""

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, List

logger = logging.getLogger("rak.hooks")

# 事件名
SESSION_START = "session_start"
SESSION_END = "session_end"
PRE_TOOL_USE = "pre_tool_use"
POST_TOOL_USE = "post_tool_use"
PRE_LLM_CALL = "pre_llm_call"
POST_LLM_CALL = "post_llm_call"
MEMORY_UPDATE = "memory_update"


class HookRegistry:
    """进程内钩子注册表"""

    def __init__(self):
        self._handlers: dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def register(self, event: str, handler: Callable):
        """注册一个钩子处理函数"""
        with self._lock:
            self._handlers[event].append(handler)

    def unregister(self, event: str, handler: Callable):
        with self._lock:
            if handler in self._handlers[event]:
                self._handlers[event].remove(handler)

    def fire(self, event: str, **kwargs: Any) -> List[Any]:
        """
        同步顺序触发。单个 handler 异常不阻断其余（降级原则），
        失败只记日志，绝不向调用方抛。
        """
        results = []
        for handler in list(self._handlers.get(event, [])):
            try:
                results.append(handler(**kwargs))
            except Exception as e:
                logger.warning("[Hook] %s 处理失败: %s", event, e)
        return results

    def handlers(self, event: str) -> List[Callable]:
        return list(self._handlers.get(event, []))

    def stats(self) -> dict:
        return {event: len(hs) for event, hs in self._handlers.items() if hs}


_registry = None
_registry_lock = threading.Lock()


def get_hooks() -> HookRegistry:
    """懒加载全局单例"""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = HookRegistry()
    return _registry
