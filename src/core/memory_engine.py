"""
认知记忆系统（Cognitive Memory System）

三层记忆架构，模仿生物海马体：
  1. 工作记忆（Working Memory）— 当前上下文窗口
  2. 短期记忆（Short-term Memory）— 最近对话 + 事件
  3. 长期记忆（Long-term Memory）— 知识库 + 经验

三种记忆形态：
  1. 事实性记忆（Episodic）— 发生了什么（RAG 检索）
  2. 程序性记忆（Procedural）— 怎么做（技能/LoRA）
  3. 语义记忆（Semantic）— 是什么（知识图谱）

实现参考：
  - MemGPT: 可插拔记忆管理
  - EverMemOS: 终身记忆设计哲学
  - lightMem: 轻量化外挂记忆（睡眠整合+反思）
  - PlugMem: 插入式记忆
  - RF-Mem: 反思学习记忆
"""

import json
import logging
import time
import hashlib
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import OrderedDict

logger = logging.getLogger(__name__)


# ========== 记忆数据结构 ==========

@dataclass
class MemoryEntry:
    """单条记忆条目"""
    id: str                          # 唯一 ID
    content: str                     # 记忆内容
    memory_type: str                 # episodic / procedural / semantic
    layer: str                       # working / short_term / long_term
    importance: float = 0.5          # 重要性 [0, 1]
    embedding: List[float] = field(default_factory=list)  # 语义向量
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0          # 创建时间
    last_accessed: float = 0.0       # 最后访问时间
    access_count: int = 0            # 访问次数
    decay_rate: float = 0.01         # 衰减率

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.last_accessed == 0.0:
            self.last_accessed = self.created_at

    @property
    def age_hours(self) -> float:
        """记忆年龄（小时）"""
        return (time.time() - self.created_at) / 3600

    @property
    def salience(self) -> float:
        """显著性 = 重要性 × 新鲜度 × 访问频率"""
        freshness = max(0.1, 1.0 - self.age_hours * self.decay_rate)
        frequency = min(1.0, self.access_count * 0.1)
        return self.importance * freshness * (1.0 + frequency)

    def touch(self):
        """访问记忆（更新时间和计数）"""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class MemoryQuery:
    """记忆查询"""
    text: str                        # 查询文本
    memory_types: List[str] = field(default_factory=lambda: ["episodic", "procedural", "semantic"])
    layers: List[str] = field(default_factory=lambda: ["working", "short_term", "long_term"])
    top_k: int = 5
    min_importance: float = 0.0
    time_range: Optional[tuple] = None  # (start, end) 时间范围


@dataclass
class MemorySearchResult:
    """记忆搜索结果"""
    entry: MemoryEntry
    similarity: float                # 余弦相似度
    score: float                     # 综合得分 = similarity × salience


# ========== 工作记忆（上下文窗口） ==========

class WorkingMemory:
    """
    工作记忆 — 当前对话上下文。

    类比：前额叶皮层的工作记忆区。
    容量有限（7±2 项），使用滑动窗口。
    """

    def __init__(self, max_items: int = 10):
        self.max_items = max_items
        self.items: OrderedDict[str, MemoryEntry] = OrderedDict()

    def add(self, entry: MemoryEntry):
        """添加到工作记忆"""
        entry.layer = "working"
        self.items[entry.id] = entry
        # 超出容量时，移除最旧的
        while len(self.items) > self.max_items:
            self.items.popitem(last=False)
        logger.debug("[WorkingMemory] 添加: %s (当前 %s 项)", entry.id, len(self.items))

    def get_context(self, max_tokens: int = 2000) -> str:
        """获取当前上下文（用于 LLM prompt）"""
        context_parts = []
        total_len = 0
        for entry in reversed(list(self.values())):
            if total_len + len(entry.content) > max_tokens:
                break
            context_parts.append(entry.content)
            total_len += len(entry.content)
        return "\n".join(reversed(context_parts))

    def values(self):
        return self.items.values()

    def clear(self):
        self.items.clear()


# ========== 短期记忆 ==========

