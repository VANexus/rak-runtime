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
            elif cache_similarity >= 0.92:
                factors["cache"] = 0.80  # 语义匹配
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

        # 确定等级
        if score > 0.85:
            level = ConfidenceLevel.HIGH
        elif score > 0.6:
            level = ConfidenceLevel.MEDIUM
        elif score > 0.3:
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
        """记录决策结果（用于反思学习）"""
        # 找到最近的匹配记录
        for record in reversed(self._decision_history):
            if record.query == query and record.was_correct is None:
                record.was_correct = was_correct
                record.user_feedback = feedback
                break

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

        # 置信度校准检查
        high_conf = [r for r in self._decision_history
                     if r.confidence_score > 0.85 and r.was_correct is not None]
        if high_conf:
            high_accuracy = sum(1 for r in high_conf if r.was_correct) / len(high_conf)
            if high_accuracy < 0.85:
                insights.append(
                    f"高置信度决策的实际准确率只有 {high_accuracy:.0%}，"
                    "置信度评估过于乐观，需要收紧阈值"
                )

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
        return {
            **self._stats,
            "strategy_weights": dict(self._strategy_weights),
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
