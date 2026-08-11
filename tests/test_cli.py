"""CLI（TUI）测试"""

from src.cli.main import render_decision, run_brain


class TestRenderDecision:
    def test_renders_answer_action(self):
        r = render_decision("你好", {
            "status": "ok", "action": "nod", "answer": "好的",
            "trace": ["tool:finalize"],
        })
        assert "Rak：" in r
        assert "nod" in r
        assert "tool:finalize" in r

    def test_renders_confirm(self):
        r = render_decision("x", {"status": "confirm", "message": "确认一下"})
        assert "需要确认" in r

    def test_renders_error(self):
        r = render_decision("x", {
            "status": "error", "error_code": "E1", "error_message": "出错了",
        })
        assert "E1" in r


class TestRunBrain:
    def test_brain_decision_rule_fallback(self, monkeypatch):
        """无 LLM 时走规则兜底仍能决策（或低置信度 confirm）"""
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("RAK_AGENT", "0")  # 直接走单发决策（确定性）
        monkeypatch.setattr("src.core.decision_engine._llm_decide",
                            lambda *a, **k: None)  # LLM 不可用
        result = run_brain("向前走")
        assert result.get("status") in ("ok", "confirm")
        if result.get("status") == "ok":
            assert result.get("action")