class ShortTermMemory:
    """
    短期记忆 — 最近的对话和事件。

    类比：海马体的短期缓冲区。
    使用 LRU 策略，按时间衰减。
    """

    def __init__(self, max_items: int = 100):
        self.max_items = max_items
        self.items: OrderedDict[str, MemoryEntry] = OrderedDict()

    def add(self, entry: MemoryEntry):
        """添加到短期记忆"""
        entry.layer = "short_term"
        self.items[entry.id] = entry
        while len(self.items) > self.max_items:
            self.items.popitem(last=False)

    def get_recent(self, n: int = 10) -> List[MemoryEntry]:
        """获取最近 N 条记忆"""
        items = list(self.values())
        return items[-n:]

    def values(self):
        return self.items.values()

    def consolidate(self, threshold: float = 0.7) -> List[MemoryEntry]:
        """
        整合：将重要的短期记忆提升到长期记忆。
        类比：睡眠时的记忆整合过程。
        """
        to_consolidate = []
        for entry in list(self.values()):
            if entry.salience >= threshold:
                to_consolidate.append(entry)
        return to_consolidate


# ========== 长期记忆（向量检索） ==========

class LongTermMemory:
    """
    长期记忆 — 持久化的知识和经验。

    类比：大脑皮层的长期存储。
    使用向量检索（ANN）实现语义查询。
    """

    def __init__(self, max_items: int = 10000):
        self.max_items = max_items
        self.items: Dict[str, MemoryEntry] = {}
        # 简单的向量索引（生产环境应用 HNSW）
        self._embeddings: List[tuple] = []  # (id, embedding)

    def add(self, entry: MemoryEntry):
        """添加到长期记忆"""
        entry.layer = "long_term"
        self.items[entry.id] = entry
        if entry.embedding:
            self._embeddings.append((entry.id, entry.embedding))
        logger.debug("[LongTermMemory] 添加: %s (总计 %s 条)", entry.id, len(self.items))

    def search(self, query_embedding: List[float], top_k: int = 5,
               memory_types: Optional[List[str]] = None,
               min_importance: float = 0.0) -> List[MemorySearchResult]:
        """
        向量检索：查找与查询最相关的记忆。

        使用余弦相似度 + 显著性加权排序。
        """
        if not query_embedding or not self._embeddings:
            return []

        results = []
        for entry_id, emb in self._embeddings:
            entry = self.items.get(entry_id)
            if not entry:
                continue

            # 过滤条件
            if memory_types and entry.memory_type not in memory_types:
                continue
            if entry.importance < min_importance:
                continue

            # 计算余弦相似度
            sim = self._cosine_similarity(query_embedding, emb)
            score = sim * entry.salience

            results.append(MemorySearchResult(
                entry=entry,
                similarity=sim,
                score=score,
            ))

        # 按综合得分排序
        results.sort(key=lambda x: x.score, reverse=True)

        # 更新访问信息
        for r in results[:top_k]:
            r.entry.touch()

        return results[:top_k]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        if len(a) != len(b) or len(a) == 0:
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def prune(self, min_salience: float = 0.1):
        """
        修剪：移除低显著性的记忆（遗忘机制）。
        """
        to_remove = []
        for entry_id, entry in self.items.items():
            if entry.salience < min_salience:
                to_remove.append(entry_id)

        for entry_id in to_remove:
            del self.items[entry_id]
            self._embeddings = [(eid, emb) for eid, emb in self._embeddings if eid != entry_id]

        if to_remove:
            logger.info("[LongTermMemory] 修剪 %s 条低显著性记忆", len(to_remove))


# ========== 反思学习引擎 ==========

