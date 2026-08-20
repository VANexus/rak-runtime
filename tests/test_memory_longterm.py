"""超长期记忆测试 — 幂等 / FTS5 / 渐进披露 / scope 隔离 / 图扩散 / 整合"""

import os

import pytest

from src.core.memory_longterm import SuperMemory


@pytest.fixture
def mem(tmp_path):
    return SuperMemory(db_path=str(tmp_path / "super_long.db"))


class TestIdempotentWrite:
    def test_same_content_deduped(self, mem):
        a = mem.remember("用户喜欢把灯调到 50%", "semantic", scope="u1")
        b = mem.remember("用户喜欢把灯调到 50%", "semantic", scope="u1")
        assert a == b  # 幂等：同内容返回同一 id
        assert mem.stats()["total_memories"] == 1
        assert mem.stats()["deduped_writes"] == 1

    def test_importance_merged_up(self, mem):
        mem.remember("Rak 会挥手", "semantic", scope="u1", importance=0.4)
        mem.remember("Rak 会挥手", "semantic", scope="u1", importance=0.9)
        hits = mem.recall("Rak 会挥手", scope="u1")
        assert hits
        row = mem.recall_full(hits[0].id)
        assert row["importance"] == 0.9  # 取更高 importance

    def test_scope_isolated(self, mem):
        mem.remember("客厅的灯坏了", "episodic", scope="u1")
        mem.remember("客厅的灯坏了", "episodic", scope="u2")
        assert mem.stats()["total_memories"] == 2  # 不同 scope 不算重复
        assert len(mem.recall("客厅的灯", scope="u1")) == 1
        assert len(mem.recall("客厅的灯", scope="u2")) == 1


class TestRecall:
    def test_progressive_disclosure_snippet(self, mem):
        long_content = "用户上周买了一个智能音箱，放在客厅，喜欢在晚上用语音控制播放音乐。"
        mem.remember(long_content, "episodic", scope="u1", importance=0.7)
        hits = mem.recall("智能音箱 音乐", scope="u1")
        assert hits
        # L1 紧凑：片段不超长
        assert len(hits[0].content) <= 120

    def test_recall_full(self, mem):
        mem.remember("用户偏好详细回答", "semantic", scope="u1")
        hits = mem.recall("偏好 回答", scope="u1")
        full = mem.recall_full(hits[0].id)
        assert full["content"] == "用户偏好详细回答"

    def test_type_filter(self, mem):
        mem.remember("开关门", "procedural", scope="u1")
        mem.remember("昨天家里停电了", "episodic", scope="u1")
        hits = mem.recall("开关门", scope="u1", memory_types=["procedural"])
        assert all(h.memory_type == "procedural" for h in hits)

    def test_recall_access_increments(self, mem):
        mem.remember("记得在 22:00 锁门", "semantic", scope="u1")
        hits = mem.recall("锁门", scope="u1")
        before = hits[0].access_count
        hits2 = mem.recall("锁门", scope="u1")
        assert hits2[0].access_count == before + 1

    def test_recall_bigram_paraphrase(self, mem):
        """无空格中文短语变体也应召回（bigram 扩展通道）"""
        mem.remember("门锁在 22:00 自动锁定", "semantic", scope="u1")
        hits = mem.recall("22点锁门", scope="u1")
        assert any("22" in h.content for h in hits)


