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


def _char_ngrams(text: str, n: int) -> set:
    """字符级 n-gram 集合（用于无依赖的语义重叠计算）。

    中文短指令的语义匹配：哈希投影向量的余弦相似度对同义改写
    （如「帮我把客厅的灯打开」↔「把屋里的灯开一下」）几乎不敏感
    （实测余弦 0.079），无法命中语义缓存。这里用字符 n-gram 的
    Dice 重叠度做改写识别层，互补余弦层。
    """
    t = text.lower().strip()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def _dice_overlap(a: str, b: str, n: int = 1) -> float:
    """字符 n-gram Dice 系数（Sørensen–Dice），无外部依赖。

    对中文同义改写更敏感：字符单字（n=1）级 Dice 能捕捉
    「灯/开/关/走/转」等共现汉字。空串按词典返回 0（不相同）或 1。
    """
    if not a and not b:
        return 1.0
    A = _char_ngrams(a, n)
    B = _char_ngrams(b, n)
    if not A and not B:
        return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
    if not A or not B:
        return 0.0
    return 2.0 * len(A & B) / (len(A) + len(B))


# 动作 → 意图类别关键词。用于守卫语义命中：若改写命中的缓存动作与
# 查询语义类别相冲突（如查询「帮我修一下车」却命中 light_on），则不返回，
# 避免「宽泛词面重叠 + 低阈值」带来的明显误命中。
_ACTION_INTENT_KEYWORDS = {
    "light_on": ("灯", "开灯", "照明", "亮", "点亮"),
    "light_off": ("灯", "关灯", "灭", "暗", "闭上"),
    "lock_open": ("开门", "门打开", "打开门", "门开", "开一下"),
    "lock_close": ("锁门", "锁上", "关门", "门关", "关死", "关掉"),
    "move_forward": ("走", "前", "进", "挪", "迈", "前进"),
    "move_back": ("退", "后", "回", "后退"),
    # 注意：不要含裸"转"——"转"无法区分左右，会让 turn_left 遮蔽 turn_right。
    # 判别靠方向字（左/右）与显式方向词。
    "turn_left": ("左", "往左", "向左"),
    "turn_right": ("右", "往右", "向右"),
    "nod": ("点头", "点"),
    "shake_head": ("摇头", "摇"),
    "wave_hand": ("招手", "挥手", "招呼"),
    "dance": ("舞", "跳", "蹦"),
}

# 方向/开关对立标记：若查询与缓存分别在两侧，必为相反动作。
# 对任何字符重叠匹配（Dice 亦是）这是最高信息量的判别信号。用「开/关」
# 单字时要避免误伤（如「开关」一词本身），故仅对成对出现做判别：
# 一方含 A 且另一方含 B（互为反义）才判为对立。
_ANTONYM_MARKERS = (
    ("开", "关"),
    ("左", "右"),
    ("前", "后"),
    ("进", "退"),
    ("上", "下"),
)


def _intent_category(query: str) -> Optional[str]:
    """粗略推断查询的意图类别（基于关键词，供守卫用）。"""
    q = query.lower().strip()
    for action, kws in _ACTION_INTENT_KEYWORDS.items():
        if any(kw in q for kw in kws):
            return action
    return None


def _has_antonym_conflict(a: str, b: str) -> bool:
    """a、b 是否落在某一对方向/开关反义标记的两端（如 a 含"开"、b 含"关"）。"""
    al = a.lower()
    bl = b.lower()
    for x, y in _ANTONYM_MARKERS:
        if (x in al and y in bl) or (y in al and x in bl):
            return True
    return False


