"""
元认知 — Agent 的自我意识层。

核心能力：
1. 置信度评估：对每个决策打分，不确定时主动询问而非硬答
2. 策略选择：根据任务类型选择最优处理路径
3. 自我反思：从成功/失败中学习，调整策略权重
4. 不确定性处理：区分"不知道"和"不确定"

设计哲学：
- 宁可说"我不确定"也不要给出错误的高置信度回答
- 置信度不是随机数，是有依据的评估
- 策略选择应该考虑用户画像（新手需要更多确认，专家可以跳过）
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rak.meta_cognition")


# ── 数据结构 ──────────────────────────────────────────────

class ConfidenceLevel:
    """置信度等级"""
    HIGH = "high"           # >0.85: 直接执行
    MEDIUM = "medium"       # 0.6-0.85: 执行但提示
    LOW = "low"             # 0.3-0.6: 建议确认
    UNCERTAIN = "uncertain" # <0.3: 主动询问


class Strategy:
    """处理策略"""
    RULE = "rule"             # 规则引擎（确定性任务）
    CACHE = "cache"           # 缓存命中（高频查询）
    LLM = "llm"              # LLM 深思（复杂推理）
    ASK_USER = "ask_user"     # 主动询问用户（不确定性高）
    HYBRID = "hybrid"         # LLM + 规则交叉验证


@dataclass
class ConfidenceAssessment:
    """置信度评估结果"""
    level: str                    # ConfidenceLevel
    score: float                  # 0.0-1.0
    factors: dict                 # 各因子得分
    reasoning: str                # 评估依据
    should_confirm: bool          # 是否需要用户确认
    confirmation_prompt: str = "" # 确认提示语


@dataclass
class StrategyDecision:
    """策略选择结果"""
    strategy: str                 # Strategy
    reasoning: str                # 选择依据
    estimated_latency_ms: int     # 预估延迟
    fallback: str = ""            # 失败时的降级策略


@dataclass
class DecisionRecord:
    """决策记录 — 用于反思学习"""
    timestamp: float
    query: str
    strategy_used: str
    confidence_score: float
    was_correct: Optional[bool] = None  # None=未知, True=正确, False=错误
    user_feedback: str = ""
    latency_ms: int = 0


# ── 核心类 ────────────────────────────────────────────────

class MetaCognition:
    """元认知引擎 — 让 Agent 知道自己知道什么，不知道什么"""

    def __init__(self):
        # 策略权重（从反思中学习）
        self._strategy_weights = {
            Strategy.RULE: 1.0,
            Strategy.CACHE: 1.0,
            Strategy.LLM: 1.0,
            Strategy.HYBRID: 1.0,
        }
        self._decision_history: list[DecisionRecord] = []
        self._max_history = 200

        # 置信度校准（从实际成功率反调）：
        # 按预测置信度分桶统计实际正确率，对后续预测做收缩校正；
        # 等级阈值可被反思（reflect）动态收紧/放松
        self._calibration: dict[str, dict] = {}   # bucket -> {n, correct, sum_predicted}
        self._level_thresholds = {"high": 0.85, "medium": 0.6, "low": 0.3}
        self._calibration_min_samples = 10        # 单桶生效所需最小样本
        self._calibration_shrink_k = 20           # 收缩强度（样本越少越趋近原值）
        self._calibration_ratio_min = 0.5         # 校正系数下限
        self._calibration_ratio_max = 1.5         # 校正系数上限

        # 统计
        self._stats = {
            "total_decisions": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
            "uncertain": 0,
            "confirmations_asked": 0,
            "strategy_usage": {},
        }

    # ── 置信度评估 ────────────────────────────────────────

    def evaluate_confidence(
        self,
        query: str,
        cache_hit: bool = False,
        cache_similarity: float = 0.0,
        cache_is_paraphrase: bool = False,
        memory_match_count: int = 0,
        memory_best_similarity: float = 0.0,
        llm_response: Optional[dict] = None,
        rule_match: bool = False,
        user_expertise: float = 0.5,
        has_correction_history: bool = False,
    ) -> ConfidenceAssessment:
        """
        综合评估决策的置信度。

        置信度由多个因子加权计算：
        - 缓存命中: 高权重（精确匹配最可靠）
        - 记忆匹配: 中权重（有历史参考）
        - LLM 一致性: 中权重（推理能力）
        - 规则匹配: 高权重（确定性）
        - 用户纠正历史: 负权重（之前犯过错）
        """
        factors = {}

        # 1. 缓存因子
        if cache_hit:
            if cache_similarity >= 0.98:
                factors["cache"] = 0.95  # 精确匹配
            elif cache_is_paraphrase or cache_similarity >= 0.92:
                # 改写命中（Dice 层已校验阈值+意图类别守卫）≈ 语义匹配的可靠度。
                # 快速通道只含 cache 因子（无 LLM/记忆/规则），0.40~0.56 的 Dice
                # 若不设高权会算出 ~0.18 低置信度 → 被元认知丢回 LLM，快通道失效。
                factors["cache"] = 0.85
            else:
                factors["cache"] = 0.60
        else:
            factors["cache"] = 0.0

        # 2. 记忆因子
        if memory_match_count > 0:
            factors["memory"] = min(0.9, 0.3 + memory_best_similarity * 0.6)
        else:
            factors["memory"] = 0.0

        # 3. LLM 因子
        if llm_response:
            # LLM 返回了有效结果
            llm_score = 0.7
            # 如果 LLM 动作在 available_actions 内，加分
            if llm_response.get("action") and llm_response.get("action") != "idle":
                llm_score += 0.1
            # 如果 LLM 给出了清晰的推理，加分
            if llm_response.get("reasoning") and len(llm_response["reasoning"]) > 10:
                llm_score += 0.1
            factors["llm"] = min(1.0, llm_score)
        else:
            factors["llm"] = 0.0

        # 4. 规则因子
        if rule_match:
            factors["rule"] = 0.90
        else:
            factors["rule"] = 0.0

        # 5. 纠正历史因子（负权重）
        correction_penalty = 0.3 if has_correction_history else 0.0

        # 6. 用户专业水平调节
        # 专家用户 → 置信度可以稍低也执行（他们能看懂结果）
        # 新手用户 → 需要更高置信度才执行（避免误导）
        expertise_factor = 0.8 + user_expertise * 0.4  # 0.8-1.2

        # 加权计算（LLM 因子权重最高——它是推理的核心）
        weights = {
            "cache": 0.30,
            "memory": 0.15,
            "llm": 0.40,
            "rule": 0.15,
        }

        weighted_sum = sum(
            factors.get(k, 0) * v for k, v in weights.items()
        )

        # 缓存精确命中时，置信度直接取缓存因子（不被其他空因子拉低）
        if cache_hit and factors.get("cache", 0) >= 0.8:
            weighted_sum = max(weighted_sum, factors["cache"])

        # LLM 兜底：当 LLM 返回了高置信度结果（有效动作 + 推理），
        # 即使其他因子为 0，也不应低于 MEDIUM
        llm_factor = factors.get("llm", 0)
        if llm_factor >= 0.8:
            weighted_sum = max(weighted_sum, llm_factor * 0.7)

        # 最终分数
        score = weighted_sum * expertise_factor - correction_penalty
        score = max(0.0, min(1.0, score))

        # 置信度校准：按历史实际正确率收缩校正（无足够历史时为恒等）
        raw_score = score
        score = self._calibrated_score(score)

        # 确定等级（阈值可被反思反调）
        if score > self._level_thresholds["high"]:
            level = ConfidenceLevel.HIGH
        elif score > self._level_thresholds["medium"]:
            level = ConfidenceLevel.MEDIUM
        elif score > self._level_thresholds["low"]:
            level = ConfidenceLevel.LOW
        else:
            level = ConfidenceLevel.UNCERTAIN

        # 是否需要确认
        should_confirm = level in (ConfidenceLevel.LOW, ConfidenceLevel.UNCERTAIN)

        # 生成确认提示
        confirmation_prompt = ""
        if should_confirm:
            if level == ConfidenceLevel.UNCERTAIN:
                confirmation_prompt = "我不太确定你的意思，能再具体说一下吗？"
            else:
                confirmation_prompt = "我理解你想要执行这个操作，确认一下可以吗？"

        # 构建推理说明
        reasoning_parts = []
        if factors.get("cache", 0) > 0.5:
            reasoning_parts.append(f"缓存匹配（相似度 {cache_similarity:.2f}）")
        if factors.get("memory", 0) > 0.3:
            reasoning_parts.append(f"有 {memory_match_count} 条相关记忆")
        if factors.get("llm", 0) > 0.5:
            reasoning_parts.append("LLM 推理通过")
        if factors.get("rule", 0) > 0.5:
            reasoning_parts.append("规则引擎匹配")
        if has_correction_history:
            reasoning_parts.append("⚠️ 有纠正历史（已降低置信度）")
        if abs(score - raw_score) > 0.02:
            reasoning_parts.append(f"校准 {raw_score:.2f}→{score:.2f}")

        reasoning = "置信度评估: " + "; ".join(reasoning_parts) if reasoning_parts else "无直接证据"

        # 统计
        self._stats["total_decisions"] += 1
        self._stats[f"{level}_confidence"] = self._stats.get(f"{level}_confidence", 0) + 1
        if should_confirm:
            self._stats["confirmations_asked"] += 1

        return ConfidenceAssessment(
            level=level,
            score=round(score, 3),
            factors=factors,
            reasoning=reasoning,
            should_confirm=should_confirm,
            confirmation_prompt=confirmation_prompt,
        )

    # ── 策略选择 ──────────────────────────────────────────

    def select_strategy(
        self,
        query: str,
        confidence: ConfidenceAssessment,
        cache_hit: bool = False,
        available_actions: Optional[list] = None,
        user_expertise: float = 0.5,
    ) -> StrategyDecision:
        """
        选择最优处理策略。

        决策逻辑：
        1. 置信度高 + 缓存命中 → 直接用缓存
        2. 置信度高 + 规则匹配 → 规则引擎
        3. 置信度中 + 有 LLM → LLM 深思
        4. 置信度低 → 主动询问用户
        5. 复杂查询 → LLM + 规则交叉验证
        """
        # 简单确定性任务 → 规则
        simple_keywords = ["开", "关", "打开", "关闭", "锁", "解锁",
                          "on", "off", "open", "close", "lock", "unlock"]
        is_simple = any(kw in query for kw in simple_keywords) and len(query) < 15

        if confidence.level == ConfidenceLevel.HIGH and cache_hit:
            return StrategyDecision(
                strategy=Strategy.CACHE,
                reasoning="高置信度 + 缓存命中，直接返回缓存结果",
                estimated_latency_ms=1,
                fallback=Strategy.LLM,
            )

        if confidence.level == ConfidenceLevel.HIGH and is_simple:
            return StrategyDecision(
                strategy=Strategy.RULE,
                reasoning="高置信度 + 简单确定性任务，规则引擎处理",
                estimated_latency_ms=5,
                fallback=Strategy.LLM,
            )

        if confidence.level in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM):
            if confidence.score > 0.75:
                return StrategyDecision(
                    strategy=Strategy.LLM,
                    reasoning="中高置信度，LLM 深度推理",
                    estimated_latency_ms=1000,
                    fallback=Strategy.RULE,
                )
            else:
                return StrategyDecision(
                    strategy=Strategy.HYBRID,
                    reasoning="中置信度，LLM + 规则交叉验证",
                    estimated_latency_ms=1200,
                    fallback=Strategy.RULE,
                )

        # 低置信度或不确定
        # 简单动作指令即便低置信也不应被"询问"卡死：走规则引擎给 best-effort
        # 动作（规则兜底会返回动作或安全 idle），保住学习/改写缓存链。
        # 若规则都找不到匹配，则 ASK_USER 兜底仍保留询问安全网。
        if is_simple:
            return StrategyDecision(
                strategy=Strategy.RULE,
                reasoning="低置信度但有明确动作关键词，规则引擎 best-effort（避免无动作死路）",
                estimated_latency_ms=5,
                fallback=Strategy.ASK_USER,
            )

        # LLM 已返回有效结果 → 信任 LLM，不要反复确认
        if confidence.factors.get("llm", 0) >= 0.7:
            return StrategyDecision(
                strategy=Strategy.LLM,
                reasoning="LLM 已返回有效推理结果，信任 LLM 判断",
                estimated_latency_ms=1000,
                fallback=Strategy.RULE,
            )

        if user_expertise > 0.7:
            # 专家用户：给个 best guess 但标注不确定性
            return StrategyDecision(
                strategy=Strategy.LLM,
                reasoning="低置信度但用户是专家，LLM 尝试推理并标注不确定性",
                estimated_latency_ms=1000,
                fallback=Strategy.ASK_USER,
            )
        else:
            # 新手用户 + 无 LLM 结果：才询问
            return StrategyDecision(
                strategy=Strategy.ASK_USER,
                reasoning="低置信度 + 无 LLM 结果，主动询问以避免误导",
                estimated_latency_ms=0,
                fallback=Strategy.RULE,
            )

    # ── 记录与反思 ────────────────────────────────────────

    def record_decision(self, query: str, strategy: str,
                        confidence_score: float, latency_ms: int = 0):
        """记录一次决策，用于后续反思"""
        record = DecisionRecord(
            timestamp=time.time(),
            query=query,
            strategy_used=strategy,
            confidence_score=confidence_score,
            latency_ms=latency_ms,
        )
        self._decision_history.append(record)
        if len(self._decision_history) > self._max_history:
            self._decision_history = self._decision_history[-self._max_history:]

        # 统计
        self._stats["strategy_usage"][strategy] = \
            self._stats["strategy_usage"].get(strategy, 0) + 1

    def record_outcome(self, query: str, was_correct: bool, feedback: str = ""):
        """记录决策结果（用于反思学习与置信度校准）"""
        # 找到最近的匹配记录
        for record in reversed(self._decision_history):
            if record.query == query and record.was_correct is None:
                record.was_correct = was_correct
                record.user_feedback = feedback
                # 喂校准桶：预测置信度 vs 实际结果
                stats = self._calibration.setdefault(
                    self._bucket_of(record.confidence_score),
                    {"n": 0, "correct": 0, "sum_predicted": 0.0},
                )
                stats["n"] += 1
                stats["sum_predicted"] += record.confidence_score
                if was_correct:
                    stats["correct"] += 1
                break

    @staticmethod
    def _bucket_of(score: float) -> str:
        """预测置信度分桶（与等级段对齐）"""
        if score > 0.85:
            return "high"
        if score > 0.6:
            return "medium"
        if score > 0.3:
            return "low"
        return "uncertain"

    def _calibrated_score(self, score: float) -> float:
        """按历史实际正确率校正预测置信度；样本不足时趋近原值"""
        stats = self._calibration.get(self._bucket_of(score))
        if not stats or stats["n"] < self._calibration_min_samples:
            return score

        success_rate = stats["correct"] / stats["n"]
        mean_predicted = stats["sum_predicted"] / stats["n"]
        if mean_predicted <= 0:
            return score

        # 校正系数 = 实际正确率 / 平均预测置信度，限幅防过度反应
        ratio = success_rate / mean_predicted
        ratio = max(self._calibration_ratio_min, min(self._calibration_ratio_max, ratio))

        # 收缩：样本越少越靠近 1.0（不激进）
        weight = stats["n"] / (stats["n"] + self._calibration_shrink_k)
        adjusted = score * (1.0 + weight * (ratio - 1.0))
        return max(0.01, min(0.99, adjusted))

    def reflect(self) -> dict:
        """
        自我反思 — 分析最近的决策，提取教训。

        返回反思结果，包含：
        - 各策略的成功率
        - 置信度校准是否准确
        - 需要调整的策略权重
        """
        if len(self._decision_history) < 10:
            return {"status": "insufficient_data", "message": "数据不足，需要至少 10 条记录"}

        # 按策略分组统计
        strategy_stats = {}
        for record in self._decision_history:
            strategy = record.strategy_used
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {"total": 0, "correct": 0, "unknown": 0}
            strategy_stats[strategy]["total"] += 1
            if record.was_correct is True:
                strategy_stats[strategy]["correct"] += 1
            elif record.was_correct is None:
                strategy_stats[strategy]["unknown"] += 1

        # 计算各策略成功率
        insights = []
        for strategy, stats in strategy_stats.items():
            known = stats["total"] - stats["unknown"]
            if known > 0:
                success_rate = stats["correct"] / known
                if success_rate < 0.7:
                    insights.append(f"策略 '{strategy}' 成功率较低 ({success_rate:.0%})，考虑降级")
                    # 降低该策略权重
                    self._strategy_weights[strategy] = max(0.5,
                        self._strategy_weights.get(strategy, 1.0) - 0.1)
                elif success_rate > 0.9:
                    self._strategy_weights[strategy] = min(1.5,
                        self._strategy_weights.get(strategy, 1.0) + 0.05)

        # 置信度校准检查 + 反调阈值
        high_conf = [r for r in self._decision_history
                     if r.confidence_score > 0.85 and r.was_correct is not None]
        if high_conf:
            high_accuracy = sum(1 for r in high_conf if r.was_correct) / len(high_conf)
            if high_accuracy < 0.85:
                insights.append(
                    f"高置信度决策的实际准确率只有 {high_accuracy:.0%}，"
                    "置信度评估过于乐观，需要收紧阈值"
                )
            # 反调 high 阈值：准确率持续偏低则收紧（上限 0.95），表现优异则适度放松（下限 0.80）
            if high_accuracy < 0.80 and self._level_thresholds["high"] < 0.95:
                self._level_thresholds["high"] = round(self._level_thresholds["high"] + 0.02, 2)
                insights.append(f"高置信阈值收紧至 {self._level_thresholds['high']}")
            elif high_accuracy >= 0.95 and self._level_thresholds["high"] > 0.80:
                self._level_thresholds["high"] = round(self._level_thresholds["high"] - 0.01, 2)
                insights.append(f"高置信阈值放松至 {self._level_thresholds['high']}")

        result = {
            "status": "ok",
            "total_decisions": len(self._decision_history),
            "strategy_stats": strategy_stats,
            "strategy_weights": dict(self._strategy_weights),
            "insights": insights,
        }

        logger.info("元认知反思完成: %d 条记录, %d 条洞察",
                     len(self._decision_history), len(insights))

        return result

    def get_stats(self) -> dict:
        """获取元认知统计"""
        calibration_summary = {}
        for bucket, stats in self._calibration.items():
            calibration_summary[bucket] = {
                "n": stats["n"],
                "success_rate": round(stats["correct"] / stats["n"], 3) if stats["n"] else None,
            }
        return {
            **self._stats,
            "strategy_weights": dict(self._strategy_weights),
            "level_thresholds": dict(self._level_thresholds),
            "calibration": calibration_summary,
            "history_size": len(self._decision_history),
        }

    def format_confidence_hint(self, assessment: ConfidenceAssessment) -> str:
        """生成用户可见的置信度提示"""
        if assessment.level == ConfidenceLevel.HIGH:
            return ""  # 高置信度不显示提示
        elif assessment.level == ConfidenceLevel.MEDIUM:
            return "（我对这个判断比较有把握）"
        elif assessment.level == ConfidenceLevel.LOW:
            return "（我不太确定，如果不对请告诉我）"
        else:
            return "（我不确定你的意思，能再具体说一下吗？）"
