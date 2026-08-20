"""语义缓存测试"""

import os
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

    # ---- 改写层（字符 n-gram Dice）----

    def test_paraphrase_hit_light_on(self):
        """同义改写应命中语义缓存（未能精确/embedding 命中时走改写层）"""
        cache = SemanticCache()
        actions = ["light_on", "light_off", "idle"]
        cache.store("帮我把客厅的灯打开", {"action": "light_on"}, actions)

        result = cache.lookup("把屋里的灯开一下", actions)
        assert result is not None
        assert result["action"] == "light_on"
        # 改写层注入真实相似度
        assert result.get("_para_similarity", 0.0) >= cache.para_similarity_threshold

    def test_paraphrase_hit_light_off(self):
        """同义改写应命中语义缓存（关灯）"""
        cache = SemanticCache()
        actions = ["light_on", "light_off", "idle"]
        cache.store("我要睡了把灯关掉", {"action": "light_off"}, actions)

        result = cache.lookup("睡觉了灯灭了吧", actions)
        assert result is not None
        assert result["action"] == "light_off"

    def test_paraphrase_unrelated_miss(self):
        """无关查询不应命中改写层（词面部分重叠但意图类别冲突）"""
        cache = SemanticCache()
        actions = ["light_on", "light_off", "idle"]
        cache.store("帮我把客厅的灯打开", {"action": "light_on"}, actions)

        result = cache.lookup("帮我修一下车", actions)
        assert result is None

    def test_paraphrase_antonym_no_false_hit(self):
        """反义动作（开↔关）不得经改写层误命中——即便字符重叠高。

        回归：live baseline cold-4 曾把「把门关死」(lock_close) 误判为缓存中的
        「把门开开」(lock_open)（dice 0.47 > 阈值）。反义标记守卫必须拦截。
        """
        cache = SemanticCache()
        actions = ["lock_open", "lock_close", "idle"]
        cache.store("让我进屋，把门开开", {"action": "lock_open"}, actions)

        assert cache.lookup("我要走了，把门关死", actions) is None
        assert cache.lookup("往左边转一下", actions) is None   # 不同域也不串

    def test_paraphrase_turn_right_hit(self):
        """「右」向改写应命中 turn_right（回归：裸"转"字曾让 turn_left 遮蔽 turn_right）。"""
        cache = SemanticCache()
        actions = ["turn_left", "turn_right", "idle"]
        cache.store("向右转一下", {"action": "turn_right"}, actions)

        result = cache.lookup("往右偏一点", actions)
        assert result is not None
        assert result["action"] == "turn_right"

    def test_paraphrase_antonym_turn_pair_blocked(self):
        """左右反义：缓存 turn_left，查询 turn_right 应被拦截。"""
        cache = SemanticCache()
        actions = ["turn_left", "turn_right", "idle"]
        cache.store("往左边转一下", {"action": "turn_left"}, actions)

        assert cache.lookup("往右偏一点", actions) is None


        # 完全无关的「关门」也不应命中
        assert cache.lookup("关门", actions) is None

    def test_paraphrase_injects_similarity(self):
        """改写层命中应注入 _similarity 与 _para_similarity"""
        cache = SemanticCache()
        actions = ["light_on", "idle"]
        cache.store("帮我把客厅的灯打开", {"action": "light_on"}, actions)

        result = cache.lookup("把屋里的灯开一下", actions)
        assert "_similarity" in result
        assert "_para_similarity" in result

    # ---- 持久化：精确 + 语义双层 round-trip ----

    def test_save_load_roundtrip_both_caches(self, tmp_path):
        """save/load 应同时恢复精确与语义缓存，且改写命中在重载后仍有效"""
        persist = str(tmp_path / "semantic_cache.json")
        cache = SemanticCache(persist_path=persist)
        actions = ["light_on", "light_off", "idle"]
        cache.store("帮我把客厅的灯打开", {"action": "light_on"}, actions)
        cache.store("我要睡了把灯关掉", {"action": "light_off"}, actions)

        # 语义缓存必须非空才谈得上持久化
        assert cache.stats()["semantic_cache_size"] == 2
        cache.save()
        assert os.path.exists(persist)

        # 重新加载
        loaded = SemanticCache(persist_path=persist)
        assert loaded.stats()["semantic_cache_size"] == 2
        assert loaded.stats()["exact_cache_size"] == 2

        # 精确命中仍有效
        assert loaded.lookup("帮我把客厅的灯打开", actions)["action"] == "light_on"
        # 改写命中在重载后仍有效
        assert loaded.lookup("把屋里的灯开一下", actions)["action"] == "light_on"
        assert loaded.lookup("睡觉了灯灭了吧", actions)["action"] == "light_off"
        # 无关查询依旧不命中
        assert loaded.lookup("帮我修一下车", actions) is None

    def test_save_load_backward_compat(self, tmp_path):
        """旧版平铺列表格式应仍能加载（向后兼容）"""
        import json
        # 用真实 actions_hash（与当前 available_actions 一致），
        # 且旧格式没有 embedding，恢复后只进精确缓存。
        probe = SemanticCache()
        actions = ["light_on", "idle"]
        actions_hash = probe._hash_actions(actions)
        persist = str(tmp_path / "semantic_cache.json")
        old_payload = [{
            "query": "帮我把客厅的灯打开",
            "result": {"action": "light_on"},
            "embedding": [],
            "actions_hash": actions_hash,
            "created_at": time.time(),
            "hit_count": 1,
        }]
        with open(persist, "w", encoding="utf-8") as f:
            json.dump(old_payload, f)

        loaded = SemanticCache(persist_path=persist)
        # 旧格式至少恢复精确缓存
        result = loaded.lookup("帮我把客厅的灯打开", actions)
        assert result is not None
        assert result["action"] == "light_on"

    def test_verbatim_exact_still_hits(self):
        """逐字重复应始终走精确层命中"""
        cache = SemanticCache()
        actions = ["light_on", "idle"]
        cache.store("帮我把客厅的灯打开", {"action": "light_on"}, actions)

        result = cache.lookup("帮我把客厅的灯打开", actions)
        assert result is not None
        assert result["action"] == "light_on"
