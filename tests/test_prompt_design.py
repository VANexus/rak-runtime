"""内置提示词设计测试（docs/ai-native-runtime/09-prompts.md）"""

from src.core.agent_loop import build_agent_system_prompt
from src.core.prompt_engine import PromptEngine


class TestPromptTemplates:
    def test_decision_yaml_renders_sections(self):
        """decision.yaml 渲染出全部分区 + 生命感"""
        pe = PromptEngine()
        prompt = pe.build_system_prompt(
            available_actions=["light_on", "lock_open"],
            memory_context="## 记忆\n用户偏好",
            device_state="设备在线",
        )
        assert "## 你的能力边界" in prompt
        assert "## 记忆与经验" in prompt
        assert "## 决策规则" in prompt
        assert "## 生命感" in prompt
        assert "light_on" in prompt

    def test_decompose_yaml_renders(self):
        """decompose.yaml 渲染"""
        pe = PromptEngine()
        prompt = pe.build_decompose_prompt(
            available_actions=["move_forward", "turn_left"]
        )
        assert "可用原子动作" in prompt
        assert "move_forward" in prompt
        assert "## 生命感" in prompt

    def test_rag_yaml_renders(self):
        """rag.yaml 渲染"""
        pe = PromptEngine()
        prompt = pe.build_rag_prompt(
            query="猫叫什么", evidence=["小橘"], available_actions=["nod"]
        )
        assert "小橘" in prompt
        assert "用户查询" in prompt

    def test_persona_in_config(self):
        """config.yaml 人格含具身定位与安全"""
        pe = PromptEngine()
        assert "具身智能助手" in pe._persona
        assert "安全" in pe._persona


class TestAgentSystemPrompt:
    def test_partitions(self):
        """agent 系统提示词含全部分区"""
        sp = build_agent_system_prompt("", ["light_on", "idle"])
        assert "## 可用动作" in sp
        assert "## 你的工具（神经元）" in sp
        assert "## 决策流程" in sp
        assert "## finalize 契约" in sp
        assert "light_on" in sp

    def test_builtin_persona(self):
        """无 system_prompt 时用内置人格"""
        sp = build_agent_system_prompt("", ["idle"])
        assert "具身智能助手" in sp

    def test_custom_persona_preserved(self):
        """自定义 system_prompt 保留"""
        sp = build_agent_system_prompt("自定义人格", ["idle"])
        assert sp.startswith("自定义人格")
