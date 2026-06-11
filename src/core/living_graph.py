"""
活体知识图谱（Living Knowledge Graph）— 认知场的核心。

不是 RAG（数据库检索），不是静态图谱，而是：
- 节点带状态（情绪、需求、激活度）
- 边带权重+时间衰减
- 扩散激活（从一个节点开始，能量沿边传播）
- 自动建图（从交互中学习连接）

这才是真正接近人脑的记忆系统。
"""

import json
import logging
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.core._utils import atomic_write_json

logger = logging.getLogger("rak.living_graph")


# ── 节点和边 ──────────────────────────────────────────────

@dataclass
class GraphNode:
    """图节点"""
    id: str                       # 唯一标识
    node_type: str                # "entity" | "concept" | "event" | "skill" | "emotion"
    label: str                    # 显示标签
    content: str = ""             # 详细内容
    created_at: float = field(default_factory=time.time)
    last_activated: float = field(default_factory=time.time)
    activation_count: int = 0     # 被激活次数
    base_activation: float = 0.5  # 基础激活度（0~1）
    metadata: dict = field(default_factory=dict)

    def current_activation(self) -> float:
        """当前激活度（随时间衰减）"""
        hours = (time.time() - self.last_activated) / 3600
        decay = math.exp(-0.1 * hours)  # 约 7 小时衰减一半
        return self.base_activation * decay

    def activate(self, energy: float = 0.3):
        """被激活"""
        self.last_activated = time.time()
        self.activation_count += 1
        self.base_activation = min(1.0, self.base_activation + energy * 0.5)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.node_type,
            "label": self.label,
            "content": self.content[:100],
            "activation": round(self.current_activation(), 3),
            "count": self.activation_count,
        }


@dataclass
class GraphEdge:
    """图边"""
    source: str                   # 源节点 ID
    target: str                   # 目标节点 ID
    edge_type: str                # "related_to" | "caused_by" | "leads_to" | "triggers" | "inhibits"
    weight: float = 0.5           # 当前权重 (0~1)
    created_at: float = field(default_factory=time.time)
    last_activated: float = field(default_factory=time.time)
    activation_count: int = 0
    decay_rate: float = 0.05      # 衰减速率（每小时）

    def time_decay(self) -> float:
        """时间衰减后的有效权重"""
        hours = (time.time() - self.last_activated) / 3600
        return self.weight * math.exp(-self.decay_rate * hours)

    def activate(self, boost: float = 0.1):
        """被激活（赫布学习：一起激活的节点连接增强）"""
        self.last_activated = time.time()
        self.activation_count += 1
        self.weight = min(1.0, self.weight + boost)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.edge_type,
            "weight": round(self.time_decay(), 3),
            "count": self.activation_count,
        }


# ── 激活结果 ──────────────────────────────────────────────

@dataclass
class ActivationResult:
    """扩散激活的结果"""
    node_id: str
    label: str
    content: str
    energy: float                 # 最终能量
    depth: int                    # 激活深度
    path: list                    # 激活路径


# ── 核心图 ────────────────────────────────────────────────

