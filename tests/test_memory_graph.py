"""
MemoryGraph（情景记忆图谱）单元测试。

不访问网络、不访问真实 LLM -- SuperMemory 用临时目录的 SQLite 实例，
实体提取用的 LivingGraph 是纯内存实例，全链路本地运行。
"""

import pytest

from src.core.memory_longterm import SuperMemory
from src.core.memory_graph import MemoryGraph, GraphRecall, get_memory_graph


@pytest.fixture()
def sm(tmp_path):
  """临时 SuperMemory（独立 SQLite 文件，测试间互不污染）"""
  mem = SuperMemory(db_path=str(tmp_path / "sm.db"))
  yield mem
  mem.close()


@pytest.fixture()
def graph(sm):
  """挂在临时 SuperMemory 之上的 MemoryGraph"""
  return MemoryGraph(super_mem=sm)


# ── 节点注册与种子召回 ────────────────────────────────────

def test_index_and_query_seed(sm, graph):
  """种子召回：命中记忆 path 长度为 1，且 id 全部来自已写入的记忆"""
  ids = [
    sm.remember("开灯成功，客厅亮了"),
    sm.remember("开灯以后房间温度升高"),
    sm.remember("开灯失败请检查电路"),
  ]
  contents = ["开灯成功，客厅亮了", "开灯以后房间温度升高", "开灯失败请检查电路"]
  for mid, c in zip(ids, contents):
    graph.index(mid, content=c)

  results = graph.query("开灯", top_k=5, hops=2)

  assert len(results) >= 1
  for r in results:
    assert isinstance(r, GraphRecall)
    assert r.path == [r.id]          # 种子：路径长度 1
    assert r.id in ids
    assert "开灯" in r.content
  # 三条都含"开灯"，应全部被召回为种子
  assert {r.id for r in results} == set(ids)
  # 种子在前：第一条的 path 就是自身
  assert results[0].path == [results[0].id]


# ── 多跳扩展 ──────────────────────────────────────────────

def test_multihop_expansion(sm, graph):
  """链 A(灯) -> B(卧室) -> C：查询"灯"经多跳浮出 C，path 为 id 链"""
  a = sm.remember("打开客厅的灯")            # 种子（含"灯"）
  b = sm.remember("卧室需要安静的休息氛围")   # 一跳邻居（不含"灯"）
  c = sm.remember("睡前调暗床头光源帮助入睡")  # 二跳邻居（不含"灯"）
  graph.index(a, content="打开客厅的灯")
  graph.index(b, content="卧室需要安静的休息氛围")
  graph.index(c, content="睡前调暗床头光源帮助入睡")
  graph.link(a, b, relation="related", weight=0.8)
  graph.link(b, c, relation="related", weight=0.8)

  results = graph.query("灯", top_k=5, hops=2)
  by_id = {r.id: r for r in results}

  # 种子 A 在结果里，路径长度 1
  assert a in by_id
  assert by_id[a].path == [a]
  # 一跳邻居 B 通过图扩展浮出，路径 [A, B]
  assert b in by_id
  assert by_id[b].path == [a, b]
  # 二跳邻居 C 通过多跳扩展浮出，路径 [A, B, C]
  assert c in by_id
  assert by_id[c].path == [a, b, c]
  # 种子排在邻居前面
  assert results[0].id == a
  # 邻居按分数降序：B（一跳）应排在 C（二跳）之前
  idx_b = [r.id for r in results].index(b)
  idx_c = [r.id for r in results].index(c)
  assert idx_b < idx_c


# ── 路径发现 ──────────────────────────────────────────────

def test_path_discovery(sm, graph):
  """BFS/DFS 路径发现：A-B-C-D 链 + A-D 直连边，返回全部简单路径"""
  ids = {
    "a": sm.remember("路径测试节点甲：打开客厅的灯"),
    "b": sm.remember("路径测试节点乙：卧室的布局"),
    "c": sm.remember("路径测试节点丙：窗帘控制"),
    "d": sm.remember("路径测试节点丁：晚安场景"),
  }
  for key in ("a", "b", "c", "d"):
    graph.index(ids[key], content=f"节点{key}")
  graph.link(ids["a"], ids["b"])
  graph.link(ids["b"], ids["c"])
  graph.link(ids["c"], ids["d"])
  graph.link(ids["a"], ids["d"])  # 直连捷径

  found = graph.paths(ids["a"], ids["d"], max_len=4)
  found_set = {tuple(p) for p in found}

  assert tuple([ids["a"], ids["d"]]) in found_set          # 直连
  assert tuple([ids["a"], ids["b"], ids["c"], ids["d"]]) in found_set  # 绕行链
  assert all(len(p) <= 4 for p in found)                   # 尊重 max_len
  # 每条路径首尾正确且无重复节点（简单路径）
  for p in found:
    assert p[0] == ids["a"] and p[-1] == ids["d"]
    assert len(set(p)) == len(p)

  # 图统计：4 节点 4 边、单连通分量
  stats = graph.get_stats()
  assert stats["nodes"] == 4
  assert stats["edges"] == 4
  assert stats["components"] == 1
  assert stats["avg_degree"] == 2.0


