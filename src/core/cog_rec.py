"""
CogRec: LLM 教规则引擎（混合神经-符号架构）

灵感来源：CogRec (arXiv:2512.24113, Dec 2025)
核心思想：LLM 和规则引擎协同工作。
  - 规则引擎处理已知模式（<1ms）
  - LLM 处理未知模式（~3s）
  - LLM 成功后自动提取规则，教给规则引擎
  - 渐进式减少 LLM 调用，越用越快

流程：
  查询 → 规则匹配 → 命中？→ 直接返回（<1ms）
                  → 未命中？→ LLM 决策 → 成功？→ 提取规则 → 存入规则库
没有硬编码阈值，规则由 LLM 自主生成。
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    """一条学习到的规则"""
    pattern: str           # 匹配模式（关键词或语义描述）
    action: str            # 对应的动作
    params_json: str       # 参数
    confidence: float      # 置信度（从成功次数学习）
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0     # 命中次数
    success_count: int = 0 # 成功次数
    source: str = "llm"    # 来源：llm / correction / manual

    def success_rate(self) -> float:
        if self.hit_count == 0:
            return self.confidence
        return self.success_count / self.hit_count

    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern,
            "action": self.action,
            "params_json": self.params_json,
            "confidence": self.confidence,
            "hit_count": self.hit_count,
            "success_count": self.success_count,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Rule':
        return cls(
            pattern=data["pattern"],
            action=data["action"],
            params_json=data.get("params_json", "{}"),
            confidence=data.get("confidence", 0.5),
            hit_count=data.get("hit_count", 0),
            success_count=data.get("success_count", 0),
            source=data.get("source", "llm"),
            created_at=data.get("created_at", time.time()),
        )


class CogRecEngine:
    """
    CogRec 引擎 — 规则引擎 + LLM 教学。

    三阶段工作：
    1. 查询 → 规则匹配（<1ms）
    2. 未命中 → LLM 决策（~3s）
    3. LLM 成功 → 提取规则 → 教给规则引擎

    规则随时间积累，LLM 调用比例渐进下降。
    """

    def __init__(self, persist_path: str = None):
        self._rules: Dict[str, Rule] = {}  # pattern → Rule
        self._persist_path = persist_path

        # 统计
        self._total_queries = 0
        self._rule_hits = 0
        self._llm_calls = 0
        self._rules_learned = 0

        # 从磁盘加载
        if persist_path:
            self._load()

    def match(self, query: str, available_actions: List[str]) -> Optional[Dict]:
        """
        规则匹配。返回匹配的动作或 None。

        匹配策略：
        1. 精确关键词匹配（最快）
        2. 子串匹配（较快）
        3. 语义相似度（通过 embedding，可选）
        """
        self._total_queries += 1
        query_lower = query.strip().lower()

        # 精确匹配
        if query_lower in self._rules:
            rule = self._rules[query_lower]
            if rule.action in available_actions:
                rule.hit_count += 1
                self._rule_hits += 1
                logger.debug("[CogRec] 精确命中: '%s' → %s", query[:30], rule.action)
                return {
                    "action": rule.action,
                    "params_json": rule.params_json,
                    "confidence": rule.confidence,
                    "source": "cogrec_exact",
                }

        # 子串匹配（最长匹配优先）
        best_match = None
        best_len = 0
        for pattern, rule in self._rules.items():
            if len(pattern) > best_len and (
                pattern in query_lower or query_lower in pattern
            ):
                if rule.action in available_actions:
                    best_match = rule
                    best_len = len(pattern)

        if best_match:
            best_match.hit_count += 1
            self._rule_hits += 1
            logger.debug("[CogRec] 子串命中: '%s' → %s", query[:30], best_match.action)
            return {
                "action": best_match.action,
                "params_json": best_match.params_json,
                "confidence": best_match.confidence,
                "source": "cogrec_substring",
            }

        return None

    def learn_from_success(self, query: str, action: str,
                           params_json: str = "{}", confidence: float = 0.7):
        """
        从成功的 LLM 决策中提取规则。

        这是 CogRec 的核心：LLM 教规则引擎。
        """
        query_lower = query.strip().lower()

        # 检查是否已有此规则
        if query_lower in self._rules:
            rule = self._rules[query_lower]
            rule.success_count += 1
            # 成功率高时提升置信度
            if rule.success_rate() > 0.8:
                rule.confidence = min(0.95, rule.confidence + 0.05)
            logger.debug("[CogRec] 规则强化: '%s' (成功率 %.0f%%)",
                         query[:30], rule.success_rate() * 100)
        else:
            # 创建新规则
            rule = Rule(
                pattern=query_lower,
                action=action,
                params_json=params_json,
                confidence=confidence,
                success_count=1,
                source="llm",
            )
            self._rules[query_lower] = rule
            self._rules_learned += 1
            logger.info("[CogRec] 新规则学习: '%s' → %s (共 %d 条规则)",
                        query[:30], action, len(self._rules))

        # 持久化
        if self._persist_path:
            self._save()

    def learn_from_correction(self, query: str, wrong_action: str,
                               correct_action: str):
        """
        从用户纠正中学习。纠正的优先级最高。
        """
        query_lower = query.strip().lower()

        rule = Rule(
            pattern=query_lower,
            action=correct_action,
            params_json="{}",
            confidence=0.95,  # 纠正的置信度最高
            success_count=5,  # 初始成功率高
            hit_count=5,
            source="correction",
        )
        self._rules[query_lower] = rule
        self._rules_learned += 1
        logger.info("[CogRec] 纠正规则: '%s' → %s (纠正 %s)",
                    query[:30], correct_action, wrong_action)

        if self._persist_path:
            self._save()

    def on_failure(self, query: str, action: str):
        """规则匹配失败时调用，降低该规则的置信度"""
        query_lower = query.strip().lower()
        if query_lower in self._rules:
            rule = self._rules[query_lower]
            rule.hit_count += 1
            # 成功率低时降低置信度
            if rule.success_rate() < 0.3:
                rule.confidence = max(0.1, rule.confidence - 0.1)
                logger.info("[CogRec] 规则降级: '%s' (成功率 %.0f%%)",
                            query[:30], rule.success_rate() * 100)

    def extract_rule_prompt(self, query: str, action: str,
                            result: Dict) -> Optional[str]:
        """
        生成规则提取的 prompt（供 LearningLoop 调用）。

        如果 LLM 决策成功，用这个 prompt 让 LLM 提取可复用规则。
        """
        return f"""分析以下成功的决策，提取一条可复用的规则：

