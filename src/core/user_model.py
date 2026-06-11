"""
用户模型 — 持续学习的用户画像系统。

不存储隐私数据，只记录：
- 交互风格偏好（简洁/详细/技术型）
- 专业水平（从交互中推断）
- 行为模式（高频操作、时间规律）
- 纠正历史（用户改过什么，说明之前的理解有误）

设计原则：
- 每次交互都在更新模型，不是静态配置
- 画像用于优化响应，不是用于"讨好"用户
- 数据只存本地 JSON，不上传
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from src.core._utils import atomic_write_json

logger = logging.getLogger("rak.user_model")

# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class UserProfile:
    """用户画像 — 从交互中持续学习"""
    # 专业水平 (0.0=纯小白, 1.0=技术专家)
    expertise_level: float = 0.5

    # 沟通风格 ("简洁" / "详细" / "技术型" / "未知")
    communication_style: str = "未知"

    # 偏好响应长度 ("short" / "medium" / "long")
    preferred_response_length: str = "medium"

    # 交互统计
    total_interactions: int = 0
    correction_count: int = 0       # 用户纠正过的次数
    successful_interactions: int = 0

    # 时间戳
    first_seen: float = 0.0
    last_seen: float = 0.0


@dataclass
class InteractionRecord:
    """单次交互记录"""
    timestamp: float
    query: str
    action_taken: str
    was_corrected: bool = False
    correction: str = ""
    user_feedback: str = ""  # "positive" / "negative" / ""


@dataclass
class BehaviorPattern:
    """行为模式 — 从历史中提取"""
    # 时间规律: {"07:00": ["light_on"], "23:00": ["lock_close"]}
    time_routines: dict = field(default_factory=dict)

    # 高频查询: [("打开灯", 15), ("锁门", 12)]
    frequent_queries: list = field(default_factory=list)

    # 常用设备
    frequent_devices: dict = field(default_factory=dict)  # {"light": 20, "lock": 15}

    # 最近操作的设备 (用于 "那个" 指代消解)
    last_device: str = ""
    last_action: str = ""
    last_query: str = ""


# ── 核心类 ────────────────────────────────────────────────

class UserModel:
    """持续学习的用户模型"""

    def __init__(self, persist_path: Optional[str] = None):
        self.profile = UserProfile(
            first_seen=time.time(),
            last_seen=time.time()
        )
        self.behavior = BehaviorPattern()
        self._history: list[InteractionRecord] = []
        self._corrections: list[InteractionRecord] = []  # 纠正记录（永不淘汰）
        self._persist_path = Path(persist_path) if persist_path else None
        self._max_history = 500  # 只保留最近 500 条

        # 加载已有数据
        if self._persist_path and self._persist_path.exists():
            self._load()

    # ── 主要接口 ──────────────────────────────────────────

    def record_interaction(self, query: str, action: str,
                           was_corrected: bool = False,
                           correction: str = "",
                           feedback: str = ""):
        """记录一次交互，同时更新画像"""
        record = InteractionRecord(
            timestamp=time.time(),
            query=query,
            action_taken=action,
            was_corrected=was_corrected,
            correction=correction,
            user_feedback=feedback
        )
        self._history.append(record)

        # 更新统计
        self.profile.total_interactions += 1
        self.profile.last_seen = time.time()
        if was_corrected:
            self.profile.correction_count += 1
        if feedback == "positive" or (not was_corrected and feedback != "negative"):
            self.profile.successful_interactions += 1

        # 更新行为模式
        self._update_behavior(query, action)

        # 更新画像特征
        self._update_profile_from_interaction(record)

        # 截断历史
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        self._save()

    def record_correction(self, original_query: str, wrong_action: str,
                          correct_action: str):
        """记录用户纠正 — 这是学习信号最强的数据"""
        self.record_interaction(
            query=original_query,
            action=wrong_action,
            was_corrected=True,
            correction=correct_action,
            feedback="negative"
        )
        # 纠正单独存储（永不被历史截断淘汰）
        self._corrections.append(InteractionRecord(
            timestamp=time.time(),
            query=original_query,
            action_taken=wrong_action,
            was_corrected=True,
            correction=correct_action,
            user_feedback="negative",
        ))
        # 只保留最近 50 条纠正
        if len(self._corrections) > 50:
            self._corrections = self._corrections[-50:]
        logger.info("用户纠正: '%s' → 错误=%s, 正确=%s",
                     original_query, wrong_action, correct_action)

    def infer_intent(self, query: str, device_states: Optional[dict] = None) -> dict:
        """
        意图推断 — 不只是字面理解，结合用户画像深度推理。

        返回:
            {
                "inferred_target": "light" | "lock" | ...,
                "inferred_action": "light_on" | ...,
                "confidence": 0.0-1.0,
                "reasoning": "推断依据",
                "is_ambiguous": bool
            }
        """
        result = {
            "inferred_target": "",
            "inferred_action": "",
            "confidence": 0.0,
            "reasoning": "",
            "is_ambiguous": False
        }

        # 指代消解: "那个" → 最近操作的设备
        if any(word in query for word in ["那个", "它", "这个", "那个东西"]):
            if self.behavior.last_device:
                result["inferred_target"] = self.behavior.last_device
                result["inferred_action"] = self.behavior.last_action
                result["confidence"] = 0.7
                result["reasoning"] = f"用户说'那个'，最近操作的是 {self.behavior.last_device}"
                return result

        # 基于高频模式推断
        for freq_query, count in self.behavior.frequent_queries[:5]:
            if self._query_similarity(query, freq_query) > 0.7:
                result["confidence"] = 0.6
                result["reasoning"] = f"与高频查询 '{freq_query}' 相似（出现 {count} 次）"
                result["is_ambiguous"] = True
                return result

        # 基于时间规律推断
        import datetime
        now = datetime.datetime.now()
        time_key = now.strftime("%H:%M")
        for routine_time, actions in self.behavior.time_routines.items():
            if abs(self._time_diff_minutes(time_key, routine_time)) < 15:
                result["confidence"] = 0.5
                result["reasoning"] = f"当前时间接近日常规律 {routine_time}（{actions}）"
                result["is_ambiguous"] = True
                return result

        result["is_ambiguous"] = True
        result["reasoning"] = "无足够上下文推断意图"
        return result

    def get_profile_summary(self) -> str:
        """生成用户画像摘要 — 用于注入系统提示词"""
        lines = []

        # 专业水平描述
        if self.profile.expertise_level < 0.3:
            lines.append("用户是技术新手，需要用简单易懂的语言解释。")
        elif self.profile.expertise_level > 0.7:
            lines.append("用户有较强技术背景，可以直接使用技术术语。")

        # 沟通风格
        if self.profile.communication_style != "未知":
            lines.append(f"用户偏好{self.profile.communication_style}的沟通方式。")

        # 行为模式
        if self.behavior.frequent_queries:
            top_queries = [q for q, _ in self.behavior.frequent_queries[:3]]
            lines.append(f"用户的高频操作：{', '.join(top_queries)}。")

        if self.behavior.time_routines:
            routines = [f"{t} {', '.join(a)}" for t, a in
                       list(self.behavior.time_routines.items())[:3]]
            lines.append(f"用户的日常规律：{'; '.join(routines)}。")

        # 纠正历史的教训
        corrections = [r for r in self._history if r.was_corrected]
        if corrections:
            recent = corrections[-3:]
            lessons = [f"'{c.query}' 不应该是 {c.action_taken}（用户纠正为 {c.correction}）"
                      for c in recent]
            lines.append(f"历史教训：{'; '.join(lessons)}。")

        # 最近操作
        if self.behavior.last_device:
            lines.append(f"用户最近操作的设备：{self.behavior.last_device}。")

        return "\n".join(lines) if lines else "用户画像数据不足，暂无特殊偏好。"

    def get_correction_context(self, query: str) -> Optional[str]:
        """检查是否有类似查询的纠正历史，用于避免重复犯错"""
        # 优先查独立的纠正存储（不会被历史截断淘汰）
        corrections = self._corrections if self._corrections else [
            r for r in self._history if r.was_corrected
        ]
        for c in reversed(corrections):
            if self._query_similarity(query, c.query) > 0.7:
                return (f"注意：用户之前纠正过类似查询 '{c.query}' — "
                       f"不应执行 {c.action_taken}，应执行 {c.correction}")
        return None

    def get_stats(self) -> dict:
        """获取用户模型统计"""
        return {
            "total_interactions": self.profile.total_interactions,
            "correction_count": self.profile.correction_count,
            "success_rate": (
                self.profile.successful_interactions / max(1, self.profile.total_interactions)
            ),
            "expertise_level": round(self.profile.expertise_level, 2),
            "communication_style": self.profile.communication_style,
            "frequent_queries": self.behavior.frequent_queries[:5],
            "last_device": self.behavior.last_device,
            "time_routines": dict(list(self.behavior.time_routines.items())[:5]),
        }

    # ── 内部方法 ──────────────────────────────────────────

    def _update_behavior(self, query: str, action: str):
        """更新行为模式"""
        # 更新最近操作
        self.behavior.last_query = query
        self.behavior.last_action = action

        # 提取设备类型
        device = self._extract_device(action)
        if device:
            self.behavior.last_device = device
            self.behavior.frequent_devices[device] = \
                self.behavior.frequent_devices.get(device, 0) + 1

        # 更新高频查询
        self._update_frequent_queries(query)

        # 更新时间规律
        self._update_time_routine(action)

    def _update_frequent_queries(self, query: str):
        """更新高频查询列表"""
        # 查找相似查询
        for i, (q, count) in enumerate(self.behavior.frequent_queries):
            if self._query_similarity(query, q) > 0.8:
                self.behavior.frequent_queries[i] = (q, count + 1)
                # 重新排序
                self.behavior.frequent_queries.sort(key=lambda x: x[1], reverse=True)
                return

        # 新查询
        self.behavior.frequent_queries.append((query, 1))
        self.behavior.frequent_queries.sort(key=lambda x: x[1], reverse=True)
        # 截断
        if len(self.behavior.frequent_queries) > 50:
            self.behavior.frequent_queries = self.behavior.frequent_queries[:50]

    def _update_time_routine(self, action: str):
        """更新时间规律"""
        import datetime
        now = datetime.datetime.now()
        # 四舍五入到 15 分钟
        minute = (now.minute // 15) * 15
        time_key = f"{now.hour:02d}:{minute:02d}"

        if time_key not in self.behavior.time_routines:
            self.behavior.time_routines[time_key] = []

        actions = self.behavior.time_routines[time_key]
        device = self._extract_device(action)
        if device and device not in actions:
            actions.append(device)
            # 每个时间段最多记录 5 个设备
            if len(actions) > 5:
                self.behavior.time_routines[time_key] = actions[-5:]

    def _update_profile_from_interaction(self, record: InteractionRecord):
        """从交互中更新画像特征"""
        # 从查询长度推断沟通风格
        query_len = len(record.query)
        if query_len < 5:
            style_hint = "简洁"
        elif query_len > 20:
            style_hint = "详细"
        else:
            style_hint = "普通"

        # 用加权平均更新（新数据权重更高）
        if self.profile.communication_style == "未知":
            self.profile.communication_style = style_hint

        # 从纠正中学习专业水平
        if record.was_corrected:
            # 用户纠正说明他在意准确度 → 可能更有经验
            self.profile.expertise_level = min(1.0,
                self.profile.expertise_level + 0.02)

        # 注意：successful_interactions 已在 record_interaction 中更新，此处不再重复计数

    def _extract_device(self, action: str) -> str:
        """从动作名提取设备类型"""
        device_keywords = {
            "light": ["light", "lamp", "灯"],
            "lock": ["lock", "门锁", "锁"],
            "motor": ["move", "forward", "back", "turn", "移动", "转"],
            "servo": ["nod", "shake", "wave", "dance", "点头", "摇头", "挥手"],
        }
        action_lower = action.lower()
        for device, keywords in device_keywords.items():
            if any(kw in action_lower for kw in keywords):
                return device
        return ""

    def _query_similarity(self, a: str, b: str) -> float:
        """简单的查询相似度（字符级 Jaccard）"""
        if not a or not b:
            return 0.0
        set_a = set(a)
        set_b = set(b)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _time_diff_minutes(self, t1: str, t2: str) -> int:
        """计算两个 HH:MM 时间的分钟差"""
        try:
            h1, m1 = map(int, t1.split(":"))
            h2, m2 = map(int, t2.split(":"))
            return (h1 * 60 + m1) - (h2 * 60 + m2)
        except Exception:
            return 999

    # ── 持久化 ────────────────────────────────────────────

    def _save(self):
        try:
            data = {
                "profile": {
                    "expertise_level": self.profile.expertise_level,
                    "communication_style": self.profile.communication_style,
                    "preferred_response_length": self.profile.preferred_response_length,
                    "total_interactions": self.profile.total_interactions,
                    "correction_count": self.profile.correction_count,
                    "successful_interactions": self.profile.successful_interactions,
                    "first_seen": self.profile.first_seen,
                    "last_seen": self.profile.last_seen,
                },
                "behavior": {
                    "time_routines": self.behavior.time_routines,
                    "frequent_queries": self.behavior.frequent_queries,
                    "frequent_devices": self.behavior.frequent_devices,
                    "last_device": self.behavior.last_device,
                    "last_action": self.behavior.last_action,
                    "last_query": self.behavior.last_query,
                },
                "history": [asdict(r) for r in self._history[-100:]],
            }
            atomic_write_json(self._persist_path, data)
        except Exception as e:
            logger.warning("用户模型持久化失败: %s", e)

    def _load(self):
        """从 JSON 加载"""
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "profile" in data:
                self.profile = UserProfile(**data["profile"])
            if "behavior" in data:
                self.behavior = BehaviorPattern(**data["behavior"])
            if "history" in data:
                self._history = [InteractionRecord(**r) for r in data["history"]]

            logger.info("用户模型已加载: %d 条历史记录", len(self._history))
        except Exception as e:
            logger.warning("加载用户模型失败: %s", e)