def test_shortest_path(sm, graph):
  """最短路径：有直连边时返回两跳以内的最小路径，不可达返回 None"""
  ids = {
    "a": sm.remember("最短路测试甲"),
    "b": sm.remember("最短路测试乙"),
    "c": sm.remember("最短路测试丙"),
    "x": sm.remember("孤立节点不与任何记忆相连"),
  }
  for key in ("a", "b", "c", "x"):
    graph.index(ids[key], content=f"节点{key}")
  graph.link(ids["a"], ids["b"])
  graph.link(ids["b"], ids["c"])

  # a -> c 的最短路是 [a, b, c]（无直连边）
  assert graph.shortest_path(ids["a"], ids["c"]) == [ids["a"], ids["b"], ids["c"]]
  # 自身到自身
  assert graph.shortest_path(ids["a"], ids["a"]) == [ids["a"]]
  # x 与主链不连通
  assert graph.shortest_path(ids["a"], ids["x"]) is None


# ── 持久化委托 ────────────────────────────────────────────

def test_links_persist_via_super_memory(sm, graph):
  """graph.link() 委托 SuperMemory 持久化：memory_links 总数增加"""
  m1 = sm.remember("持久化验证：今天修好了门锁")
  m2 = sm.remember("持久化验证：明天要买牛奶")
  before = sm.stats()["total_links"]

  graph.link(m1, m2, relation="related", weight=0.9)

  after = sm.stats()["total_links"]
  assert after > before
  # 覆盖层里也能查到这条边
  nbrs = graph.neighbors(m1)
  assert any(n["id"] == m2 and n["weight"] == 0.9 for n in nbrs)


# ── 降级 ──────────────────────────────────────────────────

def test_degradation_no_super_memory(tmp_path):
  """super_mem=None：全部操作 no-op，返回空/None，绝不抛异常"""
  g = MemoryGraph(super_mem=None, persist_path=str(tmp_path / "overlay.json"))

  g.index("mem_x", content="任意内容")           # no-op
  g.link("mem_x", "mem_y")                       # no-op

  assert g.query("开灯") == []
  assert g.neighbors("mem_x") == []
  assert g.paths("mem_x", "mem_y") == []
  assert g.shortest_path("mem_x", "mem_y") is None
  stats = g.get_stats()
  assert stats["nodes"] == 0 and stats["edges"] == 0
  assert stats["components"] == 0


def test_singleton_degrades_when_no_super_memory(monkeypatch):
  """单例：get_super_memory 返回 None 时，单例创建但整体降级为 no-op"""
  import src.core.memory_graph as mg
  monkeypatch.setattr(mg, "get_super_memory", lambda: None)
  mg._instance = None  # 重置单例后重新获取
  g = mg.get_memory_graph()
  try:
    assert g is not None
    assert g.query("任何查询") == []
    assert g.shortest_path("a", "b") is None
  finally:
    mg._instance = None  # 还原全局单例，避免污染其它测试


# ── 语义种子回退（capstone 泛化缺口闭合） ─────────────────

def test_query_semantic_seed_fallback(sm, graph):
  """词法命中为空时，MemoryGraph.query 回退 recall_related，让改写相关目标也能召回。

  场景：只写入工作流样式先例『让灯亮起来』（带结构化 goal），查询改写目标
  『把灯光调亮方便看书』——词法 recall 返回空，语义回退通道浮出先例。
  """
  mid = sm.remember(
    "工作流『让灯亮起来』完成（completed，1 轮）：\n- 查询: 结果\n- 执行: 结果",
    "procedural", scope="workflow", importance=0.8,
    metadata={"type": "workflow", "goal": "让灯亮起来", "status": "completed"},
  )
  graph.index(mid, content="工作流『让灯亮起来』完成", scope="workflow")

  # 词法路径确认：真的会空（触发回退的前提）
  assert sm.recall("把灯光调亮方便看书", scope="workflow") == []

  results = graph.query("把灯光调亮方便看书", scope="workflow", top_k=5, hops=2)
  assert any(r.id == mid for r in results)

  # 无关目标：即使回退到语义通道也精确返回空
  unrelated = graph.query("今天天气怎么样", scope="workflow", top_k=5, hops=2)
  assert all(r.id != mid for r in unrelated)
