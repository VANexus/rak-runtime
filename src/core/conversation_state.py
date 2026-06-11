"""
对话状态 — 当前对话的活状态。

不是记忆（长期），不是缓存（短期），而是：
- 此刻在聊什么
- 对话的情绪基调和口吻
- 沉默时围绕主题的发散思考
- 被打断时带着上下文无缝衔接

这是"呼吸感"的核心：对话不是一条一条独立的，而是连续的流。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rak.conversation")


@dataclass
class Message:
    """一条消息"""
    role: str                 # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    emotion: str = ""         # 消息的情绪标记


@dataclass
class WanderingThought:
    """沉默时的发散想法"""
    content: str              # 想到了什么
    related_topic: str        # 和当前话题的关联
    energy: float             # 想法的强度
    timestamp: float = field(default_factory=time.time)


class ConversationState:
    """
    对话的活状态。

    跟踪当前对话的上下文，在沉默时围绕主题发散思考，
    被打断时带着思考上下文无缝衔接。
    """

    def __init__(self):
        # ── 当前对话 ──
        self.current_topic: str = ""              # 在聊什么
        self.current_mood: str = "neutral"        # 对话情绪基调
        self.messages: list[Message] = []         # 最近消息
        self.max_messages: int = 20

        # ── 发散思考 ──
        self.wandering_thoughts: list[WanderingThought] = []
        self.max_wanderings: int = 10
        self.wandering_topic: str = ""            # 发散思考围绕的主题

        # ── 对话风格 ──
        self.tone: str = "casual"                 # casual / serious / humorous
        self.formality: float = 0.3               # 0=随意, 1=正式
        self.verbosity: float = 0.4               # 0=简洁, 1=详细

        # ── 状态 ──
        self.last_user_time: float = 0.0
        self.last_assistant_time: float = 0.0
        self.silence_start: float = 0.0           # 沉默开始时间
        self.is_silent: bool = False
        self.turn_count: int = 0

    # ══════════════════════════════════════════════════════
    #  消息记录
    # ══════════════════════════════════════════════════════

    def add_user_message(self, content: str, emotion: str = ""):
        """记录用户消息"""
        self.messages.append(Message(role="user", content=content, emotion=emotion))
        self._trim_messages()

        self.last_user_time = time.time()
        self.turn_count += 1
        self.is_silent = False
        self.silence_start = 0.0

        # 更新话题
        self._update_topic(content)

    def add_assistant_message(self, content: str, emotion: str = ""):
        """记录助手消息"""
        self.messages.append(Message(role="assistant", content=content, emotion=emotion))
        self._trim_messages()

        self.last_assistant_time = time.time()

        # 更新对话风格
        self._update_style(content)

    def _trim_messages(self):
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def _update_topic(self, content: str):
        """从消息中提取话题"""
        # 简单提取：用最近的用户消息作为话题
        self.current_topic = content[:50]
        self.wandering_topic = content[:50]

    def _update_style(self, content: str):
        """从助手回复中学习风格"""
        if len(content) < 10:
            self.verbosity = max(0.2, self.verbosity - 0.05)
        elif len(content) > 50:
            self.verbosity = min(0.8, self.verbosity + 0.05)

    # ══════════════════════════════════════════════════════
    #  沉默检测
    # ══════════════════════════════════════════════════════

    def check_silence(self) -> bool:
        """检查是否进入沉默状态"""
        if self.is_silent:
            return True

        if self.last_user_time == 0:
            return False

        silence_seconds = time.time() - self.last_user_time
        if silence_seconds > 10:  # 10 秒无用户输入算沉默
            self.is_silent = True
            self.silence_start = time.time()
            return True

        return False

    def get_silence_duration(self) -> float:
        """获取沉默时长（秒）"""
        if not self.is_silent:
            return 0.0
        return time.time() - self.silence_start

    # ══════════════════════════════════════════════════════
    #  发散思考
    # ══════════════════════════════════════════════════════

    def add_wandering(self, content: str, related_topic: str, energy: float = 0.5):
        """记录一个发散想法"""
        thought = WanderingThought(
            content=content,
            related_topic=related_topic,
            energy=energy,
        )
        self.wandering_thoughts.append(thought)
        if len(self.wandering_thoughts) > self.max_wanderings:
            self.wandering_thoughts = self.wandering_thoughts[-self.max_wanderings:]

    def get_wandering_context(self) -> str:
        """
        获取发散思考的上下文。

        用于无缝衔接：用户突然说话时，把思考上下文注入回复。
        """
        if not self.wandering_thoughts:
            return ""

        recent = self.wandering_thoughts[-3:]
        lines = []
        for t in recent:
            lines.append(f"- {t.content}")
        return "\n".join(lines)

    def clear_wandering(self):
        """清空发散思考（对话重新开始时）"""
        self.wandering_thoughts.clear()

    # ══════════════════════════════════════════════════════
    #  上下文构建
    # ══════════════════════════════════════════════════════

    def get_context_for_response(self) -> str:
        """
        构建回复时的上下文。

        包含：
        - 最近的对话历史
        - 当前话题
        - 发散思考的上下文（如果有）
        - 对话风格
        """
        parts = []

        # 对话历史
        if self.messages:
            parts.append("## 最近对话")
            for msg in self.messages[-5:]:
                role = "用户" if msg.role == "user" else "Rak"
                parts.append(f"{role}: {msg.content[:80]}")

        # 当前话题
        if self.current_topic:
            parts.append(f"## 当前话题\n{self.current_topic}")

        # 发散思考上下文（无缝衔接的关键）
        wandering = self.get_wandering_context()
        if wandering:
            parts.append(f"## 我刚才在想\n{wandering}")

        # 对话风格
        style = self._describe_style()
        if style:
            parts.append(f"## 对话风格\n{style}")

        return "\n".join(parts)

    def _describe_style(self) -> str:
        """描述当前对话风格"""
        parts = []
        if self.verbosity < 0.3:
            parts.append("简洁")
        elif self.verbosity > 0.7:
            parts.append("详细")
        if self.tone == "humorous":
            parts.append("幽默")
        elif self.tone == "serious":
            parts.append("认真")
        return "、".join(parts) if parts else ""

    # ══════════════════════════════════════════════════════
    #  无缝衔接
    # ══════════════════════════════════════════════════════

    def should_carry_context(self) -> bool:
        """
        是否应该带着发散思考的上下文回复。

        条件：
        - 刚才在沉默
        - 沉默期间有发散思考
        - 沉默时间不太长（<2 分钟，否则上下文过期）
        """
        if not self.is_silent:
            return False
        if not self.wandering_thoughts:
            return False
        silence = self.get_silence_duration()
        return silence < 120  # 2 分钟内

    def get_seamless_prefix(self) -> str:
        """
        生成无缝衔接的前缀。

        不是"我刚才在想..."，而是自然地把思考融入回复。
        例如：
        - 想到了相关的事 → 自然地提一句
        - 没想到什么 → 正常回复
        """
        if not self.should_carry_context():
            return ""

        recent = self.wandering_thoughts[-1]
        if recent.energy > 0.5:
            return f"（想到{recent.related_topic}）"
        return ""

    # ══════════════════════════════════════════════════════
    #  统计
    # ══════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            "current_topic": self.current_topic[:50],
            "current_mood": self.current_mood,
            "messages_count": len(self.messages),
            "turn_count": self.turn_count,
            "wandering_count": len(self.wandering_thoughts),
            "is_silent": self.is_silent,
            "silence_seconds": int(self.get_silence_duration()),
            "tone": self.tone,
            "verbosity": round(self.verbosity, 2),
        }
