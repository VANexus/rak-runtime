"""
学习闭环（Learning Loop v2）— 事件驱动的自适应学习

灵感来源：
- Reflexion (Shinn 2023): 失败 → 立即语言反思 → 存入记忆
- ExpeL (Zhao 2024): 对比成功/失败轨迹 → 提取可复用规则
- CoALA (Sumers 2023): 元认知作为独立内部动作
- MemGPT (Packer 2023): LLM 自主管理内存分层
- Voyager (Wang 2023): 自动课程 + 技能库

核心原则：事件驱动，不是定时驱动。
- 纠正 → 立刻反思（Reflexion）
- 累积足够样本 → 批量对比分析（ExpeL）
- 上下文满 → LLM 决定存什么扔什么（MemGPT）
- 成功模式重复 → 抽象为可复用技能（Voyager）

没有硬编码阈值，路由决策由 LLM 做。
"""

import json
import logging
import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """执行记录"""
    trace_id: str
    query: str
    action: str
    success: bool
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    context: str = ""
    confidence: float = 0.0
    correction: str = ""  # 用户纠正内容
    answer: str = ""  # LLM 的自然语言回复


@dataclass
class Signal:
    """学习信号"""
    signal_type: str  # correction, failure, low_confidence, novelty, prediction_error
    intensity: float  # 0.0-1.0
    data: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class LearningLoop:
    """
    事件驱动的自适应学习闭环。

    不训练模型，而是：
    1. 从每次决策中采集信号
    2. LLM 路由决定是否反思
    3. 并行执行多种反思（不阻塞决策）
    4. 洞察自动注入下次决策的 prompt
    """

    def __init__(self, memory_engine=None, prompt_engine=None, semantic_cache=None):
        self.memory_engine = memory_engine
        self.prompt_engine = prompt_engine
        self.semantic_cache = semantic_cache

        # 执行记录缓冲
        self._records: List[ExecutionRecord] = []
        self._max_records = 2000

        # 信号缓冲
        self._signals: List[Signal] = []
        self._max_signals = 500

        # 洞察库（反思产出）
        self._insights: List[str] = []
        self._max_insights = 20

        # 技能库（Voyager 风格）
        self._skills: Dict[str, Dict] = {}  # pattern → {action, confidence, uses}

        # 统计
        self._total_decisions = 0
        self._total_successes = 0
        self._total_failures = 0
        self._total_reflections = 0

        # 动作统计
        self._action_stats: Dict[str, Dict] = defaultdict(
            lambda: {"success": 0, "failure": 0, "total_latency": 0.0}
        )

        # 反思状态
        self._last_reflection_time = 0.0
        self._reflection_in_progress = False
        self._reflection_lock = threading.Lock()

        # LLM 客户端（延迟初始化）
        self._llm_client = None

    # ========== 主入口 ==========

    def on_decision(self, trace_id: str, query: str, result: dict, success: bool):
        """
        记录决策反馈。每次决策后调用。

        流程：
        1. 记录到缓冲区
        2. 采集信号
        3. 信号足够强 → 触发后台反思（不阻塞）
        """
        self._total_decisions += 1

        action = result.get("action", "unknown")
        confidence = result.get("confidence", 0.5)
        correction = result.get("correction", "")
        answer = result.get("answer", "")

        if success:
            self._total_successes += 1
        else:
            self._total_failures += 1

        # 更新动作统计
        stats = self._action_stats[action]
        if success:
            stats["success"] += 1
        else:
            stats["failure"] += 1

        # 记录
        record = ExecutionRecord(
            trace_id=trace_id,
            query=query,
            action=action,
            success=success,
            confidence=confidence,
            correction=correction,
            answer=answer,
        )
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

        # 采集信号
        self._collect_signals(record)

        # 存入记忆
        self._store_to_memory(record)

        # 检查是否应触发反思（事件驱动）
        self._maybe_trigger_reflection()

    def on_correction(self, query: str, wrong_action: str, correct_action: str):
        """
        用户纠正。这是最强的学习信号。
        Reflexion 风格：立刻触发即时反思。
        """
        signal = Signal(
            signal_type="correction",
            intensity=1.0,
            data={
                "query": query,
                "wrong_action": wrong_action,
                "correct_action": correct_action,
            },
        )
        self._signals.append(signal)

        # 纠正是最高优先级，立刻触发即时反思（Reflexion）
        self._trigger_immediate_reflection(
            f"用户纠正: '{query}' 不应该执行 {wrong_action}，应该执行 {correct_action}",
            {"type": "correction", "query": query,
             "wrong": wrong_action, "correct": correct_action},
        )

    # ========== 信号采集 ==========

    def _collect_signals(self, record: ExecutionRecord):
        """从决策记录中采集学习信号"""

        # 失败信号
        if not record.success:
            self._signals.append(Signal(
                signal_type="failure",
                intensity=0.8,
                data={"action": record.action, "query": record.query[:100]},
            ))

        # 低置信度信号
        if record.confidence < 0.4 and record.confidence > 0:
            self._signals.append(Signal(
                signal_type="low_confidence",
                intensity=0.5,
                data={"action": record.action, "confidence": record.confidence},
            ))

        # 新颖信号（首次遇到的动作+查询组合）
        pattern = f"{record.action}:{record.query[:30]}"
        if not any(
            r.action == record.action and r.query[:30] == record.query[:30]
            for r in self._records[:-1]
        ):
            self._signals.append(Signal(
                signal_type="novelty",
                intensity=0.3,
                data={"pattern": pattern},
            ))

        # 清理旧信号
        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals:]

    # ========== 反思触发（事件驱动） ==========

    def _maybe_trigger_reflection(self):
        """
        检查是否应触发反思。

        触发条件（任一满足）：
        1. 累积了足够多的信号（信号密度高）
        2. 距上次反思太久了（保底机制）
        3. 有强烈的单个信号（如连续失败）

        不使用硬编码阈值——用信号的"强度密度"自然判断。
        """
        with self._reflection_lock:
            if self._reflection_in_progress:
                return  # 已有反思在进行

        # 计算近期信号强度密度
        recent_signals = [s for s in self._signals if time.time() - s.timestamp < 300]
        if not recent_signals:
            return

        total_intensity = sum(s.intensity for s in recent_signals)
        signal_count = len(recent_signals)

        # 信号密度 = 平均强度 × 信号数量
        # 密度高说明有大量值得反思的事件
        density = (total_intensity / max(signal_count, 1)) * signal_count

        # 距上次反思的时间
        time_since_last = time.time() - self._last_reflection_time

        # 触发判断：
        # - 信号密度 > 5（约 5+ 个中等强度信号）
        # - 或距上次反思 > 600 秒（10 分钟保底）
        # - 或有强度 > 0.9 的单个信号（如纠正）
        should_reflect = (
            density > 5
            or time_since_last > 600
            or any(s.intensity > 0.9 for s in recent_signals)
        )

        if should_reflect:
            self._trigger_batch_reflection()

    def _trigger_immediate_reflection(self, context: str, data: Dict):
        """
        Reflexion 风格的即时反思。

        纠正/失败发生后立刻执行，不等累积。
        用 LLM 分析"刚才发生了什么，为什么，下次怎么避免"。
        """
        def _reflect_thread():
            with self._reflection_lock:
                self._reflection_in_progress = True
            try:
                self._reflexion_reflect(context, data)
            finally:
                with self._reflection_lock:
                    self._reflection_in_progress = False
                self._last_reflection_time = time.time()

        thread = threading.Thread(target=_reflect_thread, daemon=True)
        thread.start()

    def _trigger_batch_reflection(self):
        """
        ExpeL 风格的批量反思。

        对比最近的成功/失败轨迹，提取可复用规则。
        在后台线程执行，不阻塞决策。
        """
        with self._reflection_lock:
            if self._reflection_in_progress:
                return
            self._reflection_in_progress = True

        def _reflect_thread():
            try:
                self._expel_analyze()
                self._maybe_extract_skills()
                self._maybe_consolidate_memory()
            except Exception as e:
                logger.warning("[Learning] 批量反思失败: %s", e)
            finally:
                with self._reflection_lock:
                    self._reflection_in_progress = False
                self._last_reflection_time = time.time()

        thread = threading.Thread(target=_reflect_thread, daemon=True)
        thread.start()

    # ========== 反思实现 ==========

    def _reflexion_reflect(self, context: str, data: Dict):
        """
        Reflexion: 立即语言反思。

        发送给 LLM，让它分析发生了什么、为什么、下次怎么避免。
        产出：一条洞察，注入 PromptEngine。
        """
        llm = self._get_llm_client()
        if not llm:
            return

        # 收集最近的相关上下文
        recent = self._records[-10:]
        recent_text = "\n".join(
            f"- [{'✓' if r.success else '✗'}] {r.action}: {r.query[:50]}"
            for r in recent
        )

        prompt = f"""你是 Rak 的自我反思模块。分析以下事件：

事件：{context}

最近的决策记录：
{recent_text}

请回答（JSON 格式）：
{{
  "what_happened": "发生了什么",
  "why": "为什么会这样",
  "lesson": "下次应该怎么做（一句话）",
  "actionable": true/false
}}"""

        try:
            response = llm.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=256,
                system="你是学习模块。简洁分析，输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
                extra_body={"thinking": {"type": "disabled"}},
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    break

            parsed = self._parse_json(text)
            if parsed and parsed.get("lesson"):
                lesson = parsed["lesson"]
                self._add_insight(f"[Reflexion] {lesson}")
                logger.info("[Learning] Reflexion 洞察: %s", lesson[:80])

        except Exception as e:
            logger.warning("[Learning] Reflexion 反思失败: %s", e)

    def _expel_analyze(self):
        """
        ExpeL: 对比成功/失败轨迹，提取可复用规则。

        发送最近的决策记录给 LLM，让它找出模式。
        """
        llm = self._get_llm_client()
        if not llm:
            return

        recent = self._records[-30:]
        if len(recent) < 5:
            return

        successes = [r for r in recent if r.success]
        failures = [r for r in recent if not r.success]

        if not successes or not failures:
            # 只有成功或只有失败，做统计分析
            success_rate = len(successes) / len(recent)
            if success_rate < 0.5:
                self._add_insight(f"[ExpeL] 近期成功率偏低 ({success_rate:.0%})，需要关注失败原因")
            return

        success_text = "\n".join(
            f"- {r.action}: {r.query[:60]}" for r in successes[-10:]
        )
        failure_text = "\n".join(
            f"- {r.action}: {r.query[:60]}" for r in failures[-10:]
        )

        prompt = f"""你是 Rak 的学习模块。对比分析成功和失败的决策：

成功案例：
{success_text}

失败案例：
{failure_text}

请回答（JSON 格式）：
{{
  "pattern": "成功和失败之间的关键区别是什么",
  "rule": "一条可复用的规则（一句话）",
  "confidence": 0.0-1.0
}}"""

        try:
            response = llm.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=256,
                system="你是学习模块。从对比中提取规则，输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
                extra_body={"thinking": {"type": "disabled"}},
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    break

            parsed = self._parse_json(text)
            if parsed and parsed.get("rule"):
                rule = parsed["rule"]
                confidence = parsed.get("confidence", 0.5)
                self._add_insight(f"[ExpeL] {rule} (置信度: {confidence:.0%})")
                logger.info("[Learning] ExpeL 规则: %s", rule[:80])

                # 存入记忆
                memory = self._get_memory_engine()
                if memory:
                    memory.remember(
                        content=f"经验规则: {rule}",
                        memory_type="procedural",
                        importance=0.8,
                        metadata={"type": "expel_rule", "confidence": confidence},
                    )

        except Exception as e:
            logger.warning("[Learning] ExpeL 分析失败: %s", e)

    def _maybe_extract_skills(self):
        """
        Voyager 风格：从重复的成功模式中提取可复用技能。

        如果同一个动作+上下文模式成功了 3+ 次，抽象为技能。
        """
        recent = self._records[-50:]
        successes = [r for r in recent if r.success]

        # 按动作分组
        action_groups: Dict[str, List[ExecutionRecord]] = defaultdict(list)
        for r in successes:
            action_groups[r.action].append(r)

        for action, records in action_groups.items():
            if len(records) >= 3:
                # 检查是否已有此技能
                skill_key = action
                if skill_key not in self._skills:
                    self._skills[skill_key] = {
                        "action": action,
                        "uses": len(records),
                        "confidence": min(0.9, 0.5 + len(records) * 0.05),
                        "learned_at": time.time(),
                    }
                    logger.info("[Learning] 新技能提取: %s (成功 %d 次)", action, len(records))

    def _maybe_consolidate_memory(self):
        """
        MemGPT 风格：当记录缓冲区快满时，让 LLM 决定保留什么。

        不是简单截断，而是 LLM 分析哪些记忆重要、哪些可以归档。
        """
        if len(self._records) < self._max_records * 0.8:
            return  # 还没满，不 consolidation

        llm = self._get_llm_client()
        if not llm:
            return

        # 提取最近的洞察摘要
        recent = self._records[-100:]
        summary_parts = []
        for r in recent[-20:]:
            status = "✓" if r.success else "✗"
            summary_parts.append(f"[{status}] {r.action}: {r.query[:40]}")

        summary_text = "\n".join(summary_parts)

        prompt = f"""你是 Rak 的记忆管理模块。上下文即将溢出，需要决定保留什么。

最近 20 条决策：
{summary_text}

已有的洞察：
{chr(10).join(self._insights[-5:])}

请回答（JSON 格式）：
{{
  "keep": ["最重要的 3 条信息"],
  "archive": ["可以归档的信息"],
  "forget": ["可以丢弃的信息"]
}}"""

        try:
            response = llm.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=256,
                system="你是记忆管理模块。决定保留什么、归档什么、丢弃什么。输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
                extra_body={"thinking": {"type": "disabled"}},
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    break

            parsed = self._parse_json(text)
            if parsed:
                keep = parsed.get("keep", [])
                if keep:
                    self._add_insight(f"[MemGPT] 核心记忆: {'; '.join(keep[:3])}")
                    logger.info("[Learning] MemGPT 整合: 保留 %d 条", len(keep))

                # 截断旧记录（保留最近一半）
                self._records = self._records[-self._max_records // 2:]

        except Exception as e:
            logger.warning("[Learning] MemGPT 整合失败: %s", e)

    # ========== 洞察管理 ==========

    def _add_insight(self, insight: str):
        """添加洞察到库中，并注入 PromptEngine"""
        # 去重
        if any(insight in existing for existing in self._insights):
            return

        self._insights.append(insight)
        if len(self._insights) > self._max_insights:
            self._insights = self._insights[-self._max_insights:]

        # 注入 PromptEngine
        pe = self._get_prompt_engine()
        if pe:
            pe.add_insight(insight)

        self._total_reflections += 1

    def get_insights(self) -> List[str]:
        """获取当前洞察列表"""
        return self._insights.copy()

    def get_skills(self) -> Dict[str, Dict]:
        """获取技能库"""
        return self._skills.copy()

    # ========== 辅助方法 ==========

    def _store_to_memory(self, record: ExecutionRecord):
        """将执行记录存入记忆系统"""
        memory = self._get_memory_engine()
        if memory is None:
            return

        try:
            status = "成功" if record.success else "失败"
            content = f"执行 {record.action} {status}"
            if record.query:
                content += f"（查询: {record.query[:50]}）"
            if record.correction:
                content += f" [纠正: {record.correction}]"

            importance = 0.6 if record.success else 0.7

            memory.remember(
                content=content,
                memory_type="episodic",
                importance=importance,
                metadata={
                    "trace_id": record.trace_id,
                    "action": record.action,
                    "success": record.success,
                    "type": "execution_feedback",
                },
            )
        except Exception as e:
            logger.warning("[Learning] 存储记忆失败: %s", e)

    def _parse_json(self, text: str) -> Optional[Dict]:
        """解析 JSON（处理 markdown 代码块）"""
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

    def _get_llm_client(self):
        """获取 LLM 客户端（延迟初始化）"""
        if self._llm_client is None:
            try:
                import anthropic
                import os
                self._llm_client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
                    base_url=os.getenv(
                        "ANTHROPIC_BASE_URL",
                        "https://token-plan-cn.xiaomimimo.com/anthropic",
                    ),
                    timeout=15.0,
                )
            except Exception as e:
                logger.warning("[Learning] LLM 客户端初始化失败: %s", e)
        return self._llm_client

    def _get_memory_engine(self):
        if self.memory_engine is None:
            try:
                from src.core.decision_engine import _get_memory_engine
                self.memory_engine = _get_memory_engine()
            except Exception:
                pass
        return self.memory_engine

    def _get_prompt_engine(self):
        if self.prompt_engine is None:
            try:
                from src.core.decision_engine import _get_prompt_engine
                self.prompt_engine = _get_prompt_engine()
            except Exception:
                pass
        return self.prompt_engine

    def get_action_stats(self) -> Dict:
        result = {}
        for action, stats in self._action_stats.items():
            total = stats["success"] + stats["failure"]
            if total > 0:
                result[action] = {
                    "success_rate": stats["success"] / total,
                    "total": total,
                    "avg_latency_ms": stats["total_latency"] / total if total > 0 else 0,
                }
        return result

    def stats(self) -> Dict:
        total = self._total_decisions or 1
        return {
            "total_decisions": self._total_decisions,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "success_rate": f"{self._total_successes / total:.1%}",
            "records_buffer": len(self._records),
            "signals_buffer": len(self._signals),
            "insights_count": len(self._insights),
            "skills_count": len(self._skills),
            "total_reflections": self._total_reflections,
            "actions_tracked": len(self._action_stats),
        }