class LivingGraph:
    """
    活体知识图谱。

    核心操作：
    1. add_node / add_edge — 建图
    2. diffuse — 扩散激活（替代 TopK 检索）
    3. strengthen — 赫布学习（一起激活的连接增强）
    4. decay — 时间衰减（不用的连接弱化）
    5. auto_build — 从文本自动提取实体和关系
    """

    def __init__(self, persist_path: Optional[str] = None):
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}  # key: "source→target"
        self._adjacency: dict[str, list[str]] = defaultdict(list)  # node_id → [neighbor_ids]
        self._persist_path = Path(persist_path) if persist_path else None

        # 统计
        self._stats = {
            "total_diffusions": 0,
            "total_activations": 0,
            "total_auto_builds": 0,
        }

        # 加载已有数据
        if self._persist_path and self._persist_path.exists():
            self._load()

    # ── 建图 ──────────────────────────────────────────────

    def add_node(self, node_id: str, node_type: str = "concept",
                 label: str = "", content: str = "", **kwargs) -> GraphNode:
        """添加节点（已存在则更新）"""
        if node_id in self._nodes:
            node = self._nodes[node_id]
            if content:
                node.content = content
            if label:
                node.label = label
            return node

        node = GraphNode(
            id=node_id,
            node_type=node_type,
            label=label or node_id,
            content=content,
            **kwargs,
        )
        self._nodes[node_id] = node
        return node

    def add_edge(self, source: str, target: str, edge_type: str = "related_to",
                 weight: float = 0.5) -> GraphEdge:
        """添加边（已存在则增强权重）"""
        edge_key = f"{source}→{target}"

        if edge_key in self._edges:
            edge = self._edges[edge_key]
            edge.activate(boost=0.05)
            return edge

        # 确保节点存在
        if source not in self._nodes:
            self.add_node(source)
        if target not in self._nodes:
            self.add_node(target)

        edge = GraphEdge(
            source=source,
            target=target,
            edge_type=edge_type,
            weight=weight,
        )
        self._edges[edge_key] = edge
        self._adjacency[source].append(target)

        # 双向连接（除非是 directed 类型）
        if edge_type not in ("caused_by", "leads_to", "triggers"):
            self._adjacency[target].append(source)

        return edge

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def get_neighbors(self, node_id: str) -> list[tuple[str, GraphEdge]]:
        """获取邻居节点和对应的边"""
        result = []
        for neighbor_id in self._adjacency.get(node_id, []):
            edge_key = f"{node_id}→{neighbor_id}"
            if edge_key in self._edges:
                result.append((neighbor_id, self._edges[edge_key]))
            else:
                # 反向边
                edge_key = f"{neighbor_id}→{node_id}"
                if edge_key in self._edges:
                    result.append((neighbor_id, self._edges[edge_key]))
        return result

    # ── 扩散激活 ──────────────────────────────────────────

    def diffuse(self, start_node: str, energy: float = 1.0,
                max_depth: int = 3, min_energy: float = 0.05) -> list[ActivationResult]:
        """
        从一个节点开始扩散激活。

        这是核心算法——替代 TopK 检索。
        能量沿边传播，经过时间衰减的边传递更少能量。
        越远的节点激活越弱。
        """
        self._stats["total_diffusions"] += 1

        # 如果起始节点不存在，尝试模糊匹配
        if start_node not in self._nodes:
            matched = self._fuzzy_find_node(start_node)
            if matched:
                start_node = matched
            else:
                return []

        activated: dict[str, tuple[float, int, list]] = {}  # node_id → (energy, depth, path)
        queue = [(start_node, energy, 0, [start_node])]

        while queue:
            node_id, current_energy, depth, path = queue.pop(0)

            if depth > max_depth or current_energy < min_energy:
                continue
            if node_id in activated and activated[node_id][0] >= current_energy:
                continue

            activated[node_id] = (current_energy, depth, path)

            # 激活节点本身
            node = self._nodes[node_id]
            node.activate(current_energy * 0.3)
            self._stats["total_activations"] += 1

            # 扩散到邻居
            for neighbor_id, edge in self.get_neighbors(node_id):
                decay = edge.time_decay()
                transferred = current_energy * decay * 0.7  # 每层保留 70% 能量
                if transferred >= min_energy:
                    # 赫布学习：被一起激活的边增强
                    edge.activate(boost=0.02)
                    queue.append((neighbor_id, transferred, depth + 1, path + [neighbor_id]))

        # 构建结果
        results = []
        for node_id, (energy, depth, path) in activated.items():
            node = self._nodes[node_id]
            results.append(ActivationResult(
                node_id=node_id,
                label=node.label,
                content=node.content,
                energy=round(energy, 4),
                depth=depth,
                path=path,
            ))

        # 按能量排序
        results.sort(key=lambda r: r.energy, reverse=True)
        return results

    def diffuse_from_text(self, text: str, energy: float = 1.0,
                          max_depth: int = 3) -> list[ActivationResult]:
        """
        从文本中提取关键词，多点扩散。

        这是对外的主要接口——输入一句话，返回激活的记忆网络。
        """
        # 提取关键词
        keywords = self._extract_keywords(text)
        if not keywords:
            return []

        # 多点扩散，合并结果
        all_activations: dict[str, ActivationResult] = {}

        for keyword in keywords:
            # 精确匹配或模糊匹配
            node_id = keyword
            if node_id not in self._nodes:
                matched = self._fuzzy_find_node(keyword)
                if matched:
                    node_id = matched
                else:
                    continue

            results = self.diffuse(node_id, energy=energy / len(keywords), max_depth=max_depth)
            for r in results:
                if r.node_id not in all_activations or r.energy > all_activations[r.node_id].energy:
                    all_activations[r.node_id] = r

        # 合并并排序
        merged = list(all_activations.values())
        merged.sort(key=lambda r: r.energy, reverse=True)
        return merged

    # ── 自动建图 ──────────────────────────────────────────

    def auto_build_from_interaction(self, query: str, action: str,
                                    success: bool = True, context: str = ""):
        """
        从一次交互中自动提取实体和关系，建图。

        这是学习机制——每次交互都在丰富图谱。
        """
        self._stats["total_auto_builds"] += 1

        # 提取实体
        entities = self._extract_entities(query)
        action_entity = f"action:{action}"

        # 添加动作节点
        self.add_node(action_entity, node_type="event", label=action, content=query)

        # 实体与动作的连接
        for entity in entities:
            self.add_node(entity, node_type="entity", label=entity)
            edge_type = "leads_to" if success else "related_to"
            self.add_edge(entity, action_entity, edge_type=edge_type, weight=0.6)

        # 实体之间的连接（共现关系）
        for i, e1 in enumerate(entities):
            for e2 in entities[i+1:]:
                self.add_edge(e1, e2, edge_type="related_to", weight=0.3)

        # 成功/失败标记
        if success:
            self.add_node("success", node_type="concept", label="成功")
            self.add_edge(action_entity, "success", "leads_to", 0.5)
        else:
            self.add_node("failure", node_type="concept", label="失败")
            self.add_edge(action_entity, "failure", "caused_by", 0.5)

        # 上下文实体
        if context:
            ctx_entities = self._extract_entities(context)
            for entity in ctx_entities:
                self.add_node(entity, node_type="concept", label=entity)
                for q_entity in entities:
                    self.add_edge(entity, q_entity, "related_to", 0.4)

    def auto_build_from_memory(self, content: str, memory_type: str = "episodic"):
        """从记忆条目自动建图"""
        entities = self._extract_entities(content)
        for i, e1 in enumerate(entities):
            self.add_node(e1, node_type="concept" if memory_type == "semantic" else "entity")
            for e2 in entities[i+1:]:
                self.add_edge(e1, e2, "associated_with", 0.4)

    # ── 实体提取 ──────────────────────────────────────────

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本中提取关键词"""
        keywords = set()

        # 设备关键词
        devices = ["灯", "锁", "门", "电机", "舵机", "机器人", "light", "lock", "door", "motor"]
        for d in devices:
            if d in text.lower():
                keywords.add(d)

        # 动作关键词
        actions = ["开", "关", "打开", "关闭", "前进", "后退", "左转", "右转", "跳舞", "点头", "摇头"]
        for a in actions:
            if a in text:
                keywords.add(a)

        # 实体关键词（简单分词）
        words = text.replace("，", " ").replace("。", " ").replace("？", " ").split()
        for w in words:
            if len(w) >= 2 and w not in {"的", "了", "是", "在", "和", "就", "都", "要", "会"}:
                keywords.add(w)

        return list(keywords)[:10]  # 最多 10 个关键词

    def _extract_entities(self, text: str) -> list[str]:
        """从文本中提取实体"""
        entities = set()

        # 设备实体
        device_map = {
            "灯": "灯", "light": "灯", "锁": "锁", "lock": "锁",
            "门": "门", "door": "门", "电机": "电机", "motor": "电机",
            "机器人": "机器人", "robot": "机器人",
        }
        for key, entity in device_map.items():
            if key in text.lower():
                entities.add(entity)

        # 房间/位置
        locations = ["客厅", "卧室", "厨房", "门口", "房间"]
        for loc in locations:
            if loc in text:
                entities.add(loc)

        # 简单分词
        words = text.replace("，", " ").replace("。", " ").replace("？", " ").split()
        for w in words:
            if len(w) >= 2 and w not in {"的", "了", "是", "在", "和", "就", "都", "要", "会", "把", "被", "给"}:
                entities.add(w)

        return list(entities)[:8]

    def _fuzzy_find_node(self, query: str) -> Optional[str]:
        """模糊匹配节点"""
        query_lower = query.lower()
        best_match = None
        best_score = 0

        for node_id, node in self._nodes.items():
            # 包含关系
            if query_lower in node_id.lower() or node_id.lower() in query_lower:
                score = len(query_lower) / max(len(node_id.lower()), 1)
                if score > best_score:
                    best_score = score
                    best_match = node_id
            # 标签匹配
            elif query_lower in node.label.lower():
                score = 0.5
                if score > best_score:
                    best_score = score
                    best_match = node_id

        return best_match if best_score > 0.3 else None

    # ── 转为记忆上下文 ────────────────────────────────────

    def to_memory_context(self, activations: list[ActivationResult],
                          max_items: int = 10) -> str:
        """
        将激活结果转为 prompt 可用的记忆上下文。

        这是与决策引擎的接口——替代原来的 _build_memory_context。
        """
        if not activations:
            return ""

        lines = ["## 激活的记忆网络"]
        for i, act in enumerate(activations[:max_items]):
            # 能量条
            energy_bar = "█" * int(act.energy * 10) + "░" * (10 - int(act.energy * 10))

            if act.content:
                lines.append(f"- [{act.label}] {energy_bar} {act.content[:80]}")
            else:
                lines.append(f"- [{act.label}] {energy_bar}")

            # 显示激活路径（如果不是直接激活）
            if act.depth > 0:
                path_str = " → ".join(act.path[:5])
                lines.append(f"  联想路径: {path_str}")

        return "\n".join(lines)

    # ── 图的统计和查询 ────────────────────────────────────

    def get_strongest_connections(self, node_id: str, top_k: int = 5) -> list[dict]:
        """获取某节点最强的连接"""
        neighbors = self.get_neighbors(node_id)
        scored = []
        for neighbor_id, edge in neighbors:
            scored.append({
                "node": neighbor_id,
                "label": self._nodes[neighbor_id].label if neighbor_id in self._nodes else neighbor_id,
                "edge_type": edge.edge_type,
                "weight": round(edge.time_decay(), 3),
                "count": edge.activation_count,
            })
        scored.sort(key=lambda x: x["weight"], reverse=True)
        return scored[:top_k]

    def get_most_activated_nodes(self, top_k: int = 10) -> list[dict]:
        """获取当前最活跃的节点"""
        nodes = sorted(self._nodes.values(), key=lambda n: n.current_activation(), reverse=True)
        return [
            {
                "id": n.id,
                "label": n.label,
                "type": n.node_type,
                "activation": round(n.current_activation(), 3),
                "count": n.activation_count,
            }
            for n in nodes[:top_k]
        ]

    def get_stats(self) -> dict:
        """统计信息"""
        return {
            "nodes_count": len(self._nodes),
            "edges_count": len(self._edges),
            "node_types": self._count_types(self._nodes.values(), "node_type"),
            "edge_types": self._count_types(self._edges.values(), "edge_type"),
            **self._stats,
            "most_activated": self.get_most_activated_nodes(5),
        }

    def _count_types(self, items, attr: str) -> dict:
        counts = {}
        for item in items:
            t = getattr(item, attr, "unknown")
            counts[t] = counts.get(t, 0) + 1
        return counts

    # ── 持久化 ────────────────────────────────────────────

    def save(self):
        """保存到 JSON"""
        if not self._persist_path:
            return
        try:
            data = {
                "nodes": {k: {
                    "id": v.id, "type": v.node_type, "label": v.label,
                    "content": v.content, "created_at": v.created_at,
                    "last_activated": v.last_activated, "count": v.activation_count,
                    "base_activation": v.base_activation, "metadata": v.metadata,
                } for k, v in self._nodes.items()},
                "edges": {k: {
                    "source": v.source, "target": v.target, "type": v.edge_type,
                    "weight": v.weight, "created_at": v.created_at,
                    "last_activated": v.last_activated, "count": v.activation_count,
                    "decay_rate": v.decay_rate,
                } for k, v in self._edges.items()},
            }
            atomic_write_json(str(self._persist_path), data)
            logger.info("活体图谱已保存: %d 节点, %d 边", len(self._nodes), len(self._edges))
        except Exception as e:
            logger.warning("保存活体图谱失败: %s", e)

    def _load(self):
        """从 JSON 加载"""
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for nid, nd in data.get("nodes", {}).items():
                self._nodes[nid] = GraphNode(
                    id=nd["id"], node_type=nd["type"], label=nd["label"],
                    content=nd.get("content", ""), created_at=nd.get("created_at", 0),
                    last_activated=nd.get("last_activated", 0),
                    activation_count=nd.get("count", 0),
                    base_activation=nd.get("base_activation", 0.5),
                    metadata=nd.get("metadata", {}),
                )

            for eid, ed in data.get("edges", {}).items():
                edge = GraphEdge(
                    source=ed["source"], target=ed["target"], edge_type=ed["type"],
                    weight=ed["weight"], created_at=ed.get("created_at", 0),
                    last_activated=ed.get("last_activated", 0),
                    activation_count=ed.get("count", 0),
                    decay_rate=ed.get("decay_rate", 0.05),
                )
                self._edges[eid] = edge
                self._adjacency[edge.source].append(edge.target)

            logger.info("活体图谱已加载: %d 节点, %d 边", len(self._nodes), len(self._edges))
        except Exception as e:
            logger.warning("加载活体图谱失败: %s", e)
