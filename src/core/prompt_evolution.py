"""
Prompt Evolution: 双流提示词进化

灵感来源：SCOPE (arXiv:2512.15374, Dec 2025)
核心思想：提示词不应该静态，而应该从执行轨迹中持续进化。

双流机制：
- 战术流（Tactical）：短期纠错，自动过期
  例："设备 X 离线，不要尝试控制它" — 设备恢复后自动失效
- 战略流（Strategic）：长期原则，永久保留
  例："始终在执行前验证设备状态" — 越用越强

不同更新和过期策略：
- 战术：成功 N 次后自动过期
- 战略：冲突时用新证据更新，不删除
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Guideline:
    """一条提示词指南"""
    content: str           # 指南内容
    stream: str            # "tactical" 或 "strategic"
    confidence: float      # 置信度
    source: str            # 来源：correction, reflection, observation
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0     # 被检索到的次数
    success_after: int = 0 # 注入后成功的次数
    ttl_hits: int = 10     # 战术流：成功 N 次后过期

    def is_expired(self) -> bool:
        """战术流是否过期"""
        if self.stream == "strategic":
            return False
        return self.success_after >= self.ttl_hits

    def to_dict(self) -> Dict:
        return {
            "content": self.content,
            "stream": self.stream,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at,
            "hit_count": self.hit_count,
            "success_after": self.success_after,
            "ttl_hits": self.ttl_hits,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Guideline':
        return cls(
            content=data["content"],
            stream=data["stream"],
            confidence=data.get("confidence", 0.5),
            source=data.get("source", "unknown"),
            created_at=data.get("created_at", time.time()),
            hit_count=data.get("hit_count", 0),
            success_after=data.get("success_after", 0),
            ttl_hits=data.get("ttl_hits", 10),
        )


class PromptEvolution:
    """
    提示词进化引擎。

    从执行轨迹中学习，自动进化提示词。
    战术流处理即时纠错，战略流积累长期原则。
    """

    def __init__(self, persist_path: str = None):
        self._guidelines: List[Guideline] = []
        self._persist_path = persist_path
        self._max_guidelines = 50

        # 统计
        self._total_injected = 0
        self._tactical_created = 0
        self._strategic_created = 0

        if persist_path:
            self._load()

    def add_tactical(self, content: str, confidence: float = 0.8,
                     source: str = "correction", ttl_hits: int = 10):
        """
        添加战术指南（短期纠错）。

        自动过期：成功 ttl_hits 次后失效。
        """
        guideline = Guideline(
            content=content,
            stream="tactical",
            confidence=confidence,
            source=source,
            ttl_hits=ttl_hits,
        )
        self._guidelines.append(guideline)
        self._tactical_created += 1
        logger.info("[PromptEvo] 战术指南: %s (TTL=%d)", content[:50], ttl_hits)
        self._cleanup()

    def add_strategic(self, content: str, confidence: float = 0.7,
                      source: str = "reflection"):
        """
        添加战略指南（长期原则）。

        永不自动过期。冲突时用新证据更新。
        """
        # 检查是否有冲突的旧指南
        for existing in self._guidelines:
            if existing.stream == "strategic" and self._conflicts(existing.content, content):
                # 更新而非重复添加
                if confidence > existing.confidence:
                    existing.content = content
                    existing.confidence = confidence
                    logger.info("[PromptEvo] 战略指南更新: %s", content[:50])
                return

        guideline = Guideline(
            content=content,
            stream="strategic",
            confidence=confidence,
            source=source,
        )
        self._guidelines.append(guideline)
        self._strategic_created += 1
        logger.info("[PromptEvo] 战略指南: %s", content[:50])
        self._cleanup()

    def get_relevant(self, query: str, max_items: int = 5) -> List[str]:
        """
        获取与查询相关的指南。

        注入到 PromptEngine 的 system prompt 中。
        """
        scored = []
        for g in self._guidelines:
            if g.is_expired():
                continue
            relevance = self._relevance(query, g.content)
            if relevance > 0.3:
                score = relevance * g.confidence
                scored.append((score, g))

        scored.sort(key=lambda x: x[0], reverse=True)
        relevant = scored[:max_items]

        for _, g in relevant:
            g.hit_count += 1

        self._total_injected += len(relevant)
        return [g.content for _, g in relevant]

    def on_success(self, query: str):
        """成功时调用，战术流计数+1"""
        for g in self._guidelines:
            if g.stream == "tactical" and self._relevance(query, g.content) > 0.5:
                g.success_after += 1

    def on_failure(self, query: str):
        """失败时调用，战术流重置计数"""
        for g in self._guidelines:
            if g.stream == "tactical" and self._relevance(query, g.content) > 0.5:
                g.success_after = 0

    def _relevance(self, query: str, guideline: str) -> float:
        """查询与指南的相关性"""
        q = query.lower()
        g = guideline.lower()

        # 子串匹配
        if q in g or g in q:
            return 1.0

        # 词级匹配
        q_words = set(q.split())
        g_words = set(g.split())
        word_overlap = 0.0
        if q_words and g_words:
            word_overlap = len(q_words & g_words) / len(q_words | g_words)

        # 字符级匹配（中文字符）
        q_chars = set(q.replace(" ", ""))
        g_chars = set(g.replace(" ", ""))
        char_overlap = 0.0
        if q_chars and g_chars:
            char_overlap = len(q_chars & g_chars) / len(q_chars | g_chars)

        # 词缀匹配：一个词包含另一个词的字符
        prefix_match = 0.0
        for qw in q_words:
            for gw in g_words:
                if qw in gw or gw in qw:
                    prefix_match = 0.6
                    break
            if prefix_match:
                break

        # 查询中的词出现在指南中（中文字符级 n-gram 匹配）
        keyword_match = 0.0
        # 2-gram 匹配
        for i in range(len(q) - 1):
            bigram = q[i:i+2]
            if bigram in g and len(bigram.strip()) == 2:
                keyword_match = 0.5
                break

        return min(1.0, max(word_overlap, char_overlap, prefix_match, keyword_match))

    def _conflicts(self, existing: str, new: str) -> bool:
        """检查两条指南是否冲突"""
        e = set(existing.lower().split())
        n = set(new.lower().split())
        overlap = len(e & n) / max(len(e | n), 1)
        return overlap > 0.5

    def _cleanup(self):
        """清理过期和低质量指南"""
        # 移除过期的战术流
        self._guidelines = [g for g in self._guidelines if not g.is_expired()]

        # 超限时移除低分指南
        if len(self._guidelines) > self._max_guidelines:
            self._guidelines.sort(
                key=lambda g: g.confidence * (1 + g.hit_count * 0.1),
                reverse=True,
            )
            self._guidelines = self._guidelines[:self._max_guidelines]

        if self._persist_path:
            self._save()

    def get_stats(self) -> Dict:
        tactical = [g for g in self._guidelines if g.stream == "tactical"]
        strategic = [g for g in self._guidelines if g.stream == "strategic"]
        return {
            "total_guidelines": len(self._guidelines),
            "tactical": len(tactical),
            "strategic": len(strategic),
            "total_injected": self._total_injected,
            "tactical_created": self._tactical_created,
            "strategic_created": self._strategic_created,
        }

    def _save(self):
        try:
            from src.core._utils import atomic_write_json
            data = [g.to_dict() for g in self._guidelines]
            atomic_write_json(self._persist_path, data)
        except Exception as e:
            logger.warning("[PromptEvo] 持久化失败: %s", e)

    def _load(self):
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            self._guidelines = [Guideline.from_dict(d) for d in data]
            logger.info("[PromptEvo] 加载 %d 条指南", len(self._guidelines))
        except Exception as e:
            logger.warning("[PromptEvo] 加载失败: %s", e)
