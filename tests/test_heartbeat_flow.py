"""心跳流集成测试 — 决策事件应驱动情绪/需求更新（事件循环桥接）"""

import asyncio
import threading
from unittest.mock import MagicMock

from src.core import decision_engine as de


class TestHeartbeatFlow:
    def test_decision_event_drives_emotion(self):
        """决策事件（经 InnerLoop）应更新情绪状态"""
        # 重置 + 接线
        de._inner_loop = None
        de._emotion_engine = None
        inner = de._get_inner_loop()
        emotion = de._get_emotion_engine()
        de._wire_cognitive_graph()

        de.DecisionEngine()  # 触发完整接线

        async def _run():
            await inner.start()
            # 从非事件循环线程触发（模拟 gRPC 线程池）
            def _fire():
                inner.on_event("decision", {"success": True, "action": "nod"})

            t = threading.Thread(target=_fire)
            t.start()
            t.join()
            await asyncio.sleep(0.3)  # 让 call_soon_threadsafe 处理完
            stats = inner.get_stats()
            assert stats["total_events"] >= 1
            await inner.stop()

        asyncio.run(_run())
        # 成功事件 → joy 上升（0.5 → 0.6）
        assert emotion.state.joy > 0.5

    def test_event_from_same_thread_direct(self):
        """事件循环线程内调用 on_event 应同步处理"""
        de._inner_loop = None
        inner = de._get_inner_loop()
        de._wire_cognitive_graph()

        async def _run():
            await inner.start()
            inner.on_event("decision", {"success": False, "action": "wave"})
            await asyncio.sleep(0.1)
            assert inner.get_stats()["total_events"] >= 1
            await inner.stop()

        asyncio.run(_run())
