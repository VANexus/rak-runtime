"""需求预测多特征测试：时间规律 + 历史重复 + 高频设备（P2-3）"""

import asyncio
import datetime

from src.core.user_model import UserModel, InteractionRecord
from src.core.proactive_engine import ProactiveEngine


def _engine_with(user_model) -> ProactiveEngine:
    engine = ProactiveEngine()
    engine.set_dependencies(user_model=user_model)
    return engine


def _routine_3min_ahead() -> str:
    """距当前时刻 3 分钟的 HH:MM"""
    t = datetime.datetime.now() + datetime.timedelta(minutes=3)
    return t.strftime("%H:%M")


def _add_history(um: UserModel, days_ago: list, action: str = "light_on"):
    """注入往日同一场次的交互历史（时间戳取自真实时钟，桶对齐当天）"""
    for d in days_ago:
        dt = datetime.datetime.now() - datetime.timedelta(days=d)
        um._history.append(InteractionRecord(
            timestamp=dt.timestamp(), query="开灯", action_taken=action,
        ))


class TestMultiFeaturePrediction:
    def test_routine_only(self):
        """只有时间规律 → 0.5 + 0.2 = 0.7，触发时刻在未来"""
        um = UserModel()
        um.behavior.time_routines = {_routine_3min_ahead(): ["light"]}
        engine = _engine_with(um)

        needs = asyncio.run(engine._predict_needs())
        assert len(needs) == 1
        assert needs[0].action == "light"
        assert needs[0].confidence == 0.7
        assert needs[0].trigger_time > um.profile.last_seen  # 触发时刻应在未来

    def test_routine_plus_history_plus_frequent(self):
        """三特征齐备 → 0.95 封顶"""
        um = UserModel()
        um.behavior.time_routines = {_routine_3min_ahead(): ["light"]}
        um.behavior.frequent_devices = {"light": 12}
        _add_history(um, [1, 2])  # 往日两个不同日子
        engine = _engine_with(um)

        needs = asyncio.run(engine._predict_needs())
        assert len(needs) == 1
        assert needs[0].confidence == 0.95
        assert "往日" in needs[0].reasoning and "高频" in needs[0].reasoning

    def test_history_only_two_days(self):
        """无规律、无高频，仅往日 2 天重复 → 0.65 可触发"""
        um = UserModel()
        _add_history(um, [1, 3])
        engine = _engine_with(um)

        needs = asyncio.run(engine._predict_needs())
        assert len(needs) == 1
        assert needs[0].confidence == 0.65

    def test_single_day_history_not_a_pattern(self):
        """仅往日 1 天不构成模式（当天数据也不算往日）"""
        um = UserModel()
        _add_history(um, [1])          # 只有 1 个往日
        _add_history(um, [0])          # 今天的数据应被忽略
        engine = _engine_with(um)

        needs = asyncio.run(engine._predict_needs())
        assert needs == []

    def test_frequent_only_reaches_threshold(self):
        """高频设备单独 → 0.6，恰好过 _process_predicted_need 的 0.6 门槛"""
        um = UserModel()
        um.behavior.frequent_devices = {"lock": 15}
        engine = _engine_with(um)

        needs = asyncio.run(engine._predict_needs())
        assert len(needs) == 1
        assert needs[0].confidence == 0.6

    def test_low_frequency_device_not_candidate(self):
        """低频设备（<10 次）不应产生候选"""
        um = UserModel()
        um.behavior.frequent_devices = {"servo": 3}
        engine = _engine_with(um)

        needs = asyncio.run(engine._predict_needs())
        assert needs == []

    def test_process_need_filters_low_confidence(self):
        """低于 0.6 的预测不产生告警"""
        um = UserModel()
        engine = _engine_with(um)

        from src.core.proactive_engine import PredictedNeed
        low = PredictedNeed(action="servo", device="servo", confidence=0.5,
                            reasoning="测试", trigger_time=um.profile.last_seen)
        alerts_before = len(engine._alerts)
        asyncio.run(engine._process_predicted_need(low))
        assert len(engine._alerts) == alerts_before
