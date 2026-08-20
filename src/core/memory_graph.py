"""
情景记忆图谱（Memory-as-Graph）- 超长期记忆的图查询层。

定位：SuperMemory（src.core.memory_longterm）是"存储层"（幂等写入 + FTS 召回 +
memory_links 持久化）；本模块是其上的"图查询层"，把超长期记忆当作情景知识图谱来用：

1. index        把一条记忆注册为图节点（内存邻接覆盖层 overlay）
2. link         记忆↔记忆建边（内存 overlay + 委托 SuperMemory.link 持久化）
3. query        多跳召回：SuperMemory 关键词召回种子 -> 沿边扩展 -> 带路径排序返回
4. paths        任意两节点间的简单路径发现（BFS/DFS）
5. get_stats    图统计（节点/边/平均度/连通分量）

设计原则（与全仓一致）：
- 不重复造存储 -- 节点内容、持久化、全文检索全部委托 SuperMemory；
  本模块只维护一份轻量邻接覆盖层（可选用 JSON 持久化）。
- 优雅降级 -- super_mem 为 None 或任何外部异常时退化为 no-op，永不抛出。
- 懒加载单例 -- get_memory_graph() 对齐 decision_engine 的 _get_* 模式。

排序公式（query 的邻居节点）：
  score = importance + (Σ edge_weight_i * HOP_DECAY ** (i-1)) / hop数
即 importance 越高、离种子越近、边越强的记忆排得越靠前（路径越深衰减越狠）。
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from src.core.memory_longterm import SuperMemory, get_super_memory

logger = logging.getLogger(__name__)

# 逐跳边权衰减系数：每多一跳，该跳边贡献减半（模拟图扩散激活的能量损失）
HOP_DECAY = 0.5

# 路径发现的简单路径数量上限（防御性，避免稠密图爆炸）
MAX_PATHS = 128


# ========== 数据结构 ==========

@dataclass
class GraphRecall:
  """一次图谱召回结果（含从种子到该节点的路径链）"""
  id: str
  content: str
  memory_type: str
  scope: str = "default"
  importance: float = 0.5
  score: float = 0.0
  path: List[str] = field(default_factory=list)  # id 链：种子 -> ... -> 本节点

  def to_dict(self) -> dict:
    return asdict(self)


# ========== 情景记忆图谱 ==========

class MemoryGraph:
  """
  超长期记忆的图查询层。

  - 节点：注册进来的记忆 id（内容/元数据仍以 SuperMemory 为唯一事实源）
  - 边：self._adjacency 内存覆盖层（双向索引），持久化委托 SuperMemory.link
  - super_mem 为 None 时全部操作退化为 no-op（降级，不抛异常）
  """

  def __init__(self, super_mem: Optional[SuperMemory] = None,
               persist_path: Optional[str] = None):
    self._super_mem = super_mem
    self._persist_path = persist_path
    self._lock = threading.RLock()
    # id -> {content, scope, memory_type, importance, tags, entities}
    self._nodes: Dict[str, dict] = {}
    # id -> {邻居id -> {"relation": str, "weight": float}}（双向对称存储）
    self._adjacency: Dict[str, Dict[str, dict]] = {}
    if persist_path:
      self._load()

  # ── 可用性 ──────────────────────────────────────────────

  @property
  def _available(self) -> bool:
    """super_mem 缺失时整图退化为 no-op"""
    return self._super_mem is not None

  # ── 节点注册 ────────────────────────────────────────────

  def index(self, mem_id: str, content: str, scope: str = "default",
            tags: Optional[List[str]] = None) -> None:
    """
    把一条记忆注册为图节点（幂等：重复 index 只刷新元数据）。

    可选地从 SuperMemory 补全 memory_type / importance；提取的实体仅作为
    节点元数据保存，供调试与后续联想使用。
    """
    if not self._available or not mem_id or not content:
      return
    node = {
      "content": content,
      "scope": scope,
      "memory_type": "episodic",
      "importance": 0.5,
      "tags": list(tags or []),
      "entities": self._extract_entities(content),
    }
    # 从 SuperMemory 补全元数据（失败静默，用默认值）
    try:
      full = self._super_mem.recall_full(mem_id)
      if full:
        node["memory_type"] = full.get("memory_type", "episodic")
        node["importance"] = float(full.get("importance", 0.5))
        node["scope"] = full.get("scope", scope)
    except Exception as e:
      logger.debug("[MemoryGraph] 补全节点元数据失败 %s: %s", mem_id, e)

    with self._lock:
      self._nodes[mem_id] = node
      self._adjacency.setdefault(mem_id, {})
    self._save()

  # ── 边 ──────────────────────────────────────────────────

  def link(self, a_id: str, b_id: str, relation: str = "related",
           weight: float = 0.5) -> None:
    """
    记忆↔记忆建边：写入内存覆盖层，并委托 SuperMemory.link 持久化。
    幂等：重复建边只抬高权重（与 SuperMemory.link 语义一致）。
    """
    if not self._available or not a_id or not b_id or a_id == b_id:
      return
    with self._lock:
      self._adjacency.setdefault(a_id, {})
      self._adjacency.setdefault(b_id, {})
      old = self._adjacency[a_id].get(b_id)
      w = weight if old is None else max(old["weight"], weight)
      edge = {"relation": relation, "weight": w}
      # 双向对称存储，便于无向遍历
      self._adjacency[a_id][b_id] = edge
      self._adjacency[b_id][a_id] = edge
    try:
      self._super_mem.link(a_id, b_id, relation=relation, weight=weight)
    except Exception as e:
      logger.warning("[MemoryGraph] 委托 SuperMemory 建边失败 %s->%s: %s",
                     a_id, b_id, e)
    self._save()

  def neighbors(self, mem_id: str) -> List[dict]:
    """一跳邻居：[{id, content, relation, weight}]，来自内存覆盖层"""
    if not self._available or not mem_id:
      return []
    with self._lock:
      adj = dict(self._adjacency.get(mem_id, {}))
    out = []
    for nid, edge in adj.items():
      out.append({
        "id": nid,
        "content": self._node_content(nid),
        "relation": edge.get("relation", "related"),
        "weight": edge.get("weight", 0.5),
      })
    return out

  # ── 多跳召回 ────────────────────────────────────────────

  def query(self, query: str, scope: str = "default", top_k: int = 5,
            hops: int = 2) -> List[GraphRecall]:
    """
    多跳召回：SuperMemory 关键词召回作为种子 -> 沿邻接边扩展最多 hops 跳。

    返回排序：种子在前（按 SuperMemory 召回分），邻居在后
    （按 importance + 边权逐跳衰减得分）。path 为种子到该节点的 id 链。
    """
    if not self._available or not query or not query.strip():
      return []
    try:
      seeds = self._super_mem.recall(query, scope=scope, top_k=top_k) or []
    except Exception as e:
      logger.warning("[MemoryGraph] 种子召回失败，退化为空结果: %s", e)
      return []

    # 词法命中不足时的语义回退：用 recall_related 对结构化 goal/标题锚点做语义匹配，
    # 让改写相关目标（回顾『让灯亮起来』vs『把灯光调亮方便看书』）也能入图扩散。
    if not seeds:
      try:
        seeds = self._super_mem.recall_related(query, scope=scope, top_k=top_k) or []
      except Exception as e:
        logger.debug("[MemoryGraph] 语义相关种子召回失败（维持空结果）: %s", e)

    if not seeds:
      return []

    # 1) 种子节点：path 长度为 1，分数沿用召回分
    results: Dict[str, GraphRecall] = {}
    for hit in seeds:
      results[hit.id] = GraphRecall(
        id=hit.id, content=hit.content, memory_type=hit.memory_type,
        scope=hit.scope, importance=hit.importance,
        score=float(hit.score), path=[hit.id],
      )

    # 2) BFS 逐跳扩展：能量 = Σ 边权 * 逐跳衰减（更浅路径优先，同深更高分胜出）
    expanded: Dict[str, GraphRecall] = {}
    depth: Dict[str, int] = {}
    for seed in seeds:
      # (节点, 路径, 折扣边权累计)
      frontier = [(seed.id, [seed.id], 0.0)]
      for hop in range(1, max(1, hops) + 1):
        next_frontier = []
        for nid, path, acc in frontier:
          with self._lock:
            adj = dict(self._adjacency.get(nid, {}))
          for nb, edge in adj.items():
            if nb in results:      # 种子不重复进入邻居区
              continue
            w = float(edge.get("weight", 0.5))
            nb_acc = acc + w * (HOP_DECAY ** (hop - 1))
            nb_path = path + [nb]
            prev = expanded.get(nb)
            prev_depth = depth.get(nb, 1 << 30)
            if prev is None or prev_depth > hop or \
                (prev_depth == hop and nb_acc > prev.score):
              # 首次到达 / 更浅路径 / 同深更强：更新记录并继续向外扩散
              depth[nb] = hop
              expanded[nb] = GraphRecall(
                id=nb, content=self._node_content(nb),
                memory_type=self._node_type(nb), scope=scope,
                importance=self._node_importance(nb),
                score=nb_acc, path=nb_path,   # score 暂存累计边权，下面统一换算
              )
              next_frontier.append((nb, nb_path, nb_acc))
        frontier = next_frontier
        if not frontier:
          break

    # 最终得分 = importance + 平均折扣边权（路径越长衰减越狠，离种子越近越靠前）
    for rec in expanded.values():
      d = max(1, depth.get(rec.id, 1))
      rec.score = round(rec.importance + rec.score / d, 4)

    seed_list = sorted(
      (r for r in results.values()),
      key=lambda r: r.score, reverse=True,
    )
    neighbor_list = sorted(expanded.values(), key=lambda r: r.score, reverse=True)
    return seed_list + neighbor_list[: max(0, top_k)]

  # ── 路径发现 ────────────────────────────────────────────

  def paths(self, from_id: str, to_id: str, max_len: int = 4) -> List[List[str]]:
    """任意两节点间的全部简单路径（含端点，长度 <= max_len），DFS 回溯枚举"""
    if not self._available or not from_id or not to_id:
      return []
    if from_id == to_id:
      return [[from_id]]
    max_len = max(2, max_len)
    found: List[List[str]] = []

    def _dfs(node: str, visited: set, trail: List[str]):
      if len(found) >= MAX_PATHS:
        return
      if node == to_id:
        found.append(list(trail))
        return
      if len(trail) >= max_len:
        return
      with self._lock:
        adj = dict(self._adjacency.get(node, {}))
      for nb in adj:
        if nb in visited:
          continue
        visited.add(nb)
        trail.append(nb)
        _dfs(nb, visited, trail)
        trail.pop()
        visited.discard(nb)

    _dfs(from_id, {from_id}, [from_id])
    return found

  def shortest_path(self, from_id: str, to_id: str) -> Optional[List[str]]:
    """BFS 最短跳路径；不可达返回 None"""
    if not self._available or not from_id or not to_id:
      return None
    if from_id == to_id:
      return [from_id]
    visited = {from_id}
    queue = deque([(from_id, [from_id])])
    while queue:
      nid, path = queue.popleft()
      with self._lock:
        adj = self._adjacency.get(nid, {})
      for nb in adj:
        if nb in visited:
          continue
        if nb == to_id:
          return path + [nb]
        visited.add(nb)
        queue.append((nb, path + [nb]))
    return None

  # ── 统计 ────────────────────────────────────────────────

  def get_stats(self) -> dict:
    """图统计：节点数/边数/平均度/连通分量数（对邻接覆盖层做 BFS）"""
    if not self._available:
      return {
        "available": False, "nodes": 0, "edges": 0,
        "avg_degree": 0.0, "components": 0,
      }
    with self._lock:
      node_ids = set(self._nodes) | set(self._adjacency)
      edge_count = sum(len(nbrs) for nbrs in self._adjacency.values()) // 2

    # 连通分量计数（无向 BFS）
    visited = set()
    components = 0
    for start in node_ids:
      if start in visited:
        continue
      components += 1
      queue = deque([start])
      visited.add(start)
      while queue:
        nid = queue.popleft()
        with self._lock:
          adj = self._adjacency.get(nid, {})
        for nb in adj:
          if nb not in visited:
            visited.add(nb)
            queue.append(nb)

    avg_degree = round(2.0 * edge_count / len(node_ids), 3) if node_ids else 0.0
    return {
      "available": True,
      "nodes": len(node_ids),
      "edges": edge_count,
      "avg_degree": avg_degree,
      "components": components,
    }

  # ── 内部工具 ────────────────────────────────────────────

  def _node_content(self, mem_id: str) -> str:
    """取节点内容：优先覆盖层缓存，缺失时回查 SuperMemory（失败返回空串）"""
    with self._lock:
      node = self._nodes.get(mem_id)
    if node:
      return node.get("content", "")
    try:
      full = self._super_mem.recall_full(mem_id)
      if full:
        return str(full.get("content", ""))[:120]
    except Exception:
      pass
    return ""

  def _node_importance(self, mem_id: str) -> float:
    with self._lock:
      node = self._nodes.get(mem_id)
    if node:
      return float(node.get("importance", 0.5))
    try:
      full = self._super_mem.recall_full(mem_id)
      if full:
        return float(full.get("importance", 0.5))
    except Exception:
      pass
    return 0.5

  def _node_type(self, mem_id: str) -> str:
    with self._lock:
      node = self._nodes.get(mem_id)
    return node.get("memory_type", "episodic") if node else "episodic"

  @staticmethod
  def _extract_entities(text: str) -> List[str]:
    """
    轻量实体提取：复用 LivingGraph._extract_entities（纯内存实例，无副作用）。
    导入失败时退化为朴素分词，永不抛异常。
    """
    try:
      from src.core.living_graph import LivingGraph
      return LivingGraph()._extract_entities(text)
    except Exception:
      try:
        return [w for w in text.replace("，", " ").replace("。", " ").split()
                if len(w) >= 2][:8]
      except Exception:
        return []

  # ── 覆盖层持久化（可选 JSON 快照） ──────────────────────

  def _save(self) -> None:
    """把邻接覆盖层原子写入 JSON（仅 persist_path 设置时；失败静默）"""
    if not self._persist_path:
      return
    try:
      from src.core._utils import atomic_write_json
      with self._lock:
        nodes = {mid: {
          "content": n.get("content", ""),
          "scope": n.get("scope", "default"),
          "memory_type": n.get("memory_type", "episodic"),
          "importance": n.get("importance", 0.5),
          "tags": n.get("tags", []),
        } for mid, n in self._nodes.items()}
        edges = []
        seen = set()
        for a, nbrs in self._adjacency.items():
          for b, e in nbrs.items():
            key = tuple(sorted((a, b)))
            if key in seen:
              continue
            seen.add(key)
            edges.append({
              "a": a, "b": b,
              "relation": e.get("relation", "related"),
              "weight": e.get("weight", 0.5),
            })
      atomic_write_json(self._persist_path, {"nodes": nodes, "edges": edges})
    except Exception as e:
      logger.debug("[MemoryGraph] 覆盖层持久化失败: %s", e)

  def _load(self) -> None:
    """从 JSON 快照恢复覆盖层（文件缺失/损坏时静默从空图开始）"""
    try:
      import json
      import os
      if not os.path.exists(self._persist_path):
        return
      with open(self._persist_path, "r", encoding="utf-8") as f:
        data = json.load(f)
      with self._lock:
        for mid, n in (data.get("nodes") or {}).items():
          self._nodes[mid] = {
            "content": n.get("content", ""),
            "scope": n.get("scope", "default"),
            "memory_type": n.get("memory_type", "episodic"),
            "importance": float(n.get("importance", 0.5)),
            "tags": list(n.get("tags", [])),
            "entities": [],
          }
          self._adjacency.setdefault(mid, {})
        for e in (data.get("edges") or []):
          a, b = e.get("a"), e.get("b")
          if not a or not b or a == b:
            continue
          edge = {"relation": e.get("relation", "related"),
                  "weight": float(e.get("weight", 0.5))}
          self._adjacency.setdefault(a, {})[b] = edge
          self._adjacency.setdefault(b, {})[a] = edge
      logger.info("[MemoryGraph] 覆盖层快照加载成功: %s", self._persist_path)
    except Exception as e:
      logger.warning("[MemoryGraph] 覆盖层快照加载失败（从空图开始）: %s", e)


# ========== 模块级单例（对齐 decision_engine 的 _get_* 模式） ==========

_instance: Optional[MemoryGraph] = None
_init_lock = threading.Lock()


def get_memory_graph() -> Optional[MemoryGraph]:
  """
  懒加载单例：super_mem 取 get_super_memory()（其自身可能返回 None，
  此时单例仍创建但整体降级为 no-op）。初始化异常时标记 False 永久不可用。
  """
  global _instance
  if _instance is not None:
    return _instance if _instance is not False else None
  with _init_lock:
    if _instance is None:
      try:
        _instance = MemoryGraph(super_mem=get_super_memory())
        logger.info("[MemoryGraph] 情景记忆图谱初始化成功")
      except Exception:
        logger.exception("[MemoryGraph] 情景记忆图谱初始化失败，永久禁用")
        _instance = False
  return _instance if _instance is not False else None
