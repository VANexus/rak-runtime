"""
超长期记忆（Super Long-Term Memory）— 大脑的终身记忆磁盘层。

现有三层记忆（CognitiveMemoryEngine）是进程内存层，salience 随时间衰减；
活体图谱（LivingGraph）是联想图谱。本模块是面向"超长期/跨会话"的持久记忆层，
补齐四个生产级缺口：

1. 幂等写入 —— sha256(content + scope) 作唯一键，同内容不重复落盘（G27）
2. 全文检索 —— SQLite FTS5 中文友好的全文索引，关键字精确召回（G27）
3. 渐进披露 —— recall 先返回紧凑索引（id/类型/时间/重要性/片段），
   recall_full 才取全文 —— 只注入高信号 token（G8）
4. scope 隔离 —— 多用户/多设备记忆不串（G11）
5. 记忆间图链接 —— 相似/关联记忆建边，图扩散召回替代纯向量 TopK（G10）

与 CognitiveMemoryEngine / LivingGraph 的关系：
- CognitiveMemoryEngine：进程内工作/短期/长期，本模块是其"磁盘归档层"的升级
- LivingGraph：概念联想图谱；本模块负责"记忆↔记忆"的篇章级关联 + 持久化
- 三者可同时接线：决策引擎从三层记忆 + 活体图谱 + 超长期记忆各取一路

设计借鉴：claude-mem（预算化注入 + content-hash 幂等 + FTS5）、
hermes（curator 归档不删）、EverMemOS（终身记忆）。
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


# ========== 数据结构 ==========

@dataclass
class MemoryHit:
    """一次召回结果（紧凑索引，渐进披露 L1）"""
    id: str
    content: str            # 片段（FTS snippet 或前 N 字）
    memory_type: str
    scope: str
    importance: float
    created_at: float
    last_accessed: float
    access_count: int
    score: float            # 相关度
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ========== 超长期记忆引擎 ==========

class SuperMemory:
    """
    超长期记忆 — 幂等 + FTS5 + 渐进披露 + scope 隔离 + 记忆图链接。

    存储：单个 SQLite 文件
      - memories        记忆主表（sha 唯一 → 幂等）
      - memories_fts    FTS5 全文索引（外内容表，触发器同步）
      - memory_links    记忆↔记忆关联边（图扩散召回）
    """

    def __init__(self, db_path: str = None, embed_fn=None):
        if db_path is None:
            # 尊重 RAK_DATA_DIR（_data_dir），与 decision_engine 其它单例隔离一致；
            # 导入失败回退旧硬编码路径（向后兼容）。
            try:
                from src.core.decision_engine import _data_dir
                db_path = os.path.join(_data_dir(), "memory", "super_long.db")
            except Exception:
                db_path = os.path.join(
                    os.path.dirname(__file__), "..", "..", "data", "memory", "super_long.db"
                )
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

        # 默认用轻量字符级 embedding（复用语义缓存，无外部依赖）
        if embed_fn is None:
            try:
                from src.core.semantic_cache import _simple_embed
                embed_fn = _simple_embed
            except ImportError:
                embed_fn = None
        self.embed_fn = embed_fn

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

        self._stats = {
            "total_writes": 0,
            "deduped_writes": 0,
            "total_recalls": 0,
            "total_links": 0,
            "consolidations": 0,
        }

    # ── Schema ──────────────────────────────────────────────

    def _init_schema(self):
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                sha TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'default',
                importance REAL DEFAULT 0.5,
                metadata TEXT DEFAULT '{}',
                created_at REAL,
                last_accessed REAL,
                access_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_mem_scope_type ON memories(scope, memory_type);
            CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance DESC);

            -- FTS5 外内容表（trigram 分词 → 中文子串匹配）
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content, content='memories', content_rowid='rowid',
                tokenize='trigram'
            );
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
                INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END;

            CREATE TABLE IF NOT EXISTS memory_links (
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation TEXT DEFAULT 'related',
                weight REAL DEFAULT 0.5,
                PRIMARY KEY(from_id, to_id)
            );
        """)
        self._conn.commit()

    # ── 写入（幂等） ────────────────────────────────────────

    def remember(self, content: str, memory_type: str = "episodic",
                 scope: str = "default", importance: float = 0.5,
                 metadata: Dict = None) -> str:
        """
        写入一条记忆。幂等：同 (content, scope) 已存在则只更新 importance/metadata，
        不产生重复条目。返回记忆 id。
        """
        if not content or not content.strip():
            return ""
        content = content.strip()
        sha = self._sha(content, scope)
        now = time.time()
        mid = f"mem_{int(now * 1000)}_{sha[:8]}"

        cur = self._conn.cursor()
        existing = cur.execute(
            "SELECT id FROM memories WHERE sha=?", (sha,)
        ).fetchone()

        if existing:
            # 幂等去重：只抬高 importance、合并 metadata、刷新时间
            self._stats["deduped_writes"] += 1
            old = cur.execute(
                "SELECT metadata FROM memories WHERE id=?",
                (existing["id"],),
            ).fetchone()
            merged = {}
            if old and old["metadata"]:
                try:
                    merged.update(json.loads(old["metadata"]))
                except (json.JSONDecodeError, TypeError):
                    pass
            if metadata:
                merged.update(metadata)
            cur.execute(
                "UPDATE memories SET importance=MAX(importance,?), metadata=?,"
                " last_accessed=? WHERE id=?",
                (importance, json.dumps(merged, ensure_ascii=False), now, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]

        cur.execute(
            "INSERT INTO memories (id, sha, content, memory_type, scope,"
            " importance, metadata, created_at, last_accessed, access_count)"
            " VALUES (?,?,?,?,?,?,?,?,?,0)",
            (mid, sha, content, memory_type, scope, importance,
             json.dumps(metadata or {}, ensure_ascii=False), now, now),
        )
        self._conn.commit()
        self._stats["total_writes"] += 1

        # 与近期记忆建立关联边（相似度 > 阈值）
        self._auto_link(mid, content, scope)

        return mid

    def _auto_link(self, mid: str, content: str, scope: str, threshold: float = 0.30):
        """与新记忆内容相关（中文 n-gram 相似）的历史记忆建边（篇章级图结构）"""
        recent = self._conn.execute(
            "SELECT id, content FROM memories WHERE id!=? AND scope=?"
            " ORDER BY created_at DESC LIMIT 60",
            (mid, scope),
        ).fetchall()
        for row in recent:
            sim = self._text_similarity(content, row["content"])
            if sim >= threshold:
                self.link(mid, row["id"], relation="similar", weight=round(sim, 3))

    # ── 召回（渐进披露 L1） ─────────────────────────────────

    def recall(self, query: str, scope: str = "default", top_k: int = 5,
               memory_types: Optional[List[str]] = None) -> List[MemoryHit]:
        """
        紧凑召回：返回索引级信息（id/类型/时间/重要性/片段 + 相关度）。
        渐进披露 L1 —— 只注入高信号 token，全文用 recall_full 按需取。
        """
        self._stats["total_recalls"] += 1
        if not query:
            return []

        candidates: Dict[str, float] = {}  # id → score
        terms = self._split_terms(query)

        # 通道 1: FTS5 trigram 全文匹配（每个 >=3 字符的词条）
        try:
            fts_q = self._fts_query(terms)
            if fts_q:
                fts_rows = self._conn.execute(
                    "SELECT m.id FROM memories_fts JOIN memories m"
                    " ON m.rowid = memories_fts.rowid"
                    " WHERE memories_fts MATCH ? AND m.scope=? LIMIT 30",
                    (fts_q, scope),
                ).fetchall()
                for r in fts_rows:
                    candidates[r["id"]] = candidates.get(r["id"], 0.0) + 1.5
        except sqlite3.OperationalError:
            pass  # FTS 查询语法异常时忽略，走通道 2

        # 通道 2: 逐词条 LIKE 子串匹配（中文主通道，空格不敏感）
        for term in terms:
            if not term:
                continue
            kw_rows = self._conn.execute(
                "SELECT id FROM memories WHERE scope=? AND content LIKE ?",
                (scope, f"%{term}%"),
            ).fetchall()
            for r in kw_rows:
                candidates[r["id"]] = candidates.get(r["id"], 0.0) + 1.0

        # 通道 3: 中文 bigram 扩展（无空格查询的近子串/短语变体召回，
        #         权重低于精确词条；对"22点锁门" vs "门锁在 22:00 自动锁定"这类变体有效）
        q_norm = re.sub(r"\s+", "", query)
        if len(q_norm) >= 2:
            bigrams = {q_norm[i:i + 2] for i in range(len(q_norm) - 1)}
            for bg in bigrams:
                if not bg.strip():
                    continue
                bg_rows = self._conn.execute(
                    "SELECT id FROM memories WHERE scope=? AND content LIKE ?",
                    (scope, f"%{bg}%"),
                ).fetchall()
                for r in bg_rows:
                    candidates[r["id"]] = candidates.get(r["id"], 0.0) + 0.4

        if not candidates:
            return []

        # 组装命中（importance + access 加权，与 salience 同理）
        hits = []
        for mid, base in candidates.items():
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id=?", (mid,)
            ).fetchone()
            if row is None:
                continue
            if memory_types and row["memory_type"] not in memory_types:
                continue
            salience = row["importance"] * (1.0 + row["access_count"] * 0.1)
            score = base + salience
            hits.append(self._row_to_hit(row, score))

        hits.sort(key=lambda h: h.score, reverse=True)

        # 更新访问信息（触达记忆）
        for h in hits[:top_k]:
            self._conn.execute(
                "UPDATE memories SET access_count=access_count+1, last_accessed=?"
                " WHERE id=?", (time.time(), h.id),
            )
        self._conn.commit()

        return hits[:top_k]

    def recall_full(self, hit_id: str) -> Optional[dict]:
        """渐进披露 L2：取一条记忆的完整内容与元数据"""
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id=?", (hit_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        return d

    # ── 图扩散召回 ──────────────────────────────────────────

    def recall_by_graph(self, seed_ids: List[str], top_k: int = 5,
                        max_depth: int = 2) -> List[MemoryHit]:
        """
        从种子记忆出发，沿 memory_links 边扩散激活召回关联记忆。
        图结构召回 —— 比纯向量/关键词更能发现"间接相关"。
        """
        if not seed_ids:
            return []
        visited = {s for s in seed_ids}
        frontier = list(seed_ids)
        results: Dict[str, float] = {}
        for _ in range(max_depth):
            if not frontier:
                break
            next_frontier = []
            ph = ",".join("?" * len(frontier))
            rows = self._conn.execute(
                f"SELECT from_id, to_id, weight FROM memory_links"
                f" WHERE from_id IN ({ph}) OR to_id IN ({ph})",
                frontier + frontier,
            ).fetchall()
            for r in rows:
                other = r["to_id"] if r["from_id"] in frontier else r["from_id"]
                if other in visited:
                    continue
                visited.add(other)
                results[other] = results.get(other, 0.0) + r["weight"]
                next_frontier.append(other)
            frontier = next_frontier

        if not results:
            return []
        hits = []
        for mid, w in results.items():
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id=?", (mid,)
            ).fetchone()
            if row:
                hits.append(self._row_to_hit(row, w * row["importance"]))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def link(self, mem_a: str, mem_b: str, relation: str = "related",
             weight: float = 0.5):
        """记忆↔记忆建边（幂等：存在则抬高权重）"""
        if mem_a == mem_b or not mem_a or not mem_b:
            return
        cur = self._conn.cursor()
        existing = cur.execute(
            "SELECT weight FROM memory_links WHERE from_id=? AND to_id=?",
            (mem_a, mem_b),
        ).fetchone()
        if existing:
            cur.execute(
                "UPDATE memory_links SET weight=MAX(weight,?) WHERE from_id=? AND to_id=?",
                (weight, mem_a, mem_b),
            )
        else:
            cur.execute(
                "INSERT OR IGNORE INTO memory_links (from_id,to_id,relation,weight)"
                " VALUES (?,?,?,?)",
                (mem_a, mem_b, relation, weight),
            )
            self._stats["total_links"] += 1
        self._conn.commit()

    # ── 整合与遗忘 ──────────────────────────────────────────

    def consolidate(self, sim_threshold: float = 0.50) -> int:
        """
        整合：合并内容高度相似（中文 n-gram > 阈值）的记忆为一条（保留高重要性者）。
        模仿睡眠整合的记忆压缩。返回合并的条数。
        """
        merged = 0
        rows = self._conn.execute(
            "SELECT id, content, importance, metadata, scope FROM memories"
            " ORDER BY created_at"
        ).fetchall()
        buckets: Dict[str, list] = {}
        for r in rows:
            buckets.setdefault(r["scope"], []).append(r)

        for scope, items in buckets.items():
            for i in range(len(items)):
                if items[i] is None:
                    continue
                for j in range(i + 1, len(items)):
                    if items[j] is None:
                        continue
                    sim = self._text_similarity(items[i]["content"], items[j]["content"])
                    if sim < sim_threshold:
                        continue
                    # 保留高重要性者，合并元数据
                    keeper, victim = (items[i], items[j]) \
                        if items[i]["importance"] >= items[j]["importance"] \
                        else (items[j], items[i])
                    self._merge_metadata(keeper, victim)
                    self._conn.execute(
                        "DELETE FROM memories WHERE id=?", (victim["id"],)
                    )
                    items[j] = None  # 不再参与后续比较
                    merged += 1
        self._conn.commit()
        if merged:
            self._stats["consolidations"] += merged
            logger.info("[SuperMemory] 整合合并 %d 条相似记忆", merged)
        return merged

    def forget(self, min_salience: float = 0.05, older_than_days: int = 14) -> int:
        """遗忘低显著性且久远的记忆（突触修剪）"""
        cutoff = time.time() - older_than_days * 86400
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM memories WHERE importance < ? AND created_at < ?",
            (min_salience, cutoff),
        )
        deleted = cur.rowcount
        self._conn.commit()
        if deleted:
            logger.info("[SuperMemory] 遗忘 %d 条低显著性记忆", deleted)
        return deleted

    # ── 统计 ────────────────────────────────────────────────

    def stats(self) -> Dict:
        mem_count = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        link_count = self._conn.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0]
        return {
            **self._stats,
            "total_memories": mem_count,
            "total_links": link_count,
            "by_type": {
                r["memory_type"]: r["n"]
                for r in self._conn.execute(
                    "SELECT memory_type, COUNT(*) n FROM memories GROUP BY memory_type"
                ).fetchall()
            },
        }

    def close(self):
        self._conn.close()

    # ── 内部工具 ────────────────────────────────────────────

    def _row_to_hit(self, row, score: float) -> MemoryHit:
        md = {}
        try:
            md = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        return MemoryHit(
            id=row["id"], content=row["content"][:120], memory_type=row["memory_type"],
            scope=row["scope"], importance=row["importance"],
            created_at=row["created_at"], last_accessed=row["last_accessed"],
            access_count=row["access_count"], score=round(score, 4), metadata=md,
        )

    def _merge_metadata(self, keeper, victim):
        km = {}
        vm = {}
        for r, d in ((keeper, km), (victim, vm)):
            try:
                d.update(json.loads(r["metadata"]) if r["metadata"] else {})
            except (json.JSONDecodeError, TypeError):
                pass
        km.update(vm)
        self._conn.execute(
            "UPDATE memories SET importance=?, metadata=? WHERE id=?",
            (max(keeper["importance"], victim["importance"]),
             json.dumps(km, ensure_ascii=False), keeper["id"]),
        )

    @staticmethod
    def _sha(content: str, scope: str) -> str:
        return hashlib.sha256((content + "\x00" + scope).encode("utf-8")).hexdigest()

    @staticmethod
    def _split_terms(query: str) -> List[str]:
        """把查询拆成词条：空白/常见中英文标点切分，去掉空词条"""
        import re
        parts = re.split(r"[\s，。？！、；：,.?!;:]+", query)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _fts_query(terms: List[str]) -> str:
        """trigram 词条拼 FTS 查询（仅 >=3 字符的词条有效，其余靠 LIKE 兜底）"""
        trigrams = [f'"{t}"' for t in terms if len(t) >= 3]
        return " OR ".join(trigrams)

    @staticmethod
    def _ngrams(text: str, n: int) -> set:
        import re
        s = re.sub(r"\s+", "", text)
        return {s[i:i + n] for i in range(len(s) - n + 1)}

    @classmethod
    def _text_similarity(cls, a: str, b: str) -> float:
        """中文 n-gram Jaccard 相似度（bigram+trigram 并集）——近重复/相关检测"""
        if not a or not b:
            return 0.0
        A = cls._ngrams(a, 2) | cls._ngrams(a, 3)
        B = cls._ngrams(b, 2) | cls._ngrams(b, 3)
        union = A | B
        if not union:
            return 0.0
        return len(A & B) / len(union)

    @staticmethod
    def _cosine(a, b) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


# ========== 模块级单例（对齐 decision_engine 的 _get_* 模式） ==========

_instance = None


def get_super_memory() -> SuperMemory:
    """懒加载单例（失败返回 None，不阻断）"""
    global _instance
    if _instance is not None:
        return _instance if _instance is not False else None
    try:
        _instance = SuperMemory()
        logger.info("[SuperMemory] 超长期记忆初始化成功: %s", _instance.db_path)
    except Exception as e:
        logger.warning("[SuperMemory] 初始化失败: %s", e)
        _instance = False
    return _instance if _instance is not False else None
