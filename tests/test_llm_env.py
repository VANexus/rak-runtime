"""LLM 环境配置测试 — RAK_LLM_* 覆盖全局代理 + LongCat 兼容"""

import pytest

from src.core import _utils


class TestResolveLLMEnv:
    def test_rak_llm_overrides_global_proxy(self, monkeypatch):
        """RAK_LLM_* 应覆盖宿主机全局 ANTHROPIC_* 代理"""
        # 模拟宿主机全局代理
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:15721")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "global-proxy-token")
        monkeypatch.delenv("RAK_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("RAK_LLM_API_KEY", raising=False)
        monkeypatch.delenv("RAK_LLM_AUTH_SCHEME", raising=False)
        monkeypatch.delenv("LONGCAT_API_KEY", raising=False)
        key, base, scheme = _utils.resolve_llm_env()
        assert key == "global-proxy-token"
        assert base == "http://127.0.0.1:15721"
        assert scheme == "api_key"

    def test_rak_llm_explicit_wins(self, monkeypatch):
        """显式 RAK_LLM_* 优先于全局代理"""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:15721")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "global")
        monkeypatch.setenv("RAK_LLM_BASE_URL", "https://api.longcat.chat/anthropic")
        monkeypatch.setenv("RAK_LLM_API_KEY", "ak_longcat")
        monkeypatch.delenv("RAK_LLM_AUTH_SCHEME", raising=False)
        key, base, scheme = _utils.resolve_llm_env()
        assert key == "ak_longcat"
        assert base == "https://api.longcat.chat/anthropic"
        assert scheme == "bearer"  # longcat 自动推断 bearer

    def test_longcat_key_auto_base(self, monkeypatch):
        """仅 LONGCAT_API_KEY 时自动用 LongCat base + bearer"""
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("RAK_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("RAK_LLM_API_KEY", raising=False)
        monkeypatch.setenv("LONGCAT_API_KEY", "ak_x")
        key, base, scheme = _utils.resolve_llm_env()
        assert base == "https://api.longcat.chat/anthropic"
        assert scheme == "bearer"

    def test_model_precedence(self, monkeypatch):
        monkeypatch.setenv("RAK_LLM_MODEL", "LongCat-2.0")
        monkeypatch.setenv("ANTHROPIC_MODEL", "mimo-v2.5-pro")
        assert _utils.get_model() == "LongCat-2.0"
        monkeypatch.delenv("RAK_LLM_MODEL", raising=False)
        assert _utils.get_model() == "mimo-v2.5-pro"
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        assert _utils.get_model() == "mimo-v2.5-pro"


class TestThinkingExtra:
    def test_disabled_omits_thinking(self, monkeypatch):
        """默认（RAK_THINKING=0）不传 thinking —— LongCat-2.0 拒绝显式 disabled"""
        monkeypatch.delenv("RAK_THINKING", raising=False)
        assert _utils.thinking_extra() == {}

    def test_enabled_sends_thinking(self, monkeypatch):
        monkeypatch.setenv("RAK_THINKING", "1")
        assert _utils.thinking_extra() == {"thinking": {"type": "enabled"}}
