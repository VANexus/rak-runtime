"""
提示词引擎（Prompt Engine）— YAML 模板 + Jinja2 渲染

核心思想：提示词模板外置到 YAML 文件，运行时动态填充变量。
- 模板修改不需要改代码
- Jinja2 支持条件、循环、过滤器
- 支持热重载（开发时修改 YAML 立即生效）

降级策略：YAML 加载失败时使用内置默认模板。
"""

import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Jinja2 和 PyYAML（必需依赖）
import yaml
from jinja2 import Template, Environment, FileSystemLoader


# 模板目录：项目根目录下的 prompts/
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class PromptEngine:
    """
    提示词引擎 — 从 YAML 模板构建 LLM 系统提示词。

    模板查找顺序：
    1. prompts/ 目录下的 YAML 文件
    2. 内置默认模板（降级）
    """

    def __init__(self, prompts_dir: str = None):
        self._prompts_dir = Path(prompts_dir) if prompts_dir else _promPTS_DIR
        self._templates: Dict[str, Template] = {}
        self._config: Dict = {}

        # 累积的洞察
        self._insights: List[str] = []
        self._max_insights = 10

        # 系统人格
        self._persona = os.getenv(
            "RAK_PERSONA",
            "你是 Rak，一个具身智能助手。你控制物理设备执行用户的指令。"
            "你谨慎、高效、安全第一。"
        )

        # Jinja2 环境
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(self._prompts_dir)) if self._prompts_dir.exists() else None,
            keep_trailing_newline=True,
        )

        # 加载模板
        self._load_templates()

    def _load_templates(self):
        """从 YAML 文件加载提示词模板"""
        if not self._prompts_dir.exists():
            logger.warning("[PromptEngine] 模板目录不存在: %s，使用内置默认", self._prompts_dir)
            return

        # 加载配置
        config_path = self._prompts_dir / "config.yaml"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    self._config = yaml.safe_load(f) or {}
                logger.info("[PromptEngine] 加载配置: %s", config_path)
            except Exception as e:
                logger.warning("[PromptEngine] 配置加载失败: %s", e)

        # 加载模板文件
        template_files = {
            "decision": "decision.yaml",
            "decompose": "decompose.yaml",
            "rag": "rag.yaml",
        }

        for name, filename in template_files.items():
            filepath = self._prompts_dir / filename
            if filepath.exists():
                try:
                    with open(filepath) as f:
                        data = yaml.safe_load(f) or {}
                    template_str = data.get("system_prompt", "")
                    if template_str:
                        self._templates[name] = Template(template_str)
                        logger.info("[PromptEngine] 加载模板: %s", filename)
                except Exception as e:
                    logger.warning("[PromptEngine] 模板加载失败 %s: %s", filename, e)

    def add_insight(self, insight: str):
        """添加来自学习闭环的洞察"""
        self._insights.append(insight)
        if len(self._insights) > self._max_insights:
            self._insights = self._insights[-self._max_insights:]
        logger.info("[PromptEngine] 新增洞察: %s...", insight[:50])

    def _get_shared_context(self, available_actions, memory_context, device_state):
        """构建共享的模板变量上下文"""
        return {
            "agent_name": "Rak",
            "persona": self._persona,
            "available_actions": available_actions,
            "memory_context": memory_context,
            "device_state": device_state,
            "insights": self._insights,
            "output_format": self._config.get("output_format", ""),
            "decision_rules": self._config.get("decision_rules", []),
        }

    def build_system_prompt(
        self,
        available_actions: List[str],
        memory_context: str = "",
        device_state: str = "",
        user_query: str = "",
    ) -> str:
        """构建单次决策的系统提示词"""
        ctx = self._get_shared_context(available_actions, memory_context, device_state)

        # 优先使用 YAML 模板
        if "decision" in self._templates:
            try:
                return self._templates["decision"].render(**ctx).strip()
            except Exception as e:
                logger.warning("[PromptEngine] YAML 渲染失败，回退内置: %s", e)

        # 内置默认模板
        return self._build_fallback_prompt(available_actions, memory_context, device_state)

    def build_decompose_prompt(
        self,
        available_actions: List[str],
        memory_context: str = "",
        device_state: str = "",
    ) -> str:
        """构建多动作分解的系统提示词"""
        ctx = self._get_shared_context(available_actions, memory_context, device_state)

        if "decompose" in self._templates:
            try:
                return self._templates["decompose"].render(**ctx).strip()
            except Exception as e:
                logger.warning("[PromptEngine] YAML 渲染失败，回退内置: %s", e)

        return self._build_fallback_decompose_prompt(available_actions, memory_context, device_state)

    def build_rag_prompt(
        self,
        query: str,
        evidence: List[str],
        available_actions: List[str],
    ) -> str:
        """构建 RAG 推理提示词"""
        evidence_text = "\n".join(f"[{i+1}] {ev}" for i, ev in enumerate(evidence[:10]))

        ctx = {
            "agent_name": "Rak",
            "query": query,
            "context": evidence_text,
            "available_actions": available_actions,
        }

        if "rag" in self._templates:
            try:
                return self._templates["rag"].render(**ctx).strip()
            except Exception as e:
                logger.warning("[PromptEngine] YAML 渲染失败，回退内置: %s", e)

        return self._build_fallback_rag_prompt(query, evidence_text, available_actions)

    # ========== 内置默认模板（降级用） ==========

    def _build_fallback_prompt(self, available_actions, memory_context, device_state):
        """内置默认决策提示词"""
        parts = [self._persona, ""]

        parts.append("## 可用动作")
        for action in available_actions:
            parts.append(f"- {action}")
        parts.append("")

        if memory_context:
            parts.append(memory_context)
            parts.append("")

        if device_state:
            parts.append(f"## 当前设备状态\n{device_state}")
            parts.append("")

        if self._insights:
            parts.append("## 经验教训")
            for insight in self._insights:
                parts.append(f"- {insight}")
            parts.append("")

        parts.append("""## 输出格式
返回一个 JSON 对象：
{
  "action": "选择的动作名（必须在可用列表中）",
  "params_json": "参数 JSON 字符串",
  "reasoning": "简短的决策理由（中文）",
  "answer": "对用户的自然语言回复（中文，可选）"
}

## 规则
1. 必须且只能选择可用动作列表中的一个
2. params_json 必须是合法 JSON
3. 如果信息不足，选择最安全的动作
4. 参考记忆中的经验，避免重复失败
5. 如果用户在问问题或聊天，用 answer 字段回复，action 选 idle
6. 如果记忆中有用户需要的信息，在 answer 中提供""")

        return "\n".join(parts)

    def _build_fallback_decompose_prompt(self, available_actions, memory_context, device_state):
        """内置默认分解提示词"""
        parts = [self._persona, ""]

        parts.append("## 可用原子动作")
        for action in available_actions:
            parts.append(f"- {action}")
        parts.append("")

        if memory_context:
            parts.append(memory_context)
            parts.append("")

        if device_state:
            parts.append(f"## 当前设备状态\n{device_state}")
            parts.append("")

        parts.append("""## 输出格式
将用户指令分解为一系列原子动作，返回 JSON：
{
  "actions": [
    {"action": "动作名", "params_json": "{}", "priority": 1},
    {"action": "动作名", "params_json": "{}", "priority": 2}
  ]
}

## 规则
1. 每个动作必须在可用列表中
2. 按执行顺序排列
3. priority 从 1 开始递增
4. 参考记忆中的经验，避免重复失败""")

        return "\n".join(parts)

    def _build_fallback_rag_prompt(self, query, evidence_text, available_actions):
        """内置默认 RAG 提示词"""
        return f"""基于以下证据，判断是否足以回答问题，并选择最合适的动作。

## 用户问题
{query}

## 检索到的证据
{evidence_text if evidence_text else "（无证据）"}

## 可用动作
{chr(10).join(f"- {a}" for a in available_actions)}

## 输出格式
返回 JSON：
{{
  "sufficient": true/false,
  "confidence": 0.0-1.0,
  "answer": "如果证据充分，给出答案",
  "action": "选择的动作",
  "params_json": "{{}}",
  "refined_query": "如果证据不充分，给出更精确的检索查询"
}}"""

    def stats(self) -> Dict:
        return {
            "insights_count": len(self._insights),
            "persona": self._persona[:50],
            "templates_loaded": list(self._templates.keys()),
            "prompts_dir": str(self._prompts_dir),
        }


# 修复拼写错误（_promPTS_DIR → _PROMPTS_DIR）
_promPTS_DIR = _PROMPTS_DIR
