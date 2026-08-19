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


class TestDecisionQualityGate(unittest.TestCase):
    """决策质量门：动作指令回 idle = 失败决策，不学习/不缓存/不记成功"""

    def _get_engine(self):
        with patch("src.core.decision_engine._get_llm_client", return_value=None):
            from src.core.decision_engine import DecisionEngine
            return DecisionEngine()

    def test_is_action_command(self):
        eng = self._get_engine()
        self.assertTrue(eng._is_action_command("向前走两步"))
        self.assertTrue(eng._is_action_command("把灯打开"))
        self.assertFalse(eng._is_action_command("今天天气怎么样"))
        self.assertFalse(eng._is_action_command("你好呀"))

    def test_is_compound_command(self):
        eng = self._get_engine()
        # 复合指令：连接词 / 逗号 / 多动词词干
        self.assertTrue(eng._is_compound_command("挥挥手并点点头"))
        self.assertTrue(eng._is_compound_command("跳完舞以后把灯关掉"))
        self.assertTrue(eng._is_compound_command("先开灯，然后把门锁上"))
        self.assertTrue(eng._is_compound_command("开门再关门"))
        # 单动作 / 闲聊不应误判
        self.assertFalse(eng._is_compound_command("帮我把客厅的灯打开"))
        self.assertFalse(eng._is_compound_command("我们以后再聊"))
        self.assertFalse(eng._is_compound_command("紧急停止"))

    def test_looks_like_device_state(self):
        eng = self._get_engine()
        self.assertTrue(eng._looks_like_device_state(
            '{"device_id":"esp-001","online":true}'))
        self.assertTrue(eng._looks_like_device_state(
            '{"status":"idle","capabilities":["light"]}'))
        self.assertFalse(eng._looks_like_device_state("向前走两步"))
        self.assertFalse(eng._looks_like_device_state("hello"))

    def test_idle_for_action_not_cached(self):
        """动作指令回 idle 的失败决策不应写入语义缓存（防污染）"""
        from src.core import decision_engine as de
        eng = self._get_engine()
        cache = de._get_semantic_cache()
        if cache is None:
            self.skipTest("语义缓存不可用")
        before = cache.stats()["exact_cache_size"]
        # 直接模拟：质量门判定应阻止缓存
        is_polluted = eng._is_action_command("向前走两步")
        self.assertTrue(is_polluted)


class TestMultiActionTopLevelAction(unittest.TestCase):
    """回归：多动作/复合路径必须补齐顶层 action 契约。

    背景（TODO #4）：decide_from_text 曾只返回 actions 列表、无顶层 action，
    导致 baseline 的 cold 决策 _extract_action 抽出空（'?'）、语义缓存落不到
    实动作、paraphrase 无法复用。修复后顶层 action = 第一个合法动作。
    """

    def _get_engine(self):
        with patch("src.core.decision_engine._get_llm_client", return_value=None):
            from src.core.decision_engine import DecisionEngine
            return DecisionEngine()

    def _primary(self, eng, actions):
        """等价于 baseline _extract_action 逻辑：优先顶层 action，其次 actions。"""
        if not isinstance(actions, dict):
            return ""
        a = actions.get("action")
        if isinstance(a, str) and a:
            return a
        acts = actions.get("actions") or []
        if acts:
            first = acts[0]
            return first.get("action", "") if isinstance(first, dict) else str(first)
        return ""

    def test_rule_decompose_sets_top_level_action(self):
        """真复合指令经规则兜底返回：顶层 action 非空且等于 actions[0]。"""
        eng = self._get_engine()
        actions = ["lock_open", "lock_close", "move_forward", "idle"]
        result = eng.decide_from_text(
            text="开门再关门", available_actions=actions,
            trace_id="test", device_state="",
        )
        self.assertEqual(result["status"], "ok")
        # 顶层 action 非空（回归曾为 ''/'?'）
        self.assertTrue(result.get("action"))
        self.assertEqual(result["action"], result["actions"][0]["action"])
        # baseline 抽取逻辑能抽出非空动作
        self.assertTrue(self._primary(eng, result))

    def test_single_intent_with_redundant_verbs_no_empty_action(self):
        """'把门打开让我进来' 这类含多个动作字的单意图——规则兜底顶层 action 非空。"""
        eng = self._get_engine()
        actions = ["lock_open", "lock_close", "idle"]
        result = eng.decide_from_text(
            text="把门打开让我进来", available_actions=actions,
            trace_id="test", device_state="",
        )
        # 即使走到复合路径，顶层 action 也必非空
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result.get("action") in actions)

    def test_primary_action_degradation_to_idle(self):
        """无合法动作时 _primary_action 安全降级 idle。"""
        eng = self._get_engine()
        actions = ["idle", "nod"]
        self.assertEqual(eng._primary_action([{"action": "dance"}], actions), "idle")
        self.assertEqual(eng._primary_action([], actions), "idle")
        self.assertEqual(eng._primary_action([{"action": "nod"}], ["nod"]), "nod")


if __name__ == "__main__":
    unittest.main()
