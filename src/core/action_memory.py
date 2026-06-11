"""
Action Memory: 动作记忆 + Record-and-Replay

灵感来源：MOBIMEM (arXiv:2512.15784, Dec 2025)
核心思想：记录成功的完整决策轨迹，相似查询直接重放，跳过 LLM。

与 CogRec 的区别：
- CogRec: 提取规则（pattern → action），抽象级别高
- ActionMemory: 记录完整轨迹（query → context → action → result），精确重放

两者互补：CogRec 处理通用模式，ActionMemory 处理精确场景。

效果：已知模式从 ~3s（LLM）降到 <1ms（重放）。
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ActionTrajectory:
    """一次成功的完整决策轨迹"""
    query: str
    action: str
    params_json: str
    context: Dict          # 决策时的上下文（设备状态、时间等）
    result: Dict           # 执行结果
    timestamp: float = field(default_factory=time.time)
    replay_count: int = 0  # 被重放的次数
    success_after_replay: int = 0  # 重放后成功的次数

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "action": self.action,
            "params_json": self.params_json,
            "context": self.context,
            "result": self.result,
            "timestamp": self.timestamp,
            "replay_count": self.replay_count,
            "success_after_replay": self.success_after_replay,
        }

    def success_rate(self) -> float:
        """重放成功率"""
        if self.replay_count == 0:
            return 1.0  # 未重放过，默认成功
        return self.success_after_replay / self.replay_count

    @classmethod
    def from_dict(cls, data: Dict) -> 'ActionTrajectory':
        return cls(
            query=data["query"],
            action=data["action"],
            params_json=data.get("params_json", "{}"),
            context=data.get("context", {}),
            result=data.get("result", {}),
            timestamp=data.get("timestamp", time.time()),
            replay_count=data.get("replay_count", 0),
            success_after_replay=data.get("success_after_replay", 0),
        )


class ActionMemory:
    """
    动作记忆 — Record-and-Replay。

    记录每次成功的决策轨迹，当相似查询再次出现时直接重放。
    检索策略：关键词相似度 + 上下文匹配。

    不是所有查询都适合重放：
    - 简单指令（"开灯"）→ 适合重放
    - 复杂推理（"我有点冷"）→ 不适合重放，需要 LLM
    """

    def __init__(self, persist_path: str = None, max_trajectories: int = 500):
        self._trajectories: List[ActionTrajectory] = []
        self._max_trajectories = max_trajectories
        self._persist_path = persist_path

        # 统计
        self._total_queries = 0
        self._replay_hits = 0
        self._replay_successes = 0

        # 从磁盘加载
        if persist_path:
            self._load()

    def record(self, query: str, action: str, params_json: str,
               context: Dict, result: Dict):
        """记录一次成功的决策轨迹"""
        trajectory = ActionTrajectory(
            query=query,
            action=action,
            params_json=params_json,
            context=context,
            result=result,
        )
        self._trajectories.append(trajectory)

        # 超限时淘汰最旧的
        if len(self._trajectories) > self._max_trajectories:
            self._trajectories = self._trajectories[-self._max_trajectories:]

        # 持久化
        if self._persist_path:
            self._save()

        logger.debug("[ActionMemory] 记录轨迹: '%s' → %s", query[:30], action)

    def replay(self, query: str, available_actions: List[str],
               context: Dict = None) -> Optional[Dict]:
        """
        尝试重放。LLM 判断是否适合重放。

        不用固定阈值——找到候选后让 LLM 评估上下文是否匹配。
        """
        self._total_queries += 1

        # 第一步：快速筛选候选（字符相似度）
        candidates = []
        for traj in self._trajectories:
            if traj.action not in available_actions:
                continue
            similarity = self._query_similarity(query, traj.query)
            if similarity > 0.5:  # 宽松筛选，交给 LLM 精确判断
                candidates.append((similarity, traj))

        if not candidates:
            return None

        # 按相似度排序
        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:3]  # 取 top 3 候选

        # 如果最高相似度非常高（近乎精确匹配），直接重放
        if top[0][0] > 0.95:
            traj = top[0][1]
            traj.replay_count += 1
            self._replay_hits += 1
            return {
                "action": traj.action,
                "params_json": traj.params_json,
                "confidence": top[0][0],
                "source": "action_memory_exact",
            }

        # 否则让 LLM 判断
        llm = self._get_llm_client()
        if not llm:
            return None

        candidate_text = "\n".join(
            f"- 查询: '{t.query}' → 动作: {t.action} (相似度: {s:.2f}, 成功率: {t.success_rate():.0%})"
            for s, t in top
        )

        prompt = f"""用户说: "{query}"

