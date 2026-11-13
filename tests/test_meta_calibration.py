"""置信度校准测试：从实际成功率反调（P2-2）"""

import pytest

from src.core.meta_cognition import MetaCognition, ConfidenceLevel


class TestCalibrationBucket:
    def test_record_outcome_feeds_bucket(self):
        """结果应按预测置信度入桶统计"""
        meta = MetaCognition()
        meta.record_decision("q1", "cache", 0.9)
        meta.record_outcome("q1", was_correct=True)
        assert meta._calibration["high"]["n"] == 1
        assert meta._calibration["high"]["correct"] == 1
        assert meta._calibration["high"]["sum_predicted"] == pytest.approx(0.9)

    def test_record_outcome_no_match_is_noop(self):
        """无匹配决策记录时不应崩、不应污染校准桶"""
        meta = MetaCognition()
        meta.record_outcome("不存在", was_correct=False)
        assert meta._calibration == {}


class TestCalibratedScore:
    def _overconfident_meta(self, n=30):
        """构造"预测 0.9 实际只对 20%"的高置信桶"""
        meta = MetaCognition()
        for i in range(n):
            meta.record_decision(f"q{i}", "cache", 0.9)
            meta.record_outcome(f"q{i}", was_correct=(i % 5 == 0))
        return meta

    def test_insufficient_samples_identity(self):
        """样本不足时校准为恒等"""
        meta = self._overconfident_meta(n=5)
        assert meta._calibrated_score(0.9) == 0.9

    def test_overconfidence_pulled_down(self):
        """长期乐观的桶应把分数拉下来"""
        meta = self._overconfident_meta()
        adjusted = meta._calibrated_score(0.9)
        # ratio = 0.2/0.9 → 限幅 0.5；weight = 30/50 → 0.9*(1+0.6*(-0.5)) ≈ 0.63
        assert adjusted == pytest.approx(0.63, abs=0.02)
        assert adjusted < 0.85

    def test_underconfidence_pushed_up(self):
        """长期保守且全对的桶应把分数抬上去"""
        meta = MetaCognition()
        for i in range(30):
            meta.record_decision(f"q{i}", "rule", 0.4)
            meta.record_outcome(f"q{i}", was_correct=True)
        adjusted = meta._calibrated_score(0.4)
        # ratio = 1.0/0.4 → 限幅 1.5；0.4*(1+0.6*0.5) = 0.52
        assert adjusted == pytest.approx(0.52, abs=0.02)

    def test_evaluated_level_downgraded(self):
        """过度自信的精确缓存命中应被降级出 HIGH"""
        meta = self._overconfident_meta()
        assessment = meta.evaluate_confidence(
            "打开灯", cache_hit=True, cache_similarity=0.99, user_expertise=0.5,
        )
        assert assessment.level != ConfidenceLevel.HIGH
        assert assessment.score < 0.85


class TestReflectThresholds:
    def test_poor_accuracy_tightens_high_threshold(self):
        """高置信准确率 <80% 时应收紧 high 阈值"""
        meta = MetaCognition()
        for i in range(12):
            meta.record_decision(f"q{i}", "llm", 0.9)
            meta.record_outcome(f"q{i}", was_correct=False)
        result = meta.reflect()
        assert result["status"] == "ok"
        assert meta._level_thresholds["high"] == pytest.approx(0.87)
        assert any("收紧" in i for i in result["insights"])

    def test_excellent_accuracy_loosens_high_threshold(self):
        """高置信准确率 ≥95% 时应适度放松 high 阈值"""
        meta = MetaCognition()
        for i in range(12):
            meta.record_decision(f"q{i}", "llm", 0.9)
            meta.record_outcome(f"q{i}", was_correct=True)
        meta.reflect()
        assert meta._level_thresholds["high"] == pytest.approx(0.84)

    def test_thresholds_clamped(self):
        """阈值应被限幅（收紧不越过 0.95）"""
        meta = MetaCognition()
        meta._level_thresholds["high"] = 0.95
        for i in range(12):
            meta.record_decision(f"q{i}", "llm", 0.9)
            meta.record_outcome(f"q{i}", was_correct=False)
        meta.reflect()
        assert meta._level_thresholds["high"] == 0.95

    def test_stats_include_calibration(self):
        """get_stats 应暴露阈值与校准概览"""
        meta = MetaCognition()
        meta.record_decision("q1", "cache", 0.7)
        meta.record_outcome("q1", was_correct=True)
        stats = meta.get_stats()
        assert stats["level_thresholds"]["high"] == 0.85
        assert stats["calibration"]["medium"]["n"] == 1


class TestDecisionEngineWiring:
    def test_correction_feeds_meta_outcome(self, monkeypatch):
        """引擎的纠正入口应把 was_correct=False 喂给元认知"""
        from src.core import decision_engine as de
        de._meta_cognition = None
        # 全量套件下，更早的异步测试可能已把全局 InnerLoop 的事件循环关闭；
        # 重置单例让本用例走同步降级路径（本用例只关心 meta 接线）
        de._inner_loop = None
        meta = de._get_meta_cognition()
        meta.record_decision("把空调关了", "llm", 0.9)

        engine = de.DecisionEngine()
        engine.record_user_correction("把空调关了", "lock_open", "ac_off")

        record = next(r for r in meta._decision_history if r.query == "把空调关了")
        assert record.was_correct is False
        assert record.user_feedback == "correction"

    def test_feedback_feeds_meta_outcome(self, monkeypatch):
        """引擎的反馈入口应把 positive/negative 喂给元认知"""
        from src.core import decision_engine as de
        de._meta_cognition = None
        de._inner_loop = None  # 见 test_correction_feeds_meta_outcome 注释
        meta = de._get_meta_cognition()
        meta.record_decision("现在几点", "llm", 0.8)

        engine = de.DecisionEngine()
        engine.record_user_feedback("现在几点", "positive")
        engine.record_user_feedback("现在几点", "positive")  # 第二次无匹配记录，应为 no-op

        record = meta._decision_history[0]
        assert record.was_correct is True
        assert record.user_feedback == "positive"
