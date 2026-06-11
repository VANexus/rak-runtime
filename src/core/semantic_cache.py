"""
语义缓存（Semantic Cache）— 高频查询的快速通道

核心思想：对于重复出现的查询，不需要每次都调用 LLM。
  查询 → embedding → ANN 检索缓存 → 相似度 > 阈值 → 直接返回缓存结果

这是"基底神经节"的替代方案——不用训练本地模型，
而是用缓存实现 <1ms 的"反射弧"。

缓存策略：
  - 精确匹配：query hash → result（最快）
  - 语义匹配：embedding 相似度 > 0.92 → result（快）
  - 过期淘汰：LRU + TTL

类比：
  - 人类的"肌肉记忆"——重复动作不需要思考
  - CPU 的 L1 缓存——热点数据就近返回
"""

import hashlib
import json
import logging
import os
import time
from typing import List, Dict, Optional, Tuple
from collections import OrderedDict

logger = logging.getLogger(__name__)


def _simple_embed(text: str, dim: int = 128) -> List[float]:
    """
    简单文本向量化（无外部依赖）。

    使用字符级 n-gram + 哈希投影，与 go-kernel skillnet 的
    EmbeddingEngine 原理一致，确保跨项目向量空间兼容。
    """
    vec = [0.0] * dim

    # 字符级 bigram + trigram
    text_lower = text.lower().strip()
    tokens = []
    for i in range(len(text_lower) - 1):
        tokens.append(text_lower[i:i+2])
    for i in range(len(text_lower) - 2):
        tokens.append(text_lower[i:i+3])

    if not tokens:
        tokens = [text_lower]

    # 哈希投影
    for token in tokens:
        h = _fnv1a(token.encode('utf-8'))
        for j in range(3):
            idx = (h + j * 2654435761) % dim
            sign = 1.0 if ((h >> j) & 1) == 0 else -1.0
            vec[idx] += sign

    # L2 归一化
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]

    return vec


