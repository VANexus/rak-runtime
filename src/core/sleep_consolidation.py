"""
睡眠整合（Sleep Consolidation）

模仿人类睡眠时的记忆整合过程：
1. 短期记忆 → 长期记忆迁移（重要性筛选）
2. 低显著性记忆遗忘（突触修剪）
3. 反思学习批处理（经验提取）
4. 记忆压缩（相似记忆合并）
5. 知识图谱更新（语义关系重建）

参考：
- lightMem: 轻量化外挂记忆（睡眠整合+反思）
- EverMemOS: 终身记忆设计哲学
- 海马体记忆巩固理论

触发方式：
- 定时触发：每隔 N 小时
- 阈值触发：短期记忆满时
- 手动触发：API 调用
"""

import logging
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """整合结果"""
    memories_consolidated: int     # 迁移到长期的记忆数
    memories_pruned: int           # 遗忘的记忆数
    reflections_generated: int     # 生成的反思数
    compressions_made: int         # 压缩的记忆数
    elapsed_ms: float              # 耗时
    details: Dict                  # 详细信息


class SleepConsolidation:
    """
    睡眠整合引擎。

    模仿人类睡眠中的记忆巩固：
    - NREM 睡眠：海马体 → 大脑皮层的记忆重放
    - REM 睡眠：情绪记忆处理 + 创造性联想

    整合流程：
    1. 筛选：从短期记忆中选择重要的
    2. 迁移：将选中的记忆写入长期存储
    3. 遗忘：移除低显著性的旧记忆
    4. 反思：分析执行记录，提取经验
    5. 压缩：合并相似记忆，减少冗余
    """

    def __init__(self,
                 memory_engine=None,
                 persistence_manager=None,
                 llm_client=None,
                 consolidation_threshold: float = 0.5,
                 prune_threshold: float = 0.05,
                 max_consolidation_per_cycle: int = 50):
        """
        Args:
            memory_engine: 认知记忆引擎实例
            persistence_manager: 持久化管理器实例
            llm_client: LLM 客户端（用于反思）
            consolidation_threshold: 整合阈值
            prune_threshold: 修剪阈值
            max_consolidation_per_cycle: 每轮最大整合数
        """
        self.memory_engine = memory_engine
        self.persistence = persistence_manager
        self.llm_client = llm_client
        self.consolidation_threshold = consolidation_threshold
        self.prune_threshold = prune_threshold
        self.max_consolidation = max_consolidation_per_cycle

        # 整合历史
        self.history: List[ConsolidationResult] = []
        self.total_cycles = 0

    def consolidate(self) -> ConsolidationResult:
        """
        执行一轮睡眠整合。

        Returns:
            ConsolidationResult: 整合结果
        """
        start_time = time.time()
        self.total_cycles += 1

        logger.info("[SleepConsolidation] === 第 %s 轮整合开始 ===", self.total_cycles)

        stats = {
            "consolidated": 0,
            "pruned": 0,
            "reflections": 0,
            "compressions": 0,
        }

        # 1. 短期 → 长期迁移
        consolidated = self._consolidate_short_to_long()
        stats["consolidated"] = consolidated

        # 2. 遗忘低显著性记忆
        pruned = self._prune_memories()
        stats["pruned"] = pruned

        # 3. 反思学习
        reflections = self._generate_reflections()
        stats["reflections"] = reflections

        # 4. 记忆压缩
        compressions = self._compress_memories()
        stats["compressions"] = compressions

        # 5. 持久化当前状态
        self._persist_state()

        elapsed_ms = (time.time() - start_time) * 1000

        result = ConsolidationResult(
            memories_consolidated=consolidated,
            memories_pruned=pruned,
            reflections_generated=reflections,
            compressions_made=compressions,
            elapsed_ms=elapsed_ms,
            details=stats,
        )

        self.history.append(result)

        logger.info("[SleepConsolidation] === 整合完成: 迁移=%d, 遗忘=%d, 反思=%d, 压缩=%d, 耗时=%.0fms ===",
                    consolidated, pruned, reflections, compressions, elapsed_ms)

        return result

    def _consolidate_short_to_long(self) -> int:
        """
        短期 → 长期记忆迁移。

        筛选标准：
        - 显著性 >= 阈值
        - 访问次数 >= 1
        - 不是太旧（< 7天）
        """
        if not self.memory_engine:
            return 0

        consolidated = 0
        short_term = list(self.memory_engine.short_term.values())

        for entry in short_term:
            if consolidated >= self.max_consolidation:
                break

            # 检查是否值得迁移
            if entry.salience >= self.consolidation_threshold:
                # 迁移到长期记忆
                self.memory_engine.long_term.add(entry)
                consolidated += 1

                logger.debug("[SleepConsolidation] 迁移: %s (salience=%.3f)", entry.id, entry.salience)

        # 从短期记忆中移除已迁移的
        if consolidated > 0:
            logger.info("[SleepConsolidation] 迁移 %s 条记忆到长期存储", consolidated)

        return consolidated

    def _prune_memories(self) -> int:
        """
        遗忘低显著性记忆。

        模仿突触修剪：
        - 长期未访问的记忆逐渐衰减
        - 重要性低的记忆被遗忘
        """
        if not self.memory_engine:
            return 0

        pruned = 0

        # 修剪长期记忆
        to_remove = []
        for entry_id, entry in self.memory_engine.long_term.items.items():
            if entry.salience < self.prune_threshold:
                to_remove.append(entry_id)

        for entry_id in to_remove:
            del self.memory_engine.long_term.items[entry_id]
            # 也从向量索引中移除
            self.memory_engine.long_term._embeddings = [
                (eid, emb) for eid, emb in self.memory_engine.long_term._embeddings
                if eid != entry_id
            ]
            pruned += 1

        if pruned > 0:
            logger.info("[SleepConsolidation] 遗忘 %s 条低显著性记忆", pruned)

        # 也修剪持久化存储
        if self.persistence:
            pruned += self.persistence.prune()

        return pruned

    def _generate_reflections(self) -> int:
        """
        生成反思记忆。

        分析最近的执行记录，提取经验教训。
        """
        if not self.memory_engine:
            return 0

        reflections = 0

        # 使用反思引擎
        reflection = self.memory_engine.reflect_and_learn()
        if reflection:
            # 存入长期记忆
            self.memory_engine.long_term.add(reflection)
            reflections += 1

            # 持久化反思
            if self.persistence:
                self.persistence.record_reflection({
                    "id": reflection.id,
                    "content": reflection.content,
                    "importance": reflection.importance,
                    "timestamp": time.time(),
                })

            logger.info("[SleepConsolidation] 生成反思: %s", reflection.id)

        # 使用 LLM 生成更深入的反思（如果可用）
        if self.llm_client and self.memory_engine.reflection.execution_log:
            llm_reflection = self._llm_reflect()
            if llm_reflection:
                self.memory_engine.long_term.add(llm_reflection)
                reflections += 1

        return reflections

    def _llm_reflect(self) -> Optional[object]:
        """使用 LLM 进行深度反思"""
        try:
            # 获取最近的执行记录
            recent = self.memory_engine.reflection.execution_log[-20:]
            if not recent:
                return None

            # 构建反思 prompt
            success_count = sum(1 for e in recent if e.get("success"))
            fail_count = len(recent) - success_count
            actions = set(e.get("action", "unknown") for e in recent)

            prompt = f"""分析最近的执行记录，提取经验教训。

统计：
- 总执行: {len(recent)}
- 成功: {success_count}
- 失败: {fail_count}
- 涉及动作: {', '.join(actions)}

执行记录：
{chr(10).join(f'- {e.get("action")}: {"成功" if e.get("success") else "失败"} ({e.get("context", "")})' for e in recent[:10])}

请用一句话总结最重要的经验教训。"""

            response = self.llm_client.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    break

            if text:
                from src.core.memory_engine import MemoryEntry
                return MemoryEntry(
                    id=f"llm_reflection_{int(time.time())}",
                    content=text,
                    memory_type="procedural",
                    layer="long_term",
                    importance=0.8,
                    metadata={"type": "llm_reflection", "sample_size": len(recent)},
                )

        except Exception as e:
            logger.warning("[SleepConsolidation] LLM 反思失败: %s", e)

        return None

    def _compress_memories(self) -> int:
        """
        记忆压缩：合并相似记忆。

        策略：
        - 内容高度相似（> 0.9）的记忆合并
        - 保留更重要/更新的那个
        - 合并元数据
        """
        if not self.memory_engine:
            return 0

        compressed = 0
        items = list(self.memory_engine.long_term.items.values())

        # 简单策略：按内容前缀分组
        prefix_groups = {}
        for entry in items:
            # 取内容前 20 字符作为分组 key
            prefix = entry.content[:20]
            if prefix not in prefix_groups:
                prefix_groups[prefix] = []
            prefix_groups[prefix].append(entry)

        for prefix, group in prefix_groups.items():
            if len(group) <= 1:
                continue

            # 保留最重要的那个
            group.sort(key=lambda e: e.importance, reverse=True)
            keeper = group[0]

            for duplicate in group[1:]:
                # 如果内容非常相似，合并
                if self._content_similarity(keeper.content, duplicate.content) > 0.8:
                    # 合并元数据
                    for k, v in duplicate.metadata.items():
                        if k not in keeper.metadata:
                            keeper.metadata[k] = v

                    # 移除重复
                    if duplicate.id in self.memory_engine.long_term.items:
                        del self.memory_engine.long_term.items[duplicate.id]
                        compressed += 1

        if compressed > 0:
            logger.info("[SleepConsolidation] 压缩 %s 条重复记忆", compressed)

        return compressed

    def _content_similarity(self, a: str, b: str) -> float:
        """简单的内容相似度（字符级 Jaccard）"""
        set_a = set(a)
        set_b = set(b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _persist_state(self):
        """持久化当前记忆状态"""
        if not self.persistence or not self.memory_engine:
            return

        try:
            # 保存短期记忆
            short_term_data = []
            for entry in self.memory_engine.short_term.values():
                short_term_data.append({
                    "id": entry.id,
                    "content": entry.content,
                    "memory_type": entry.memory_type,
                    "importance": entry.importance,
                    "created_at": entry.created_at,
                    "last_accessed": entry.last_accessed,
                    "access_count": entry.access_count,
                    "metadata": entry.metadata,
                })
            self.persistence.save_short_term(short_term_data)

            # 保存长期记忆
            for entry in self.memory_engine.long_term.items.values():
                self.persistence.save_long_term(
                    {
                        "id": entry.id,
                        "content": entry.content,
                        "memory_type": entry.memory_type,
                        "layer": entry.layer,
                        "importance": entry.importance,
                        "created_at": entry.created_at,
                        "last_accessed": entry.last_accessed,
                        "access_count": entry.access_count,
                        "decay_rate": entry.decay_rate,
                        "metadata": entry.metadata,
                    },
                    entry.embedding if entry.embedding else None,
                )

            logger.debug("[SleepConsolidation] 状态已持久化")

        except Exception as e:
            logger.warning("[SleepConsolidation] 持久化失败: %s", e)

    def restore_state(self):
        """从持久化存储恢复记忆状态"""
        if not self.persistence or not self.memory_engine:
            return

        try:
            # 恢复短期记忆
            short_term_data = self.persistence.load_short_term()
            from src.core.memory_engine import MemoryEntry
            for data in short_term_data:
                entry = MemoryEntry(
                    id=data["id"],
                    content=data["content"],
                    memory_type=data["memory_type"],
                    layer="short_term",
                    importance=data.get("importance", 0.5),
                    created_at=data.get("created_at", 0),
                    last_accessed=data.get("last_accessed", 0),
                    access_count=data.get("access_count", 0),
                    metadata=data.get("metadata", {}),
                )
                self.memory_engine.short_term.add(entry)

            # 恢复长期记忆
            long_term_data = self.persistence.load_long_term()
            embeddings = self.persistence.load_embeddings()

            for data in long_term_data:
                entry = MemoryEntry(
                    id=data["id"],
                    content=data["content"],
                    memory_type=data["memory_type"],
                    layer="long_term",
                    importance=data.get("importance", 0.5),
                    created_at=data.get("created_at", 0),
                    last_accessed=data.get("last_accessed", 0),
                    access_count=data.get("access_count", 0),
                    decay_rate=data.get("decay_rate", 0.01),
                    metadata=data.get("metadata", {}),
                    embedding=embeddings.get(data["id"], []),
                )
                self.memory_engine.long_term.add(entry)

            logger.info("[SleepConsolidation] 恢复完成: 短期=%d条, 长期=%d条",
                        len(short_term_data), len(long_term_data))

        except Exception as e:
            logger.warning("[SleepConsolidation] 恢复失败: %s", e)

    def stats(self) -> Dict:
        """返回统计"""
        return {
            "total_cycles": self.total_cycles,
            "consolidation_threshold": self.consolidation_threshold,
            "prune_threshold": self.prune_threshold,
            "history_size": len(self.history),
            "last_cycle": self.history[-1].__dict__ if self.history else None,
        }