def _action_plausible(query: str, cached_query: str) -> bool:
    """判断改写命中的缓存动作对当前查询是否『合理』。

    规则：
    1. 反义标记（开↔关、左↔右、前↔后、进↔退…）冲突 → 拒绝。这是最强的
       对立判别，独立于类别关键词。
    2. 两者类别关键词都命中且一致 → 合理。
    3. 有一方无法归类 → 不因"无法归类"而拒绝：真正的同义改写常只有一侧含
       关键词（如「招个手问个好」无"招手"子串）。相似度交由 Dice 阈值把关；
       反义情况已由第 1 条拦截，不再依赖类别回退。
    """
    if _has_antonym_conflict(query, cached_query):
        return False
    q_cat = _intent_category(query)
    c_cat = _intent_category(cached_query)
    if q_cat is not None and c_cat is not None:
        return q_cat == c_cat
    return True




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

    多层查找：
    1. 精确匹配（hash）：<1ms
    2. 语义匹配（embedding 余弦，near-verbatim）：~5ms
    3. 改写匹配（字符 n-gram Dice，中文同义改写层）
    4. 未命中 → 返回 None，走 LLM 路径
    """

    def __init__(self,
                 max_entries: int = 500,
                 similarity_threshold: float = 0.97,
                 para_similarity_threshold: float = 0.40,
                 ttl_seconds: float = 3600,
                 persist_path: str = None):
        self.max_entries = max_entries
        self.similarity_threshold = similarity_threshold
        # 改写层（字符 n-gram Dice）阈值。实测：同义改写对「帮我把客厅的灯打开」
        # ↔「把屋里的灯开一下」≈0.47、「我要睡了把灯关掉」↔「睡觉了灯灭了吧」≈0.43，
        # 无关查询（如「帮我修一下车」vs light_on 缓存）≈0.27。取 0.40 切线。
        self.para_similarity_threshold = para_similarity_threshold
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
        self._para_hits = 0
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

        # 2. 语义匹配（embedding 余弦，近逐字变体）
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
            result = best_entry.result.copy()
            result["_similarity"] = best_sim  # 注入真实相似度，供元认知评估
            return result

        # 2b. 改写匹配（字符 n-gram Dice，中文同义改写层）
        best_entry = None
        best_para = 0.0
        for emb, entry in self._semantic_cache:
            if entry.actions_hash != actions_hash:
                continue
            if self._is_expired(entry):
                continue
            # 守卫：改写命中的动作类别须与查询合理（防「修车」命中 light_on）
            if not _action_plausible(query, entry.query):
                continue
            para = _dice_overlap(query, entry.query)
            if para > best_para:
                best_para = para
                best_entry = entry

        if best_entry and best_para >= self.para_similarity_threshold:
            best_entry.last_hit = time.time()
            best_entry.hit_count += 1
            self._para_hits += 1
            logger.info("[SemanticCache] 改写命中 (dice=%.3f): %s → %s",
                        best_para, query[:30], best_entry.query[:30])
            result = best_entry.result.copy()
            result["_similarity"] = best_para          # 真实相似度，供元认知评估
            result["_para_similarity"] = best_para     # 改写层相似度标识
            return result

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
            "para_hits": self._para_hits,
            "misses": self._misses,
            "hit_rate": f"{(self._exact_hits + self._semantic_hits + self._para_hits) / total:.1%}",
            "exact_cache_size": len(self._exact_cache),
            "semantic_cache_size": len(self._semantic_cache),
        }

    def save(self):
        """将缓存保存到磁盘。

        同时持久化精确缓存与语义缓存的并集：存储时两者共享 CacheEntry，
        但语义缓存可能保留被 LRU 逐出的条目，若只序列化 _exact_cache 会丢失
        这部分改写层条目。以 query_hash 为键去重后统一写盘。
        """
        if not self.persist_path:
            return
        try:
            # 并集：精确 + 语义，按 query_hash 去重（同一条目可能同时挂在两个缓存）
            by_hash: Dict[str, CacheEntry] = {}
            for entry in self._exact_cache.values():
                by_hash[self._hash_query(entry.query)] = entry
            for _emb, entry in self._semantic_cache:
                by_hash.setdefault(self._hash_query(entry.query), entry)

            entries = []
            for entry in by_hash.values():
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
            payload = {
                "version": 2,          # v2：明确同时持久化精确 + 语义两层
                "entries": entries,
            }
            atomic_write_json(self.persist_path, payload)
            logger.info("[SemanticCache] 缓存已保存: %d 条", len(entries))
        except Exception as e:
            logger.warning("[SemanticCache] 缓存保存失败: %s", e)

    def load(self):
        """从磁盘加载缓存。

        兼容两种格式：
        - v2（当前）：{"version": 2, "entries": [...]}
        - 旧版平铺列表 [entry, ...]（仅精确缓存）
        每条都同时恢复到精确缓存与语义缓存（若有 embedding）。
        """
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path) as f:
                data = json.load(f)
            if isinstance(data, dict) and "entries" in data:
                entries = data["entries"]
            elif isinstance(data, list):
                entries = data
            else:
                logger.warning("[SemanticCache] 缓存文件格式未知，跳过加载")
                return
            loaded = 0
            seen = set()
            for item in entries:
                query = item.get("query")
                if not query:
                    continue
                qh = self._hash_query(query)
                if qh in seen:              # 并集去重
                    continue
                seen.add(qh)
                entry = CacheEntry(
                    query=query,
                    result=item.get("result", {}),
                    embedding=item.get("embedding", []),
                    actions_hash=item.get("actions_hash", ""),
                )
                entry.created_at = item.get("created_at", time.time())
                entry.hit_count = item.get("hit_count", 0)
                self._exact_cache[qh] = entry
                if entry.embedding:
                    self._semantic_cache.append((entry.embedding, entry))
                loaded += 1
            logger.info("[SemanticCache] 从磁盘加载 %d 条缓存", loaded)
        except Exception as e:
            logger.warning("[SemanticCache] 缓存加载失败: %s", e)
