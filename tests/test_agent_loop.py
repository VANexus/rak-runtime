"""Agentic 内核测试"""

import os
from unittest.mock import patch

import pytest

from src.core import decision_engine as de
from src.core import agent_loop


class TestRunAgent:
    def test_empty_actions_returns_none(self):
        """无可用动作应返回 None（不调模型）"""
        assert agent_loop.run_agent("hi", [], system_prompt="x") is None

    def test_model_failure_degrades(self):
        """模型创建失败应返回 None（上层降级）"""
        with patch("src.core._utils.make_langchain_anthropic",
                   side_effect=RuntimeError("no model")):
            result = agent_loop.run_agent("hi", ["nod"], system_prompt="x")
        assert result is None


class TestAgentDecide:
    def test_agent_failure_falls_back_to_json(self, monkeypatch):
        """agent 失败应降级单发 JSON 决策"""
        monkeypatch.setenv("RAK_AGENT", "1")
        engine = de.DecisionEngine()
        with patch("src.core.agent_loop.run_agent", return_value=None):
            with patch("src.core.decision_engine._llm_decide",
                       return_value={"action": "nod", "params_json": "{}",
                                     "answer": "好的"}):
                result = engine._agent_decide("你好", ["nod"], "sys", "user")
        assert result["action"] == "nod"

    def test_agent_success_used(self, monkeypatch):
        """agent 成功应使用其决策"""
        monkeypatch.setenv("RAK_AGENT", "1")
        engine = de.DecisionEngine()
        with patch("src.core.agent_loop.run_agent",
                   return_value={"action": "wave_hand", "params_json": "{}",
                                 "answer": "好的", "trace": ["llm→finalize"]}):
            result = engine._agent_decide("你好", ["wave_hand"], "sys", "user")
        assert result["action"] == "wave_hand"

    def test_agent_disabled(self, monkeypatch):
        """RAK_AGENT=0 应直接走单发决策"""
        monkeypatch.setenv("RAK_AGENT", "0")
        engine = de.DecisionEngine()
        with patch("src.core.decision_engine._llm_decide",
                   return_value={"action": "nod"}):
            with patch("src.core.agent_loop.run_agent",
                       side_effect=AssertionError("不应调用 agent")):
                result = engine._agent_decide("你好", ["nod"], "sys", "user")
        assert result["action"] == "nod"


class TestRealAgent:
    def test_real_model_agent_loop(self):
        """真实模型 agent 端到端（需 ANTHROPIC_AUTH_TOKEN）"""
        if not os.getenv("ANTHROPIC_AUTH_TOKEN"):
            pytest.skip("无 API token")
        result = agent_loop.run_agent(
            "帮我开灯", ["light_on", "light_off"],
            system_prompt="你是 Rak，一个具身智能助手，控制物理设备。回复简洁。",
        )
        assert result is not None, "agent 应调用 finalize 产出决策"
        assert result["action"] in ("light_on", "light_off")