class ReflectionEngine:
    """
    反思学习引擎 — 从经验中提取知识。

    参考 RF-Mem 工程方法：
    1. 收集执行记录
    2. 分析成功/失败模式
    3. 提取通用规则
    4. 存入长期记忆

    类比：人类的"复盘"过程。
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.execution_log: List[Dict] = []

    def record_execution(self, trace_id: str, action: str, success: bool,
                         context: str, result: str):
        """记录执行历史"""
        self.execution_log.append({
            "trace_id": trace_id,
            "action": action,
            "success": success,
            "context": context,
            "result": result,
            "timestamp": time.time(),
        })

    def reflect(self, n_recent: int = 20) -> Optional[MemoryEntry]:
        """
        反思：从最近的执行记录中提取经验。

        成功模式 → 正面强化
        失败模式 → 负面规避
        """
        if len(self.execution_log) < 5:
            return None

        recent = self.execution_log[-n_recent:]

        # 统计成功率
        successes = [e for e in recent if e["success"]]
        failures = [e for e in recent if not e["success"]]

        success_rate = len(successes) / len(recent) if recent else 0

        # 构建反思内容
        reflection_text = self._build_reflection_text(successes, failures, success_rate)

        # 创建反思记忆
        entry = MemoryEntry(
            id=f"reflection_{int(time.time())}",
            content=reflection_text,
            memory_type="procedural",
            layer="long_term",
            importance=min(1.0, 0.3 + success_rate * 0.5),
            metadata={
                "type": "reflection",
                "success_rate": success_rate,
                "sample_size": len(recent),
            },
        )

        logger.info("[ReflectionEngine] 反思完成: 成功率=%.2f, 样本=%d, 重要性=%.2f",
                    success_rate, len(recent), entry.importance)

        return entry

    def _build_reflection_text(self, successes: List[Dict],
                                failures: List[Dict],
                                success_rate: float) -> str:
        """构建反思文本"""
        parts = [f"执行反思（成功率 {success_rate:.0%}）："]

        if successes:
            # 提取最常见的成功动作
            action_counts = {}
            for s in successes:
                action_counts[s["action"]] = action_counts.get(s["action"], 0) + 1
            top_actions = sorted(action_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            parts.append(f"成功模式：{', '.join(f'{a}({c}次)' for a, c in top_actions)}")

        if failures:
            # 提取失败原因
            error_reasons = [f.get("result", "未知") for f in failures[:3]]
            parts.append(f"失败原因：{'; '.join(error_reasons[:3])}")

        return "\n".join(parts)


# ========== 认知记忆引擎（统一接口） ==========

class CognitiveMemoryEngine:
    """
    认知记忆引擎 — 统一的记忆管理接口。

    整合三层记忆 + 反思学习：
    1. 工作记忆：当前上下文
    2. 短期记忆：最近事件
    3. 长期记忆：知识库
    4. 反思引擎：经验提取

    实现四个闭环：
    - 记忆闭环：感知 → 工作记忆 → 短期 → 长期 → 检索 → 决策
    - 知识闭环：执行 → 反思 → 知识提取 → 长期记忆 → 检索
    - 学习闭环：成功/失败 → 权重调整 → 行为优化
    - 执行闭环：决策 → 执行 → 反馈 → 记忆 → 下次决策
    """

    def __init__(self, embed_fn=None, llm_client=None, persistence=None):
        """
        Args:
            embed_fn: 向量生成函数 (text) -> List[float]
            llm_client: LLM 客户端（用于反思）
            persistence: PersistentMemoryManager 实例（可选，提供持久化能力）
        """
        self.working = WorkingMemory(max_items=10)
        self.short_term = ShortTermMemory(max_items=100)
        self.long_term = LongTermMemory(max_items=10000)
        self.reflection = ReflectionEngine(llm_client)
        self.persistence = persistence

        # 默认使用轻量级字符级 embedding（无外部依赖）
        if embed_fn is None:
            try:
                from src.core.semantic_cache import _simple_embed
                embed_fn = _simple_embed
            except ImportError:
                pass
        self.embed_fn = embed_fn

        # 统计
        self._total_queries = 0
        self._total_stores = 0

        # 从持久化加载历史记忆
        if self.persistence:
            self._load_from_persistence()

    def remember(self, content: str, memory_type: str = "episodic",
                 importance: float = 0.5, metadata: Dict = None) -> MemoryEntry:
        """
        存入记忆。

        自动选择合适的记忆层：
        - 高重要性 → 直接存长期
        - 中重要性 → 存短期
        - 低重要性 → 仅工作记忆
        """
        entry_id = self._generate_id(content)

        # 生成 embedding
        embedding = []
        if self.embed_fn:
            try:
                embedding = self.embed_fn(content)
            except Exception as e:
                logger.warning("[Memory] embedding 生成失败: %s", e)

        entry = MemoryEntry(
            id=entry_id,
            content=content,
            memory_type=memory_type,
            layer="",  # 由下面决定
            importance=importance,
            embedding=embedding,
            metadata=metadata or {},
        )

        # 根据重要性选择记忆层
        if importance >= 0.8:
            self.long_term.add(entry)
            # 高重要性记忆立即持久化
            if self.persistence:
                try:
                    self.persistence.save_long_term(
                        entry=asdict(entry),
                        embedding=embedding if embedding else None,
                    )
                except Exception as e:
                    logger.warning("[Memory] 持久化写入失败: %s", e)
            logger.info("[Memory] 存入长期记忆: %s (importance=%.2f)", entry_id, importance)
        elif importance >= 0.3:
            self.short_term.add(entry)
            logger.info("[Memory] 存入短期记忆: %s (importance=%.2f)", entry_id, importance)

        # 总是加入工作记忆
        self.working.add(entry)
        self._total_stores += 1

        return entry

    def recall(self, query: str, top_k: int = 5,
               memory_types: Optional[List[str]] = None) -> List[MemorySearchResult]:
        """
        检索记忆。

        从三层记忆中检索，按相关性排序。
        类比：人类的"联想"过程。
        """
        self._total_queries += 1

        # 生成查询向量
        query_embedding = []
        if self.embed_fn:
            try:
                query_embedding = self.embed_fn(query)
            except Exception as e:
                logger.warning("[Memory] 查询 embedding 生成失败: %s", e)

        results = []

        # 1. 搜索长期记忆（向量检索 + 关键词兜底）
        if query_embedding:
            long_term_results = self.long_term.search(
                query_embedding, top_k=top_k, memory_types=memory_types
            )
            results.extend(long_term_results)

        # 关键词兜底：向量检索可能因稀疏 embedding 漏掉精确匹配
        query_lower = query.lower()
        seen_ids = {r.entry.id for r in results}
        for entry in self.long_term.items.values():
            if entry.id in seen_ids:
                continue
            if memory_types and entry.memory_type not in memory_types:
                continue
            if query_lower in entry.content.lower():
                results.append(MemorySearchResult(
                    entry=entry, similarity=0.85, score=0.85 * entry.salience
                ))

        # 精确关键词匹配优先排序
        for r in results:
            if query_lower in r.entry.content.lower():
                r.score += 1.0  # 确保精确匹配排在最前
        results.sort(key=lambda x: x.score, reverse=True)

        # 2. 搜索短期记忆（线性扫描）
        for entry in self.short_term.values():
            if memory_types and entry.memory_type not in memory_types:
                continue
            sim = 0.0
            if query_embedding and entry.embedding:
                sim = self.long_term._cosine_similarity(query_embedding, entry.embedding)
            # 关键词匹配（即使有 embedding 也作为补充）
            if sim < 0.5 and query.lower() in entry.content.lower():
                sim = max(sim, 0.8)
            if sim > 0.3:
                results.append(MemorySearchResult(
                    entry=entry, similarity=sim, score=sim * entry.salience
                ))

        # 3. 搜索工作记忆
        for entry in self.working.values():
            if memory_types and entry.memory_type not in memory_types:
                continue
            sim = 0.0
            if query_embedding and entry.embedding:
                sim = self.long_term._cosine_similarity(query_embedding, entry.embedding)
            # 关键词匹配
            if sim < 0.5 and query.lower() in entry.content.lower():
                sim = max(sim, 0.9)
            if sim > 0.3:
                results.append(MemorySearchResult(
                    entry=entry, similarity=sim, score=sim * entry.salience
                ))

        # 去重 + 排序
        seen = set()
        unique_results = []
        for r in results:
            if r.entry.id not in seen:
                seen.add(r.entry.id)
                unique_results.append(r)
        unique_results.sort(key=lambda x: x.score, reverse=True)

        return unique_results[:top_k]

    def get_context(self, max_tokens: int = 2000) -> str:
        """获取当前上下文（用于 LLM prompt）"""
        return self.working.get_context(max_tokens)

    def consolidate(self):
        """
        记忆整合 — 将重要的短期记忆提升到长期记忆。
        类比：睡眠时的记忆整合。
        """
        to_consolidate = self.short_term.consolidate(threshold=0.7)
        for entry in to_consolidate:
            self.long_term.add(entry)
            logger.info("[Memory] 整合: %s 短期 → 长期 (salience=%.2f)", entry.id, entry.salience)

        # 修剪低显著性的长期记忆
        self.long_term.prune(min_salience=0.05)

        logger.info("[Memory] 整合完成: 短期=%d条, 长期=%d条",
                    len(list(self.short_term.values())), len(self.long_term.items))

        # 整合后持久化
        if self.persistence:
            self.save()

    def reflect_and_learn(self) -> Optional[MemoryEntry]:
        """反思学习"""
        return self.reflection.reflect()

    def record_execution(self, trace_id: str, action: str, success: bool,
                         context: str = "", result: str = ""):
        """记录执行（供反思引擎使用）"""
        self.reflection.record_execution(trace_id, action, success, context, result)

    def stats(self) -> Dict:
        """返回记忆统计"""
        return {
            "working_memory": len(list(self.working.values())),
            "short_term_memory": len(list(self.short_term.values())),
            "long_term_memory": len(self.long_term.items),
            "total_queries": self._total_queries,
            "total_stores": self._total_stores,
            "execution_log_size": len(self.reflection.execution_log),
        }

    def _generate_id(self, content: str) -> str:
        """生成记忆 ID"""
        hash_val = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"mem_{int(time.time())}_{hash_val}"

    # ========== 持久化 ==========

    def _load_from_persistence(self):
        """从持久化存储加载历史记忆"""
        if not self.persistence:
            return

        try:
            # 加载长期记忆
            long_term_data = self.persistence.load_long_term()
            embeddings_map = self.persistence.load_embeddings()

            loaded = 0
            for mem_dict in long_term_data:
                entry = MemoryEntry(
                    id=mem_dict["id"],
                    content=mem_dict["content"],
                    memory_type=mem_dict["memory_type"],
                    layer=mem_dict.get("layer", "long_term"),
                    importance=mem_dict.get("importance", 0.5),
                    embedding=embeddings_map.get(mem_dict["id"], []),
                    metadata=mem_dict.get("metadata", {}),
                    created_at=mem_dict.get("created_at", 0),
                    last_accessed=mem_dict.get("last_accessed", 0),
                    access_count=mem_dict.get("access_count", 0),
                    decay_rate=mem_dict.get("decay_rate", 0.01),
                )
                self.long_term.add(entry)
                loaded += 1

            # 加载短期记忆
            short_term_data = self.persistence.load_short_term()
            for mem_dict in short_term_data:
                entry = MemoryEntry(
                    id=mem_dict["id"],
                    content=mem_dict["content"],
                    memory_type=mem_dict["memory_type"],
                    layer="short_term",
                    importance=mem_dict.get("importance", 0.5),
                    metadata=mem_dict.get("metadata", {}),
                    created_at=mem_dict.get("created_at", 0),
                    last_accessed=mem_dict.get("last_accessed", 0),
                    access_count=mem_dict.get("access_count", 0),
                )
                self.short_term.add(entry)
                loaded += 1

            if loaded > 0:
                logger.info("[Memory] 从持久化加载 %d 条记忆 (长期=%d, 短期=%d)",
                            loaded, len(self.long_term.items), len(list(self.short_term.values())))
        except Exception as e:
            logger.warning("[Memory] 加载持久化记忆失败: %s", e)

    def save(self):
        """将当前记忆状态保存到持久化存储"""
        if not self.persistence:
            return

        try:
            # 保存长期记忆
            for entry in self.long_term.items.values():
                self.persistence.save_long_term(
                    entry={
                        "id": entry.id,
                        "content": entry.content,
                        "memory_type": entry.memory_type,
                        "layer": "long_term",
                        "importance": entry.importance,
                        "metadata": entry.metadata,
                        "created_at": entry.created_at,
                        "last_accessed": entry.last_accessed,
                        "access_count": entry.access_count,
                        "decay_rate": entry.decay_rate,
                    },
                    embedding=entry.embedding if entry.embedding else None,
                )

            # 保存短期记忆
            short_term_list = []
            for entry in self.short_term.values():
                short_term_list.append({
                    "id": entry.id,
                    "content": entry.content,
                    "memory_type": entry.memory_type,
                    "importance": entry.importance,
                    "metadata": entry.metadata,
                    "created_at": entry.created_at,
                    "last_accessed": entry.last_accessed,
                    "access_count": entry.access_count,
                })
            self.persistence.save_short_term(short_term_list)

            logger.info("[Memory] 持久化完成: 长期=%d, 短期=%d",
                        len(self.long_term.items), len(list(self.short_term.values())))
        except Exception as e:
            logger.warning("[Memory] 持久化保存失败: %s", e)
