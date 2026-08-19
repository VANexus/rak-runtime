"""Core Memory 块（Letta 实证模式）测试 — labeled 有界记忆 + 系统提示词注入"""

import os

from src.core.core_memory import CoreMemory, get_core_memory, _block_limit


class TestCoreMemory:
    def test_set_get_digest(self):
        cm = CoreMemory()
        cm.set("persona", "我是 Rak")
        cm.set("user", "用户偏好简洁")
        cm.set("session", "当前任务：开灯")
        cm.set("scratch", "临时：先查设备")
        d = cm.digest()
        assert "[persona] 我是 Rak" in d
        assert "[user] 用户偏好简洁" in d
        assert "[session] 当前任务：开灯" in d
        assert "[scratch] 临时：先查设备" in d
        assert "## 核心记忆" in d

    def test_empty_digest(self):
        cm = CoreMemory()
        assert cm.digest() == ""

    def test_unknown_label_goes_to_scratch(self):
        cm = CoreMemory()
        cm.set("nonsense", "x")
        assert cm.get("scratch") == "x"
        cm.set("persona", "p")  # 已知 label 正常
        assert cm.get("persona") == "p"

    @staticmethod
    def _force_limit(cm, limit):
        # 直接改限值测截断
        cm._limit = limit

    def test_bounded_blocks(self):
        cm = CoreMemory()
        self._force_limit(cm, 10)
        cm.set("persona", "这是一段超过限值的内容，应被截断以保上下文有界")
        assert len(cm.get("persona")) <= 10

    def test_block_limit_env(self, monkeypatch):
        monkeypatch.setenv("RAK_CORE_BLOCK_LIMIT", "200")
        assert _block_limit() == 200
        monkeypatch.setenv("RAK_CORE_BLOCK_LIMIT", "abc")
        assert _block_limit(400) == 400  # 非法回退
        monkeypatch.setenv("RAK_CORE_BLOCK_LIMIT", "5")
        assert _block_limit() == 64  # clamp 下限

    def test_singleton(self):
        assert get_core_memory() is get_core_memory()


class TestCoreMemoryPromptInjection:
    def test_prompt_includes_core_memory(self):
        """build_agent_system_prompt 应注入 core memory（且空时不注入段）。"""
        from src.core import agent_loop
        try:
            get_core_memory().set("persona", "我是 Rak")
            get_core_memory().set("session", "测试任务")
            sp = agent_loop.build_agent_system_prompt("", ["idle"])
            assert "## 核心记忆" in sp
            assert "[persona] 我是 Rak" in sp
        finally:
            for label in ("persona", "session"):
                get_core_memory().set(label, "")
