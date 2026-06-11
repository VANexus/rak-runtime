"""
内心循环（Inner Loop）— 事件驱动的生命节奏。

不是 30 秒定时器，而是三层节奏：

1. 事件驱动（毫秒级）：有事发生 → 立刻反应
2. 余韵（秒级）：事件后的涟漪效应 → 自然联想
3. 安静联想（分钟级）：长时间无事件 → 概率触发随机联想

没有事件时真的安静，不产生垃圾想法。
"""

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("rak.inner_loop")


@dataclass
class InnerThought:
    """一次内心想法"""
    content: str
    source: str               # "event" | "ripple" | "idle" | "need" | "emotion"
    energy: float             # 0~1
    should_speak: bool
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "source": self.source,
            "energy": round(self.energy, 3),
            "should_speak": self.should_speak,
            "timestamp": self.timestamp,
        }


class InnerLoop:
    """
    事件驱动的内心循环。

    不是定时器，而是：
    - 有事件 → 立刻反应 + 产生余韵
    - 没事件 → 安静存在（概率触发随机联想）
    """

    def __init__(self):
        # 外部依赖
        self._emotion_engine = None
        self._need_engine = None
        self._living_graph = None
        self._self_model = None
        self._world_model = None
        self._conversation_state = None

        # 回调
        self._speak_callback: Optional[Callable[[str], Awaitable[None]]] = None

        # 状态
        self._thoughts: list[InnerThought] = []
        self._max_thoughts = 200
        self._last_event_time: float = time.time()
        self._last_idle_think_time: float = 0
        self._event_count: int = 0

        # 余韵队列（事件后产生的联想，延迟执行）
        self._ripple_queue: list[dict] = []
        self._ripple_task: Optional[asyncio.Task] = None

        # 安静联想的后台任务
        self._idle_task: Optional[asyncio.Task] = None
        self._running = False

        # 统计
        self._stats = {
            "total_events": 0,
            "total_ripples": 0,
            "total_idle_thinks": 0,
            "times_spoken": 0,
            "times_silent": 0,
            "start_time": 0.0,
        }

    # ── 生命周期 ──────────────────────────────────────────

    def set_dependencies(self, emotion_engine=None, need_engine=None,
                         living_graph=None, self_model=None,
                         world_model=None, conversation_state=None):
        self._emotion_engine = emotion_engine
        self._need_engine = need_engine
        self._living_graph = living_graph
        self._self_model = self_model
        self._world_model = world_model
        self._conversation_state = conversation_state

    def set_speak_callback(self, callback: Callable[[str], Awaitable[None]]):
        self._speak_callback = callback

    async def start(self):
        """启动后台任务"""
        if self._running:
            return
        self._running = True
        self._stats["start_time"] = time.time()
        self._idle_task = asyncio.create_task(self._idle_loop())
        logger.info("内心循环已启动（事件驱动 + 安静联想）")

    async def stop(self):
        self._running = False
        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
        logger.info("内心循环已停止")

    # ══════════════════════════════════════════════════════
    #  第一层：事件驱动（毫秒级）
    # ══════════════════════════════════════════════════════

    def on_event(self, event_type: str, details: dict):
        """
        事件发生时立刻调用。

        这是主要的"思考"触发器。
        每个 gRPC 请求、设备状态变化、异常都算一个事件。
        """
        self._last_event_time = time.time()
        self._event_count += 1
        self._stats["total_events"] += 1

        # 1. 更新情绪
        self._process_emotion(event_type, details)

        # 2. 更新需求
        self._process_needs(event_type, details)

        # 3. 产生余韵（事件后的涟漪）
        self._spawn_ripple(event_type, details)

        # 4. 检查是否需要主动说话
        thought = self._check_speak_trigger(event_type, details)
        if thought:
            self._record_thought(thought)

    def _process_emotion(self, event_type: str, details: dict):
        """事件驱动的情绪更新"""
        if not self._emotion_engine:
            return

        if event_type == "decision":
            success = details.get("success", True)
            action = details.get("action", "")
            if success:
                self._emotion_engine.on_success(action)
            else:
                self._emotion_engine.on_failure(action)

        elif event_type == "correction":
            self._emotion_engine.on_correction(details.get("action", ""))

        elif event_type == "anomaly":
            self._emotion_engine.on_anomaly(details.get("description", ""))

        elif event_type == "feedback":
            feedback = details.get("feedback", "")
            if feedback == "positive":
                self._emotion_engine.on_positive_feedback()
            elif feedback == "negative":
                self._emotion_engine.on_negative_feedback()

    def _process_needs(self, event_type: str, details: dict):
        """事件驱动的需求更新"""
        if not self._need_engine:
            return

        if event_type == "decision":
            self._need_engine.record_decision(details.get("success", True))
        elif event_type == "correction":
            self._need_engine.record_correction()
        elif event_type == "anomaly":
            self._need_engine.record_anomaly()

    def _check_speak_trigger(self, event_type: str, details: dict) -> Optional[InnerThought]:
        """检查事件是否触发主动说话"""
        if not self._emotion_engine:
            return None

        state = self._emotion_engine.state

        # 高压力 → 可能说出来
        if state.stress > 0.8:
            return InnerThought(
                content="我感到压力很大，最近的决策不太顺利",
                source="emotion",
                energy=state.stress,
                should_speak=True,
            )

        # 连续失败 → 可能说出来
        if event_type == "decision" and not details.get("success", True):
            # 检查最近的失败次数
            recent_failures = sum(1 for t in self._thoughts[-5:]
                                 if "失败" in t.content)
            if recent_failures >= 2:
                return InnerThought(
                    content="我连续犯了几次错误，需要反思一下",
                    source="event",
                    energy=0.7,
                    should_speak=True,
                )

        return None

    # ══════════════════════════════════════════════════════
    #  第二层：余韵（秒级）
    # ══════════════════════════════════════════════════════

    def _spawn_ripple(self, event_type: str, details: dict):
        """
        事件后的涟漪效应。

        不是立刻执行，而是加入队列，由后台任务延迟处理。
        这样不会阻塞主请求。
        """
        ripple = {
            "event_type": event_type,
            "details": details,
            "spawn_time": time.time(),
        }
        self._ripple_queue.append(ripple)

        # 如果后台任务没在跑，启动它
        if self._running and (not self._ripple_task or self._ripple_task.done()):
            self._ripple_task = asyncio.create_task(self._process_ripples())

    async def _process_ripples(self):
        """处理余韵队列"""
        while self._ripple_queue and self._running:
            ripple = self._ripple_queue.pop(0)

            # 延迟 1-3 秒（模拟"反应时间"）
            delay = random.uniform(1.0, 3.0)
            await asyncio.sleep(delay)

            if not self._running:
                break

            thought = self._think_ripple(ripple)
            if thought:
                self._record_thought(thought)
                self._stats["total_ripples"] += 1

                # 如果有洞察，检查要不要说出来
                if thought.should_speak and self._speak_callback:
                    try:
                        await self._speak_callback(thought.content)
                        self._stats["times_spoken"] += 1
                    except Exception:
                        pass

    def _think_ripple(self, ripple: dict) -> Optional[InnerThought]:
        """
        从事件中产生联想。

        这是"余韵"的核心——事件发生后的自然联想。
        """
        event_type = ripple["event_type"]
        details = ripple["details"]

        if not self._living_graph:
            return None

        # 从事件中提取关键词
        keywords = []
        if event_type == "decision":
            action = details.get("action", "")
            query = details.get("query", "")
            keywords = self._extract_keywords(f"{query} {action}")
        elif event_type == "correction":
            keywords = self._extract_keywords(details.get("original_query", ""))
        elif event_type == "anomaly":
            keywords = self._extract_keywords(details.get("description", ""))

        if not keywords:
            return None

        # 从 LivingGraph 扩散激活
        start_node = keywords[0]
        activations = self._living_graph.diffuse(start_node, energy=0.6, max_depth=2)

        if len(activations) < 2:
            return None

        # 生成联想内容
        labels = [a.label for a in activations[:3]]
        content = f"联想到: {' → '.join(labels)}"

        # 检查是否有洞察
        insight = self._check_insight(activations)
        if insight:
            content = f"洞察: {insight}"

        return InnerThought(
            content=content,
            source="ripple",
            energy=activations[0].energy * 0.5,
            should_speak=False,  # 余韵通常不说出来
        )

    def _check_insight(self, activations) -> Optional[str]:
        """从激活结果中检查是否有洞察"""
        # 如果激活了"成功"和"失败"节点，可能有对比洞察
        labels = [a.label for a in activations]
        has_success = "成功" in labels
        has_failure = "失败" in labels

        if has_success and has_failure:
            return "发现成功和失败的对比模式"

        # 如果激活了同一设备的多个动作
        actions = [a.label for a in activations if a.label.startswith("action:")]
        if len(actions) >= 2:
            return f"关于 {actions[0].split(':')[1]} 的多个操作被联想"

        return None

    # ══════════════════════════════════════════════════════
    #  第三层：安静联想（分钟级，概率触发）
    # ══════════════════════════════════════════════════════

    async def _idle_loop(self):
        """
        后台安静联想循环。

        两种模式：
        1. 对话沉默中（>10 秒）→ 围绕对话主题发散思考
        2. 完全空闲（>2 分钟）→ 随机联想
        """
        while self._running:
            try:
                await asyncio.sleep(5)  # 每 5 秒检查一次

                if not self._running:
                    break

                # ── 模式 1: 对话沉默中的发散思考 ──
                if self._conversation_state and self._conversation_state.check_silence():
                    silence = self._conversation_state.get_silence_duration()
                    # 10-120 秒的沉默，围绕话题发散
                    if 10 < silence < 120:
                        # 概率触发（沉默越久概率越高）
                        trigger_prob = min(0.5, 0.15 + (silence - 10) / 200)
                        if random.random() < trigger_prob:
                            thought = self._think_wander()
                            if thought:
                                self._record_thought(thought)
                                self._stats["total_idle_thinks"] += 1
                    continue

                # ── 模式 2: 完全空闲的随机联想 ──
                idle_seconds = time.time() - self._last_event_time
                if idle_seconds < 120:
                    continue

                trigger_probability = min(0.5, 0.1 + (idle_seconds - 120) / 600)
                if random.random() > trigger_probability:
                    continue

                thought = self._think_idle()
                if thought:
                    self._record_thought(thought)
                    self._stats["total_idle_thinks"] += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("安静联想异常: %s", e)

    def _think_wander(self) -> Optional[InnerThought]:
        """
        对话沉默时的发散思考。

        围绕当前对话主题，在 LivingGraph 中扩散。
        产生和对话相关的联想，不是随机的。
        """
        if not self._living_graph or not self._conversation_state:
            return None

        # 从对话话题开始扩散
        topic = self._conversation_state.current_topic
        if not topic:
            return None

        # 用话题中的关键词扩散
        activations = self._living_graph.diffuse_from_text(topic, energy=0.6, max_depth=3)

        if len(activations) < 2:
            return None

        # 生成发散想法
        labels = [a.label for a in activations[:4]]
        content = f"聊到'{topic[:15]}'时想到: {' → '.join(labels)}"

        # 记录到对话状态
        self._conversation_state.add_wandering(
            content=content,
            related_topic=topic[:30],
            energy=activations[0].energy,
        )

        return InnerThought(
            content=content,
            source="wander",
            energy=activations[0].energy * 0.4,
            should_speak=False,
        )

    def _think_idle(self) -> Optional[InnerThought]:
        """
        完全空闲时的随机联想。

        从 LivingGraph 中随机选一个活跃节点，扩散。
        """
        if not self._living_graph:
            return None

        nodes = self._living_graph._nodes
        if not nodes:
            return None

        sorted_nodes = sorted(
            nodes.values(),
            key=lambda n: n.current_activation(),
            reverse=True,
        )
        candidates = sorted_nodes[:min(20, len(sorted_nodes))]
        if not candidates:
            return None

        start_node = random.choice(candidates)
        activations = self._living_graph.diffuse(
            start_node.id, energy=0.5, max_depth=2
        )

        if len(activations) < 2:
            return None

        labels = [a.label for a in activations[:4]]
        content = f"安静时想到: {' → '.join(labels)}"

        return InnerThought(
            content=content,
            source="idle",
            energy=activations[0].energy * 0.3,
            should_speak=False,
        )

    # ══════════════════════════════════════════════════════
    #  工具方法
    # ══════════════════════════════════════════════════════

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本中提取关键词"""
        keywords = set()
        devices = ["灯", "锁", "门", "电机", "light", "lock", "door", "motor"]
        for d in devices:
            if d in text.lower():
                keywords.add(d)
        actions = ["开", "关", "打开", "关闭", "前进", "后退", "左转", "右转"]
        for a in actions:
            if a in text:
                keywords.add(a)
        return list(keywords)[:5]

    def _record_thought(self, thought: InnerThought):
        """记录想法"""
        self._thoughts.append(thought)
        if len(self._thoughts) > self._max_thoughts:
            self._thoughts = self._thoughts[-self._max_thoughts:]

    def record_observation(self, observation: str):
        """外部注入观察"""
        self._last_event_time = time.time()
        # 观察也会产生轻微的余韵
        if self._living_graph:
            keywords = self._extract_keywords(observation)
            if keywords:
                self._spawn_ripple("observation", {"query": observation})

    # ══════════════════════════════════════════════════════
    #  外部接口
    # ══════════════════════════════════════════════════════

    def get_recent_thoughts(self, count: int = 10) -> list[dict]:
        return [t.to_dict() for t in self._thoughts[-count:]]

    def get_narrative(self) -> str:
        """自我叙事——"我最近在想什么" """
        if not self._thoughts:
            return ""

        recent = self._thoughts[-5:]
        lines = ["## 我的内心独白"]
        for t in recent:
            if t.source == "ripple":
                lines.append(f"- {t.content}")
            elif t.source == "idle":
                lines.append(f"- {t.content}")
            elif t.source == "event":
                lines.append(f"- {t.content}")
            elif t.source == "emotion":
                lines.append(f"- {t.content}")
            elif t.source == "need":
                lines.append(f"- {t.content}")

        # 时间感
        uptime_hours = (time.time() - self._stats.get("start_time", time.time())) / 3600
        if uptime_hours > 1:
            lines.append(f"- 我已经运行了 {uptime_hours:.1f} 小时")

        # 事件密度
        if self._event_count > 0:
            events_per_hour = self._event_count / max(0.1, uptime_hours)
            if events_per_hour > 10:
                lines.append("- 最近挺忙的")
            elif events_per_hour < 1:
                lines.append("- 最近比较清闲")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        uptime = time.time() - self._stats.get("start_time", time.time())
        idle_seconds = time.time() - self._last_event_time
        return {
            **self._stats,
            "running": self._running,
            "uptime_seconds": int(uptime),
            "idle_seconds": int(idle_seconds),
            "thoughts_count": len(self._thoughts),
            "ripple_queue_size": len(self._ripple_queue),
            "speak_rate": (
                self._stats["times_spoken"] /
                max(1, self._stats["times_spoken"] + self._stats["times_silent"])
            ),
        }
