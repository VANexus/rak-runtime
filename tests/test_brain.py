"""统一大脑入口（Brain Facade）测试 — CLI/A2A/benchmark 应共用同一入口"""

from unittest.mock import patch

from src.harness.brain import run_brain, run_brain_single_shot, DEFAULT_ACTIONS


class TestBrainFacade:
    def test_default_actions_is_14_mvp(self):
        assert len(DEFAULT_ACTIONS) == 14
        assert "light_on" in DEFAULT_ACTIONS and "emergency_stop" in DEFAULT_ACTIONS

    def test_run_brain_delegates_to_decision_engine(self):
        """run_brain 应构造标准请求并走 DecisionEngine"""
        calls = {}

        def _fake_decide(self, req):
            calls["req"] = req
            return {"status": "ok", "action": "light_on", "answer": "好"}

        with patch("src.core.decision_engine.DecisionEngine.decide", _fake_decide):
            with patch("src.core.decision_engine.DecisionEngine.__init__",
                       lambda self: None):
                result = run_brain("把灯打开", trace_id="t1", source="cli:user")

        assert result["action"] == "light_on"
        assert calls["req"].state == "把灯打开"
        assert calls["req"].trace_id == "t1"
        assert calls["req"].source == "cli:user"
        assert "light_on" in calls["req"].available_actions

    def test_single_shot_forces_agent_off(self, monkeypatch):
        """单发路径应临时强制 RAK_AGENT=0 并恢复"""
        seen = {}

        def _fake(text, trace_id="", **kw):
            seen["agent"] = __import__("os").environ.get("RAK_AGENT")
            return {"status": "ok", "action": "idle", "answer": ""}

        monkeypatch.delenv("RAK_AGENT", raising=False)
        with patch("src.harness.brain.run_brain", _fake):
            run_brain_single_shot("测试")
        assert seen["agent"] == "0"
        assert "RAK_AGENT" not in __import__("os").environ
