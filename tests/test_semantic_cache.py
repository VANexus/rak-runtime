"""语义缓存测试"""

import time
import pytest

from src.core.semantic_cache import SemanticCache


class TestSemanticCache:
    """语义缓存核心功能测试"""

    def test_exact_match(self):
        """精确匹配：相同输入应直接命中"""
        cache = SemanticCache()
        actions = ["nod", "shake_head"]
        cache.store("打开灯", {"action": "light_on"}, actions)

        result = cache.lookup("打开灯", actions)
        assert result is not None
        assert result["action"] == "light_on"

    def test_miss(self):
        """未命中：完全不同的输入"""
        cache = SemanticCache()
        actions = ["nod", "shake_head"]
        cache.store("打开灯", {"action": "light_on"}, actions)

        result = cache.lookup("关门", actions)
        assert result is None

    def test_lru_eviction(self):
        """LRU 淘汰：超过最大条目数后淘汰最旧的"""
        cache = SemanticCache(max_entries=5, similarity_threshold=0.99)
        actions = ["nod"]

        # 存入足够多条目，确保精确缓存和语义缓存都溢出
        for i in range(25):
            cache.store(f"query-{i}-unique-suffix", {"action": "nod", "index": i}, actions)

        stats = cache.stats()
        # 精确缓存应被限制在 max_entries 以内
        assert stats["exact_cache_size"] <= 5

    def test_ttl_expiry(self):
        """TTL 过期：超过生存时间的条目应返回 None"""
        cache = SemanticCache(ttl_seconds=1)
        actions = ["nod"]
        cache.store("test", {"action": "nod"}, actions)

        assert cache.lookup("test", actions) is not None

        time.sleep(1.1)
        assert cache.lookup("test", actions) is None

    def test_stats(self):
        """统计数据应包含必要字段"""
        cache = SemanticCache()
        cache.store("test", {"action": "nod"}, ["nod"])
        cache.lookup("test", ["nod"])
        stats = cache.stats()
        assert "total_lookups" in stats
        assert "exact_hits" in stats
        assert "exact_cache_size" in stats
        assert stats["total_lookups"] == 1
        assert stats["exact_hits"] == 1

    def test_store_and_lookup_different_actions(self):
        """不同 available_actions 应独立缓存"""
        cache = SemanticCache()
        cache.store("test", {"action": "nod"}, ["nod"])
        cache.store("test", {"action": "wave"}, ["wave"])

        result = cache.lookup("test", ["nod"])
        assert result["action"] == "nod"

        result = cache.lookup("test", ["wave"])
        assert result["action"] == "wave"

    def test_result_is_copy(self):
        """lookup 返回的应是副本，修改不影响缓存"""
        cache = SemanticCache()
        cache.store("test", {"action": "nod"}, ["nod"])

        r1 = cache.lookup("test", ["nod"])
        r1["action"] = "modified"

        r2 = cache.lookup("test", ["nod"])
        assert r2["action"] == "nod"
