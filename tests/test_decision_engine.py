"""
Unit tests for the decision engine rule-based fallback.
Tests the keyword-to-action mapping and task decomposition without LLM.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRuleDecompose(unittest.TestCase):
    """测试规则引擎的任务分解功能"""

    def _get_engine(self):
        """创建 DecisionEngine 实例，跳过 LLM 初始化"""
        with patch("src.core.decision_engine._get_llm_client", return_value=None):
            with patch("src.core.decision_engine._get_memory_engine", return_value=None):
                from src.core.decision_engine import DecisionEngine
                return DecisionEngine()

    def test_single_chinese_keyword(self):
        """单个中文关键词应映射到正确的动作"""
        engine = self._get_engine()
        actions = ["lock_open", "lock_close", "move_forward", "move_back",
                    "wave_hand", "shake_head", "nod", "dance", "emergency_stop"]
        result = engine._rule_decompose("开门", actions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "lock_open")

    def test_single_english_keyword(self):
        """单个英文关键词应映射到正确的动作"""
        engine = self._get_engine()
        actions = ["lock_open", "lock_close", "move_forward", "wave_hand"]
        result = engine._rule_decompose("forward", actions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "move_forward")

    def test_multiple_keywords(self):
        """多个关键词应分解为多个动作"""
        engine = self._get_engine()
        actions = ["lock_open", "move_forward", "wave_hand", "shake_head"]
        result = engine._rule_decompose("开门然后前进", actions)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["action"], "lock_open")
        self.assertEqual(result[1]["action"], "move_forward")

    def test_longer_keyword_priority(self):
        """较长的关键词应优先匹配（如'打开门'优于'开门'）"""
        engine = self._get_engine()
        actions = ["lock_open", "lock_close"]
        result = engine._rule_decompose("打开门", actions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "lock_open")

    def test_unavailable_action_skipped(self):
        """不在可用列表中的动作应被跳过"""
        engine = self._get_engine()
        actions = ["move_forward"]  # lock_open 不在可用列表中
        result = engine._rule_decompose("开门", actions)
        # lock_open 不可用，应被跳过
        for r in result:
            self.assertIn(r["action"], actions)

    def test_no_match_fallback(self):
        """无匹配时应返回默认动作"""
        engine = self._get_engine()
        actions = ["wave_hand", "shake_head"]
        result = engine._rule_decompose("你好世界", actions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "wave_hand")  # 第一个可用动作

    def test_empty_actions(self):
        """空动作列表应返回空结果"""
        engine = self._get_engine()
        result = engine._rule_decompose("开门", [])
        self.assertEqual(len(result), 0)

    def test_priority_classification(self):
        """规则引擎应将所有匹配的动作设为 Q1 优先级"""
        engine = self._get_engine()
        actions = ["lock_open", "move_forward"]
        result = engine._rule_decompose("开门前进", actions)
        for r in result:
            self.assertEqual(r["priority"], 1)  # Q1

    def test_params_json_format(self):
        """每个动作应包含合法的 params_json"""
        engine = self._get_engine()
        actions = ["lock_open", "dance"]
        result = engine._rule_decompose("开门", actions)
        for r in result:
            params = json.loads(r["params_json"])
            self.assertIsInstance(params, dict)


class TestActionClassification(unittest.TestCase):
    """测试动作优先级分类（与 go-kernel 对齐）"""

    def test_classify_action_from_scheduler(self):
        """go-kernel 的 ClassifyAction 应正确分类"""
        # 这里测试 rak-runtime 的规则引擎分类逻辑
        with patch("src.core.decision_engine._get_llm_client", return_value=None):
            with patch("src.core.decision_engine._get_memory_engine", return_value=None):
                from src.core.decision_engine import DecisionEngine
                engine = DecisionEngine()

        actions = ["lock_open", "lock_close", "move_forward", "move_back",
                    "wave_hand", "shake_head", "nod", "dance",
                    "light_on", "light_off", "emergency_stop"]

        # lock_open 应该在可用列表中
        result = engine._rule_decompose("开门", actions)
        self.assertTrue(any(r["action"] == "lock_open" for r in result))

        # dance 应该在可用列表中
        result = engine._rule_decompose("跳舞", actions)
        self.assertTrue(any(r["action"] == "dance" for r in result))

        # emergency_stop 应该在可用列表中
        result = engine._rule_decompose("停止", actions)
        self.assertTrue(any(r["action"] == "emergency_stop" for r in result))


class TestValidateRequest(unittest.TestCase):
    """测试请求验证逻辑"""

    def _get_engine(self):
        with patch("src.core.decision_engine._get_llm_client", return_value=None):
            with patch("src.core.decision_engine._get_memory_engine", return_value=None):
                from src.core.decision_engine import DecisionEngine
                return DecisionEngine()

    def test_valid_request_with_action(self):
        """有 action 的请求应通过验证"""
        engine = self._get_engine()
        request = MagicMock()
        request.action = "lock_open"
        request.available_actions = ["lock_open", "lock_close"]
        request.state = ""
        request.params_json = "{}"
        request.audio = None

        result = engine._validate_request(request)
        self.assertTrue(result["is_valid"])

    def test_valid_request_with_state(self):
        """有 state 的请求应通过验证"""
        engine = self._get_engine()
        request = MagicMock()
        request.action = ""
        request.available_actions = ["lock_open"]
        request.state = "door is closed"
        request.params_json = ""
        request.audio = None

        result = engine._validate_request(request)
        self.assertTrue(result["is_valid"])

    def test_invalid_request_no_action_no_state(self):
        """既没有 action 也没有 state 的请求应失败"""
        engine = self._get_engine()
        request = MagicMock()
        request.action = ""
        request.available_actions = ["lock_open"]
        request.state = ""
        request.params_json = ""
        request.audio = None

        result = engine._validate_request(request)
        self.assertFalse(result["is_valid"])


if __name__ == "__main__":
    unittest.main()
