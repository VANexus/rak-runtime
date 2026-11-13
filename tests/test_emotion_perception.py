"""文本语气情绪感知测试：词典法 + 否定削弱 + 六维融入（P2-4）"""

import pytest

from src.core.emotion_perception import EmotionPerception
from src.core.emotion_state import EmotionEngine


@pytest.fixture
def perception():
    return EmotionPerception()


class TestPerceive:
    def test_anger_detected(self, perception):
        """愤怒措辞 → anger，感叹号抬升强度"""
        p = perception.perceive("滚开！烦死了！")
        assert p["emotion"] == "anger"
        assert p["intensity"] >= 0.5
        assert p["method"] == "lexicon"

    def test_joy_detected(self, perception):
        p = perception.perceive("太好了，谢谢你！")
        assert p["emotion"] == "joy"

    def test_sadness_detected(self, perception):
        p = perception.perceive("我最近好难过，很失望")
        assert p["emotion"] == "sadness"

    def test_surprise_detected(self, perception):
        p = perception.perceive("怎么可能？？")
        assert p["emotion"] == "surprise"
        assert p["intensity"] >= 0.6  # 连续问号加成

    def test_neutral_instruction(self, perception):
        """普通指令不应误判情绪"""
        p = perception.perceive("帮我开一下灯")
        assert p["emotion"] == "neutral"
        assert p["intensity"] == 0.0

    def test_negation_weakens_and_flips(self, perception):
        """"不太满意" 应翻转为轻度消极，而非积极"""
        p = perception.perceive("不太满意这个结果")
        assert p["emotion"] == "sadness"
        assert p["intensity"] < 0.5

    def test_empty_and_short_input(self, perception):
        assert perception.perceive("")["emotion"] == "neutral"
        assert perception.perceive("好")["emotion"] == "neutral"


class TestApplyTo:
    def test_angry_text_raises_anger(self, perception):
        """愤怒文本应抬升 anger 维度"""
        engine = EmotionEngine()
        before = engine.state.anger
        perception.apply_to(engine, "你们这个产品真的太让人恼火了！")
        assert engine.state.anger > before

    def test_joyful_text_raises_joy_and_trust(self, perception):
        engine = EmotionEngine()
        before_joy, before_trust = engine.state.joy, engine.state.trust
        perception.apply_to(engine, "太棒了，非常谢谢！")
        assert engine.state.joy > before_joy
        assert engine.state.trust > before_trust

    def test_neutral_text_leaves_state(self, perception):
        """中性文本不动状态"""
        engine = EmotionEngine()
        snapshot = dict(engine.state.__dict__)
        perception.apply_to(engine, "帮我查一下天气")
        assert dict(engine.state.__dict__) == snapshot

    def test_low_intensity_below_threshold_skipped(self, perception):
        """强度 <0.3 的感知不进状态（如被否定的轻度消极 0.24）"""
        engine = EmotionEngine()
        before = engine.state.sadness
        p = perception.apply_to(engine, "不太满意这个结果")
        assert p["intensity"] < 0.3
        assert engine.state.sadness == before


class TestEngineGetter:
    def test_decision_engine_getter(self):
        """decision_engine 应能懒初始化感知器"""
        from src.core import decision_engine as de
        de._emotion_perception = None
        p = de._get_emotion_perception()
        assert p is not None
        assert hasattr(p, "apply_to")
