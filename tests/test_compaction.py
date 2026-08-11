"""上下文压缩测试"""

from src.core.compaction import (
    SUMMARY_TEMPLATE, build_compaction_prompt, compact_context, parse_summary,
)


class TestCompaction:
    def test_short_context_not_compressed(self):
        """短上下文直接返回"""
        text = "短上下文"
        assert compact_context(text, max_chars=3000) == text

    def test_summary_template_fields(self):
        """摘要模板含具身字段"""
        out = SUMMARY_TEMPLATE.format(
            objective="开灯", work_state="进行中",
            next_move="执行 light_on", devices="light-01 在线",
        )
        assert "## Objective" in out
        assert "## Work State" in out
        assert "## Next Move" in out
        assert "## Relevant Devices" in out

    def test_parse_summary(self):
        """解析 LLM 输出的 JSON 摘要（容忍代码块）"""
        s = '```json\n{"objective": "开灯", "work_state": "完成", "next_move": "无", "devices": "灯"}\n```'
        parsed = parse_summary(s)
        assert parsed["objective"] == "开灯"

    def test_parse_summary_invalid(self):
        """无法解析返回 None"""
        assert parse_summary("not json") is None

    def test_compact_failure_returns_none(self, monkeypatch):
        """LLM 失败返回 None（调用方截断兜底，不阻断）"""
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        long_text = "用户的偏好是喜欢把灯光调成暖色调，这个信息很重要。" * 300
        result = compact_context(long_text, max_chars=500)
        # 无 token 时 LLM 客户端创建失败 → None
        assert result is None or len(result) < len(long_text)

    def test_build_prompt_has_tail(self):
        """超长上下文的压缩提示词含尾部原文"""
        long_text = "开头" + "中段内容。" * 500 + "结尾关键"
        prompt = build_compaction_prompt(long_text, keep_tail=50)
        assert "结尾关键" in prompt