历史决策候选：
{candidate_text}

当前可用动作: {', '.join(available_actions)}

问题：用户当前的指令和历史中的哪个最相似？可以直接重用那个动作吗？

输出 JSON:
{{"match": true/false, "action": "选择的动作", "confidence": 0.0-1.0, "reason": "原因"}}"""

        try:
            response = llm.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=128,
                system="你是决策重放评估模块。判断历史决策是否可以直接重用。只输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
                extra_body={"thinking": {"type": "disabled"}},
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    break

            parsed = self._parse_json(text)
            if parsed and parsed.get("match") and parsed.get("action"):
                action = parsed["action"]
                if action in available_actions:
                    self._replay_hits += 1
                    # 更新匹配的轨迹
                    for _, traj in top:
                        if traj.action == action:
                            traj.replay_count += 1
                            break
                    return {
                        "action": action,
                        "params_json": "{}",
                        "confidence": parsed.get("confidence", 0.7),
                        "source": "action_memory_llm",
                    }

        except Exception as e:
            logger.warning("[ActionMemory] LLM 评估失败: %s", e)

        return None

    def on_replay_result(self, query: str, success: bool):
        """重放后的结果反馈"""
        for traj in self._trajectories:
            if self._query_similarity(query, traj.query) > 0.9:
                if success:
                    traj.success_after_replay += 1
                    self._replay_successes += 1
                break

    def _query_similarity(self, q1: str, q2: str) -> float:
        """查询相似度（字符级 Jaccard + 子串匹配）"""
        q1 = q1.strip().lower()
        q2 = q2.strip().lower()

        # 精确匹配
        if q1 == q2:
            return 1.0

        # 子串匹配
        if q1 in q2 or q2 in q1:
            return 0.95

        # 字符级 Jaccard
        set1 = set(q1)
        set2 = set(q2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        if union == 0:
            return 0.0
        return intersection / union

    def _context_similarity(self, ctx1: Optional[Dict], ctx2: Dict) -> float:
        """上下文相似度"""
        if not ctx1 or not ctx2:
            return 0.5  # 无上下文时给中性分

        # 比较关键字段
        matches = 0
        total = 0
        for key in ["device_id", "online", "time_of_day"]:
            if key in ctx1 and key in ctx2:
                total += 1
                if ctx1[key] == ctx2[key]:
                    matches += 1

        if total == 0:
            return 0.5
        return matches / total

    def get_stats(self) -> Dict:
        total = self._total_queries or 1
        return {
            "total_trajectories": len(self._trajectories),
            "total_queries": self._total_queries,
            "replay_hits": self._replay_hits,
            "replay_hit_rate": f"{self._replay_hits / total:.1%}",
            "replay_successes": self._replay_successes,
            "most_replayed": sorted(
                self._trajectories,
                key=lambda t: t.replay_count, reverse=True
            )[:3],
        }

    def _save(self):
        try:
            from src.core._utils import atomic_write_json
            data = [t.to_dict() for t in self._trajectories]
            atomic_write_json(self._persist_path, data)
        except Exception as e:
            logger.warning("[ActionMemory] 持久化失败: %s", e)

    def _load(self):
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            self._trajectories = [ActionTrajectory.from_dict(d) for d in data]
            logger.info("[ActionMemory] 加载 %d 条轨迹", len(self._trajectories))
        except Exception as e:
            logger.warning("[ActionMemory] 加载失败: %s", e)

    def _get_llm_client(self):
        if not hasattr(self, '_llm'):
            self._llm = None
        if self._llm is None:
            try:
                import anthropic
                self._llm = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
                    base_url=os.getenv(
                        "ANTHROPIC_BASE_URL",
                        "https://token-plan-cn.xiaomimimo.com/anthropic",
                    ),
                    timeout=5.0,
                )
            except Exception:
                pass
        return self._llm

    def _parse_json(self, text: str):
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return None