class TestRecallRelated:
    """语义相关召回（泛化通道）— 词法命中为空时按结构化 goal / 标题锚点召回。

    设计：对比"短而密"的语义锚点（metadata['goal'] 或内容首行标题），
    双守卫卡精度——min_shared>=2 结构门槛 + min_overlap 复合分门槛，
    避免长内容稀释（capstone『回调阈值破坏精度契约』教训）。
    """

    def _wf_mem(self, mem, goal, importance=0.8):
        """写入一条工作流样式记忆（带结构化 goal）"""
        return mem.remember(
            f"工作流『{goal}』完成（completed，1 轮）：\n- 查询: 结果\n- 执行: 结果",
            "procedural", scope="workflow", importance=importance,
            metadata={"type": "workflow", "goal": goal, "status": "completed"},
        )

    def test_goal_field_semantic_match(self, mem):
        """改写相关目标应召回：『把灯光调亮方便看书』→ 先例『让灯亮起来』"""
        mid = self._wf_mem(mem, "让灯亮起来")
        hits = mem.recall_related("把灯光调亮方便看书", scope="workflow", top_k=5)
        assert any(h.id == mid for h in hits)

    def test_title_anchor_fallback(self, mem, tmp_path):
        """无结构化 goal 的记忆，回退内容首行标题锚点也能召回"""
        mem.remember(
            "工作流『给客厅换新灯泡』完成：\n- 下单: 已买\n- 安装: 完成",
            "procedural", scope="workflow",
        )
        hits = mem.recall_related("换一下客厅的灯泡", scope="workflow", top_k=5)
        assert any("换新灯泡" in h.content for h in hits)

    def test_unrelated_returns_empty(self, mem):
        """无关目标应返回空（精度契约）：话题不相关不召回"""
        self._wf_mem(mem, "让灯亮起来")
        hits = mem.recall_related("今天天气怎么样", scope="workflow", top_k=5)
        assert all("让灯亮起来" not in h.content for h in hits)

    def test_single_char_overlap_rejected(self, mem):
        """仅 1 个共享字（语义未接地）应被 min_shared 门槛拒绝"""
        self._wf_mem(mem, "让灯亮起来")
        # 与『让灯亮起来』仅共享『起』1 字（无灯/亮），判定无关
        hits = mem.recall_related("打开起居室的照明", scope="workflow", top_k=5)
        assert all("让灯亮起来" not in h.content for h in hits)

    def test_scope_isolated(self, mem):
        """跨 scope 不串：workflow 记忆不因别的 scope 的无关查询被召回"""
        self._wf_mem(mem, "让灯亮起来")
        hits = mem.recall_related("把灯光调亮方便看书", scope="other", top_k=5)
        assert all("让灯亮起来" not in h.content for h in hits)



    def test_auto_link_similar(self, mem):
        mem.remember("用户喜欢在晚上听音乐", "semantic", scope="u1")
        mem.remember("用户喜欢晚上听音乐", "semantic", scope="u1")
        assert mem.stats()["total_links"] >= 1

    def test_graph_diffusion(self, mem):
        a = mem.remember("灯", "semantic", scope="u1")
        b = mem.remember("卧室", "semantic", scope="u1")
        c = mem.remember("卧室里的灯", "semantic", scope="u1")
        mem.link(a, b, weight=0.9)
        mem.link(b, c, weight=0.8)
        # 从 a 扩散，应触达 b、c
        hits = mem.recall_by_graph([a], top_k=5)
        ids = {h.id for h in hits}
        assert b in ids and c in ids


class TestConsolidateForget:
    def test_consolidate_merges_near_duplicates(self, mem):
        mem.remember("用户喜欢在晚上听音乐", "semantic", scope="u1", importance=0.5)
        mem.remember("用户喜欢晚上听音乐", "semantic", scope="u1", importance=0.8)
        before = mem.stats()["total_memories"]
        merged = mem.consolidate(sim_threshold=0.5)
        assert merged >= 1
        assert mem.stats()["total_memories"] < before

    def test_forget_prunes_old_low_importance(self, mem):
        import time
        mem.remember("临时记录", "episodic", scope="u1", importance=0.01)
        # 直接改 created_at 到 30 天前
        mem._conn.execute(
            "UPDATE memories SET created_at=? WHERE content LIKE '%临时记录%'",
            (time.time() - 30 * 86400,),
        )
        mem._conn.commit()
        n = mem.forget(min_salience=0.05, older_than_days=14)
        assert n >= 1