def _fnv1a(data: bytes) -> int:
    """FNV-1a 哈希"""
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """余弦相似度"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class CacheEntry:
    """缓存条目"""
    __slots__ = ['query', 'result', 'embedding', 'actions_hash',
                 'created_at', 'last_hit', 'hit_count']

    def __init__(self, query: str, result: dict, embedding: List[float],
                 actions_hash: str):
        self.query = query
        self.result = result
        self.embedding = embedding
        self.actions_hash = actions_hash
        self.created_at = time.time()
        self.last_hit = time.time()
        self.hit_count = 0


class SemanticCache:
    """
    语义缓存 — 高频查询的快速通道。

    三层查找：
    1. 精确匹配（hash）：<1ms
    2. 语义匹配（embedding）：~5ms
    3. 未命中 → 返回 None，走 LLM 路径
    """

    def __init__(self,
                 max_entries: int = 500,
                 similarity_threshold: float = 0.92,
                 ttl_seconds: float = 3600,
                 persist_path: str = None):
        self.max_entries = max_entries
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self.persist_path = persist_path

        # 精确匹配缓存：query_hash → CacheEntry
        self._exact_cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # 语义匹配缓存：[(embedding, CacheEntry), ...]
        self._semantic_cache: List[Tuple[List[float], CacheEntry]] = []

        # 统计
        self._total_lookups = 0
        self._exact_hits = 0
        self._semantic_hits = 0
        self._misses = 0

        # 从磁盘加载缓存
        if persist_path:
            self.load()

    def lookup(self, query: str, available_actions: List[str]) -> Optional[dict]:
        """
        查找缓存。

        Returns:
            缓存命中返回 dict（包含 action, params_json 等），未命中返回 None
        """
        self._total_lookups += 1
        actions_hash = self._hash_actions(available_actions)

        # 1. 精确匹配
        query_hash = self._hash_query(query)
        entry = self._exact_cache.get(query_hash)
        if entry and entry.actions_hash == actions_hash:
            if not self._is_expired(entry):
                entry.last_hit = time.time()
                entry.hit_count += 1
                self._exact_hits += 1
                # LRU：移到末尾
                self._exact_cache.move_to_end(query_hash)
                logger.debug("[SemanticCache] 精确命中: %s", query[:30])
                return entry.result.copy()
            else:
                # 过期，删除
                del self._exact_cache[query_hash]

        # 2. 语义匹配
        query_emb = _simple_embed(query)
        best_entry = None
        best_sim = 0.0

        for emb, entry in self._semantic_cache:
            if entry.actions_hash != actions_hash:
                continue
            if self._is_expired(entry):
                continue
            sim = _cosine_similarity(query_emb, emb)
            if sim > best_sim:
                best_sim = sim
                best_entry = entry

        if best_entry and best_sim >= self.similarity_threshold:
            best_entry.last_hit = time.time()
            best_entry.hit_count += 1
            self._semantic_hits += 1
            logger.info("[SemanticCache] 语义命中 (sim=%.3f): %s", best_sim, query[:30])
            return best_entry.result.copy()

        # 3. 未命中
        self._misses += 1
        return None

    def store(self, query: str, result: dict, available_actions: List[str]):
        """存储查询结果到缓存"""
        actions_hash = self._hash_actions(available_actions)
        query_hash = self._hash_query(query)
        embedding = _simple_embed(query)

        entry = CacheEntry(query, result, embedding, actions_hash)

        # 存入精确缓存
        self._exact_cache[query_hash] = entry
        self._exact_cache.move_to_end(query_hash)

        # 存入语义缓存
        self._semantic_cache.append((embedding, entry))

        # 淘汰
        self._evict()

        logger.debug("[SemanticCache] 缓存存储: %s → %s", query[:30], result.get('action', '?'))

    def _evict(self):
        """淘汰过期和超量条目"""
        now = time.time()

        # 淘汰过期的精确缓存
        expired = [k for k, v in self._exact_cache.items()
                   if now - v.created_at > self.ttl_seconds]
        for k in expired:
            del self._exact_cache[k]

        # LRU 淘汰超量
        while len(self._exact_cache) > self.max_entries:
            self._exact_cache.popitem(last=False)

        # 清理过期的语义缓存
        self._semantic_cache = [
            (emb, entry) for emb, entry in self._semantic_cache
            if not self._is_expired(entry)
        ]

        # 限制语义缓存大小
        if len(self._semantic_cache) > self.max_entries * 2:
            self._semantic_cache = self._semantic_cache[-self.max_entries:]

    def _is_expired(self, entry: CacheEntry) -> bool:
        return time.time() - entry.created_at > self.ttl_seconds

    def _hash_query(self, query: str) -> str:
        return hashlib.md5(query.strip().lower().encode()).hexdigest()

    def _hash_actions(self, actions: List[str]) -> str:
        return hashlib.md5("|".join(sorted(actions)).encode()).hexdigest()

    def stats(self) -> Dict:
        total = self._total_lookups or 1
        return {
            "total_lookups": self._total_lookups,
            "exact_hits": self._exact_hits,
            "semantic_hits": self._semantic_hits,
            "misses": self._misses,
            "hit_rate": f"{(self._exact_hits + self._semantic_hits) / total:.1%}",
            "exact_cache_size": len(self._exact_cache),
            "semantic_cache_size": len(self._semantic_cache),
        }

    def save(self):
        """将缓存保存到磁盘"""
        if not self.persist_path:
            return
        try:
            entries = []
            for entry in self._exact_cache.values():
                entries.append({
                    "query": entry.query,
                    "result": entry.result,
                    "embedding": entry.embedding,
                    "actions_hash": entry.actions_hash,
                    "created_at": entry.created_at,
                    "hit_count": entry.hit_count,
                })
            os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
            from src.core._utils import atomic_write_json
            atomic_write_json(self.persist_path, entries)
            logger.info("[SemanticCache] 缓存已保存: %d 条", len(entries))
        except Exception as e:
            logger.warning("[SemanticCache] 缓存保存失败: %s", e)

    def load(self):
        """从磁盘加载缓存"""
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path) as f:
                entries = json.load(f)
            loaded = 0
            for data in entries:
                entry = CacheEntry(
                    query=data["query"],
                    result=data["result"],
                    embedding=data.get("embedding", []),
                    actions_hash=data.get("actions_hash", ""),
                )
                entry.created_at = data.get("created_at", time.time())
                entry.hit_count = data.get("hit_count", 0)
                query_hash = self._hash_query(entry.query)
                self._exact_cache[query_hash] = entry
                if entry.embedding:
                    self._semantic_cache.append((entry.embedding, entry))
                loaded += 1
            logger.info("[SemanticCache] 从磁盘加载 %d 条缓存", loaded)
        except Exception as e:
            logger.warning("[SemanticCache] 缓存加载失败: %s", e)