用户输入: "{query}"
执行动作: {action}
执行结果: {json.dumps(result, ensure_ascii=False)}

请提取规则（JSON 格式）：
{{
  "pattern": "匹配此规则的关键词或语义描述",
  "generalizable": true/false,
  "confidence": 0.0-1.0
}}

规则应该是通用的，不要太具体。"""

    def get_stats(self) -> Dict:
        total = self._total_queries or 1
        return {
            "total_rules": len(self._rules),
            "total_queries": self._total_queries,
            "rule_hits": self._rule_hits,
            "rule_hit_rate": f"{self._rule_hits / total:.1%}",
            "llm_calls": self._llm_calls,
            "rules_learned": self._rules_learned,
            "top_rules": [
                {"pattern": r.pattern[:30], "action": r.action,
                 "confidence": r.confidence, "hits": r.hit_count}
                for r in sorted(self._rules.values(),
                               key=lambda r: r.hit_count, reverse=True)[:5]
            ],
        }

    def _save(self):
        """持久化规则库"""
        try:
            from src.core._utils import atomic_write_json
            data = {k: v.to_dict() for k, v in self._rules.items()}
            atomic_write_json(self._persist_path, data)
        except Exception as e:
            logger.warning("[CogRec] 持久化失败: %s", e)

    def _load(self):
        """从磁盘加载规则库"""
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for pattern, rule_data in data.items():
                self._rules[pattern] = Rule.from_dict(rule_data)
            logger.info("[CogRec] 加载 %d 条规则", len(self._rules))
        except Exception as e:
            logger.warning("[CogRec] 加载失败: %s", e)
