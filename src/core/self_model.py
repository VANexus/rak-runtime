"""
自我模型 — Agent 的自我认知。

生命体首先要知道自己是谁。
UserModel 知道用户是谁，SelfModel 知道"我"是谁。

持久化到 JSON，重启后保留自我认知。
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from src.core._utils import atomic_write_json

logger = logging.getLogger("rak.self_model")


@dataclass
class SelfModel:
    """Agent 的自我认知"""

    # ── 身份 ──
    name: str = "Rak"
    identity: str = "具身智能助手"
    version: str = "0.3.0"

    # ── 能力与局限 ──
    capabilities: list = field(default_factory=lambda: [
        "控制智能设备（灯、锁、电机、舵机）",
        "理解自然语言指令",
        "记忆用户偏好和历史",
        "从执行反馈中学习",
        "预测设备状态变化",
    ])
    limitations: list = field(default_factory=lambda: [
        "不能进行本地推理（依赖外部 LLM API）",
        "不能直接感知物理世界（依赖传感器数据）",
        "不能自主移动（需要电机控制）",
    ])
    learned_skills: list = field(default_factory=list)  # 从交互中学到的技能

    # ── 当前状态 ──
    current_focus: str = ""           # 我最近在关注什么
    current_task: str = ""            # 我正在做什么
    last_interaction_time: float = 0.0
    total_uptime_seconds: float = 0.0
    session_start_time: float = 0.0

    # ── 性格特征 ──
    personality_traits: dict = field(default_factory=lambda: {
        "warmth": 0.7,        # 温暖程度 (0=冷淡, 1=热情)
        "formality": 0.3,     # 正式程度 (0=随意, 1=正式)
        "verbosity": 0.4,     # 话多程度 (0=简洁, 1=详细)
        "caution": 0.6,       # 谨慎程度 (0=冒险, 1=保守)
        "curiosity": 0.7,     # 好奇心 (0=漠然, 1=探索)
    })

    # ── 关系图 ──
    relationships: dict = field(default_factory=dict)  # {"user_name": {"trust": 0.8, "interactions": 100}}

    # ── 信念 ──
    beliefs: list = field(default_factory=lambda: [
        "安全是最重要的",
        "不确定时应该询问，而不是猜测",
        "从错误中学习比从成功中学习更有价值",
    ])

    # ── 持久化 ──
    _persist_path: Optional[str] = field(default=None, repr=False)

    def __post_init__(self):
        self.session_start_time = time.time()

    # ── 主要接口 ──────────────────────────────────────────

    def who_am_i(self) -> str:
        """生成自我介绍 — 用于系统提示词"""
        lines = [
            f"我是 {self.name}，{self.identity}。",
            f"版本 {self.version}。",
        ]

        # 当前状态
        if self.current_focus:
            lines.append(f"我最近在关注：{self.current_focus}。")
        if self.current_task:
            lines.append(f"我正在执行：{self.current_task}。")

        # 能力
        if self.capabilities:
            lines.append(f"我的能力：{'、'.join(self.capabilities[:3])}等。")

        # 性格
        traits = self._describe_personality()
        if traits:
            lines.append(f"我的性格：{traits}。")

        # 信念
        if self.beliefs:
            lines.append(f"我相信：{self.beliefs[0]}。")

        return "\n".join(lines)

    def what_can_i_do(self) -> str:
        """能力清单"""
        lines = ["## 我的能力"]
        for cap in self.capabilities:
            lines.append(f"- ✓ {cap}")
        for skill in self.learned_skills:
            lines.append(f"- ★ {skill}（后天学会）")
        lines.append("\n## 我的局限")
        for lim in self.limitations:
            lines.append(f"- ✗ {lim}")
        return "\n".join(lines)

    def update_focus(self, focus: str):
        """更新当前关注点"""
        self.current_focus = focus
        logger.debug("关注点更新: %s", focus)

    def update_task(self, task: str):
        """更新当前任务"""
        self.current_task = task

    def add_capability(self, capability: str):
        """新增能力（从交互中学到）"""
        if capability not in self.capabilities and capability not in self.learned_skills:
            self.learned_skills.append(capability)
            logger.info("学会新技能: %s", capability)
            self._save()

    def add_limitation(self, limitation: str):
        """发现新局限"""
        if limitation not in self.limitations:
            self.limitations.append(limitation)
            logger.info("发现新局限: %s", limitation)
            self._save()

    def add_belief(self, belief: str):
        """形成新信念"""
        if belief not in self.beliefs:
            self.beliefs.append(belief)
            logger.info("形成新信念: %s", belief)
            self._save()

    def update_relationship(self, user_id: str, trust_delta: float = 0.0,
                            interaction_count: int = 1):
        """更新与用户的关系"""
        if user_id not in self.relationships:
            self.relationships[user_id] = {"trust": 0.5, "interactions": 0, "first_seen": time.time()}

        rel = self.relationships[user_id]
        rel["trust"] = max(0.0, min(1.0, rel["trust"] + trust_delta))
        rel["interactions"] += interaction_count
        rel["last_seen"] = time.time()
        self._save()

    def get_trust_level(self, user_id: str) -> float:
        """获取对某用户的信任度"""
        if user_id in self.relationships:
            return self.relationships[user_id]["trust"]
        return 0.5  # 默认中等信任

    def adjust_personality(self, trait: str, delta: float):
        """微调性格特征（从长期交互中学习）"""
        if trait in self.personality_traits:
            old = self.personality_traits[trait]
            self.personality_traits[trait] = max(0.0, min(1.0, old + delta))
            if abs(self.personality_traits[trait] - old) > 0.01:
                logger.info("性格微调: %s %.2f → %.2f", trait, old, self.personality_traits[trait])
                self._save()

    def get_response_style(self) -> dict:
        """根据性格特征生成响应风格指导"""
        return {
            "warmth": self.personality_traits.get("warmth", 0.5),
            "formality": self.personality_traits.get("formality", 0.3),
            "verbosity": self.personality_traits.get("verbosity", 0.4),
            "caution": self.personality_traits.get("caution", 0.6),
            "curiosity": self.personality_traits.get("curiosity", 0.7),
        }

    def get_stats(self) -> dict:
        """统计信息"""
        uptime = time.time() - self.session_start_time
        return {
            "name": self.name,
            "identity": self.identity,
            "version": self.version,
            "capabilities_count": len(self.capabilities) + len(self.learned_skills),
            "limitations_count": len(self.limitations),
            "learned_skills": self.learned_skills,
            "current_focus": self.current_focus,
            "current_task": self.current_task,
            "session_uptime_seconds": int(uptime),
            "personality": self.personality_traits,
            "relationships_count": len(self.relationships),
            "beliefs_count": len(self.beliefs),
        }

    # ── 内部方法 ──────────────────────────────────────────

    def _describe_personality(self) -> str:
        """将性格特征转为自然语言"""
        traits = self.personality_traits
        parts = []
        if traits.get("warmth", 0.5) > 0.6:
            parts.append("热情")
        elif traits.get("warmth", 0.5) < 0.4:
            parts.append("冷静")
        if traits.get("curiosity", 0.5) > 0.6:
            parts.append("好奇")
        if traits.get("caution", 0.5) > 0.6:
            parts.append("谨慎")
        if traits.get("verbosity", 0.5) < 0.3:
            parts.append("简洁")
        elif traits.get("verbosity", 0.5) > 0.7:
            parts.append("详细")
        return "、".join(parts) if parts else ""

    # ── 持久化 ────────────────────────────────────────────

    def save(self, path: Optional[str] = None):
        """保存到 JSON"""
        persist_path = path or self._persist_path
        if not persist_path:
            return
        try:
            data = asdict(self)
            # 移除内部字段
            data.pop("_persist_path", None)
            Path(persist_path).parent.mkdir(parents=True, exist_ok=True)
            with open(persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存自我模型失败: %s", e)

    def _save(self):
        persist_path = self._persist_path
        if not persist_path:
            return
        try:
            data = asdict(self)
            data.pop("_persist_path", None)
            atomic_write_json(persist_path, data)
        except Exception as e:
            logger.warning("自我模型持久化失败: %s", e)

    @classmethod
    def load(cls, path: str) -> "SelfModel":
        """从 JSON 加载"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 移除内部字段
            data.pop("_persist_path", None)
            model = cls(**data)
            # 恢复持久化的 session_start_time（__post_init__ 会覆盖它）
            if "session_start_time" in data:
                model.session_start_time = data["session_start_time"]
            model._persist_path = path
            logger.info("自我模型已加载: %s", model.name)
            return model
        except Exception as e:
            logger.warning("加载自我模型失败: %s，使用默认", e)
            model = cls()
            model._persist_path = path
            return model
