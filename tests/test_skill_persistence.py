"""G12/G13 技能 SKILL.md 落盘 / 跨会话恢复 / 复用强化测试（独立 skills_dir，不污染线上 data/）"""

import os

from src.core.learning_loop import LearningLoop


def _feed(ll, action, queries):
    """喂 N 条同动作的成功记录，触发窗口内提取。"""
    for i, q in enumerate(queries):
        ll.on_decision(f"t-{action}-{i}", q,
                       {"action": action, "success": True, "confidence": 0.9}, True)


class TestSkillPersistence:
    def test_extract_persists_skill_file(self, tmp_path):
        """3 次成功 → 技能提取 + SKILL.md 落盘。"""
        skdir = str(tmp_path / "skills")
        ll = LearningLoop(skills_dir=skdir)
        _feed(ll, "nod", ["点个头", "点点头", "表示同意"])
        ll._maybe_extract_skills()
        assert "nod" in ll._skills
        assert os.path.exists(os.path.join(skdir, "nod.md"))

    def test_restore_across_instances(self, tmp_path):
        """新实例（模拟重启）应恢复已落盘技能。"""
        skdir = str(tmp_path / "skills")
        ll = LearningLoop(skills_dir=skdir)
        _feed(ll, "wave_hand", ["挥挥手", "招个手", "打招呼"])
        ll._maybe_extract_skills()

        ll2 = LearningLoop(skills_dir=skdir)
        assert "wave_hand" in ll2._skills
        assert ll2._skills["wave_hand"]["uses"] >= 3

    def test_reuse_strengthens_confidence(self, tmp_path):
        """再次 3 次成功（复用）应强化 confidence（上调至 0.9 上限）。"""
        skdir = str(tmp_path / "skills")
        ll = LearningLoop(skills_dir=skdir)
        _feed(ll, "nod", ["点个头", "点点头", "表示同意"])
        ll._maybe_extract_skills()
        base = ll._skills["nod"]["confidence"]  # 0.65

        ll2 = LearningLoop(skills_dir=skdir)  # 恢复
        _feed(ll2, "nod", ["再点头", "点一下头", "同意就点头"])
        ll2._maybe_extract_skills()
        assert ll2._skills["nod"]["confidence"] > base
        # 不越过 0.9 上限
        assert ll2._skills["nod"]["confidence"] <= 0.9

    def test_no_skill_with_few_successes(self, tmp_path):
        """成功少于 3 次不应提取技能。"""
        skdir = str(tmp_path / "skills")
        ll = LearningLoop(skills_dir=skdir)
        _feed(ll, "lock_open", ["开门", "把门打开"])  # 只有 2 次
        ll._maybe_extract_skills()
        assert "lock_open" not in ll._skills

    def test_skills_digest_format(self, tmp_path):
        """digest 可注入提示词（含技能名与置信度）。"""
        skdir = str(tmp_path / "skills")
        ll = LearningLoop(skills_dir=skdir)
        _feed(ll, "light_on", ["开灯", "把灯打开", "开一下灯"])
        ll._maybe_extract_skills()
        dig = ll.get_skills_digest()
        assert "我已学会的技能" in dig
        assert "light_on" in dig
        assert "置信度" in dig

    def test_digest_empty_when_no_skills(self, tmp_path):
        """无技能时 digest 为空串（不注入多余信号）。"""
        ll = LearningLoop(skills_dir=str(tmp_path / "empty"))
        assert ll.get_skills_digest() == ""
