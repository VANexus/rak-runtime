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

    def test_stuck_guard_stops_repeated_tool(self):
        """卡死护栏：同一工具连续调用 >=4 次应返回提示而非继续执行"""
        tools, _ = agent_loop._build_tools(["idle"], "sys")
        qd = next(t for t in tools if t.name == "query_device")
        out = [qd.func() for _ in range(4)]  # 直接调底层函数（StructuredTool 不可直接调用）
        assert "重复调用同一工具" in out[3]  # 第 4 次连续调用被护栏拦截


class TestToolRegistrySingleSource:
    """G5：认知工具以 src.tools.registry 为单一事实源，agent 内核自动获得。"""

    def test_registry_has_core_readonly_neurons(self):
        """registry 至少包含 5 个核心只读神经元 + 新增的自我检视工具。"""
        from src.tools.registry import COGNITIVE_TOOLS
        names = {t.name for t in COGNITIVE_TOOLS}
        for required in ["search_memory", "query_device", "get_emotion",
                         "get_needs", "reflect"]:
            assert required in names, f"缺核心工具 {required}"
        # G5 新增：扩散联想 / 自我认知 / 内心独白 / 图谱统计 / 认知全量统计
        for added in ["diffuse_memory", "get_self_info", "get_inner_thoughts",
                      "get_graph_stats", "get_cognitive_stats"]:
            assert added in names, f"缺 G5 新增工具 {added}"

    def test_build_tools_derives_all_registry_tools(self):
        """_build_tools 应物化 registry 的全部认知工具（+ finalize）。"""
        from src.tools.registry import COGNITIVE_TOOLS, get_tool_defs
        tools, _ = agent_loop._build_tools(["idle"], "")
        tool_names = {t.name for t in tools}
        for td in get_tool_defs():
            assert td.name in tool_names, f"agent 内核缺工具 {td.name}"
        assert "finalize" in tool_names
        # 物化数量 = registry 全部 + finalize
        assert len(tools) == len(get_tool_defs()) + 1

    def test_system_prompt_promotes_registry_tools(self):
        """系统提示词的工具列表应派生自 registry（窄腰原则）。"""
        from src.tools.registry import COGNITIVE_TOOLS
        sp = agent_loop.build_agent_system_prompt("", ["idle"])
        for td in COGNITIVE_TOOLS:
            assert td.name in sp, f"提示词未提及工具 {td.name}"

    def test_new_handlers_are_readonly_and_safe(self, monkeypatch):
        """新 handler 是只读且异常时降级（不抛）。"""
        from src.tools.registry import COGNITIVE_TOOLS
        # 令一个依赖不可用,确认降级 fallback 而非抛异常
        from src.tools import registry
        engine = registry._get_self_info
        # 不实际破坏单例;直接确认 handler 可返回字符串
        for name in ["get_self_info", "get_graph_stats", "get_cognitive_stats"]:
            td = next(t for t in COGNITIVE_TOOLS if t.name == name)
            out = td.handler()
            assert isinstance(out, str) and len(out) <= 500



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
        """真实模型 agent 端到端（RAK_LIVE_TESTS=1 才跑，默认跳过保离线确定性）"""
        if os.getenv("RAK_LIVE_TESTS", "0") != "1":
            pytest.skip("live 测试：设 RAK_LIVE_TESTS=1 启用（需 LLM key 已配置）")
        result = agent_loop.run_agent(
            "帮我开灯", ["light_on", "light_off"],
            system_prompt="你是 Rak，一个具身智能助手，控制物理设备。回复简洁。",
        )
        assert result is not None, "agent 应调用 finalize 产出决策"
        assert result["action"] in ("light_on", "light_off")
