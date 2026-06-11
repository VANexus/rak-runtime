"""
Agentic RAG — 多跳检索推理引擎

不同于单次 RAG（query → retrieve → answer），Agentic RAG 实现：
1. 初始检索（粗粒度）
2. 推理链（判断信息是否充分）
3. 迭代检索（精细化查询）
4. 综合推理（跨文档推理）

参考：
- arXiv:2603.07379 形式化框架
- arXiv:2603.09192 双树架构（方法即节点）
- "嵌套学习"（Nested Learning）范式
"""

import json
import logging
import time
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ReasoningStep(Enum):
    """推理步骤类型"""
    RETRIEVE = "retrieve"       # 检索
    REASON = "reason"           # 推理
    REFINE = "refine"           # 精化查询
    SYNTHESIZE = "synthesize"   # 综合
    STOP = "stop"               # 停止


@dataclass
class RetrievalResult:
    """检索结果"""
    content: str
    source: str                # 来源标识
    similarity: float          # 相似度得分
    metadata: Dict = field(default_factory=dict)


@dataclass
class ReasoningState:
    """推理状态"""
    step: int = 0
    max_steps: int = 5
    original_query: str = ""
    current_query: str = ""
    accumulated_evidence: List[str] = field(default_factory=list)
    reasoning_chain: List[Dict] = field(default_factory=list)
    confidence: float = 0.0
    answer: str = ""


@dataclass
class AgenticRAGResult:
    """Agentic RAG 最终结果"""
    answer: str                           # 最终答案
    confidence: float                     # 置信度 [0, 1]
    reasoning_chain: List[Dict]           # 推理链
    total_retrievals: int                 # 总检索次数
    total_steps: int                      # 总推理步数
    evidence: List[str]                   # 累积证据
    elapsed_ms: float                     # 耗时


class AgenticRAG:
    """
    Agentic RAG 引擎 — 多跳检索推理。

    核心循环：
    1. RETRIEVE: 用当前查询检索记忆
    2. REASON: 判断证据是否充分
    3. REFINE: 如果不充分，生成更精确的子查询
    4. SYNTHESIZE: 综合所有证据生成答案

    类比：人类的"深思熟虑"过程——不是一次联想就下结论，
    而是反复检索、验证、补充，直到信息充分。
    """

    def __init__(self,
                 retrieve_fn: Callable[[str, int], List[RetrievalResult]],
                 reason_fn: Optional[Callable[[str, List[str]], Dict]] = None,
                 max_steps: int = 5,
                 confidence_threshold: float = 0.8):
        """
        Args:
            retrieve_fn: 检索函数 (query, top_k) -> [RetrievalResult]
            reason_fn: 推理函数 (query, evidence) -> {"sufficient": bool, "answer": str, "refined_query": str}
                       如果为 None，使用内置规则推理
            max_steps: 最大推理步数
            confidence_threshold: 置信度阈值（超过则停止）
        """
        self.retrieve_fn = retrieve_fn
        self.reason_fn = reason_fn or self._default_reason
        self.max_steps = max_steps
        self.confidence_threshold = confidence_threshold

    def query(self, question: str, top_k: int = 5) -> AgenticRAGResult:
        """
        执行 Agentic RAG 查询。

        Args:
            question: 用户问题
            top_k: 每轮检索的候选数

        Returns:
            AgenticRAGResult: 包含答案、推理链、证据等
        """
        start_time = time.time()
        state = ReasoningState(
            original_query=question,
            current_query=question,
            max_steps=self.max_steps,
        )

        logger.info("[AgenticRAG] 开始查询: '%s' (max_steps=%s)", question, self.max_steps)

        while state.step < self.max_steps:
            state.step += 1
            logger.info("[AgenticRAG] 步骤 %s/%s: 查询='%s'", state.step, self.max_steps, state.current_query)

            # 1. RETRIEVE
            retrieval_results = self._retrieve(state.current_query, top_k)
            new_evidence = [r.content for r in retrieval_results]
            state.accumulated_evidence.extend(new_evidence)

            state.reasoning_chain.append({
                "step": state.step,
                "action": ReasoningStep.RETRIEVE.value,
                "query": state.current_query,
                "results_count": len(retrieval_results),
                "top_similarity": retrieval_results[0].similarity if retrieval_results else 0,
            })

            logger.info("[AgenticRAG] 检索到 %d 条结果, 累积证据 %d 条",
                        len(retrieval_results), len(state.accumulated_evidence))

            # 2. REASON — 判断证据是否充分
            reasoning_result = self.reason_fn(question, state.accumulated_evidence)

            state.reasoning_chain.append({
                "step": state.step,
                "action": ReasoningStep.REASON.value,
                "sufficient": reasoning_result.get("sufficient", False),
                "confidence": reasoning_result.get("confidence", 0),
            })

            state.confidence = reasoning_result.get("confidence", 0)

            # 3. 判断是否可以停止
            if reasoning_result.get("sufficient", False) or \
               state.confidence >= self.confidence_threshold:
                state.answer = reasoning_result.get("answer", "")
                state.reasoning_chain.append({
                    "step": state.step,
                    "action": ReasoningStep.STOP.value,
                    "reason": "证据充分",
                    "confidence": state.confidence,
                })
                logger.info("[AgenticRAG] 证据充分，停止 (confidence=%.2f)", state.confidence)
                break

            # 4. REFINE — 生成更精确的子查询
            refined_query = reasoning_result.get("refined_query", "")
            if refined_query and refined_query != state.current_query:
                state.current_query = refined_query
                state.reasoning_chain.append({
                    "step": state.step,
                    "action": ReasoningStep.REFINE.value,
                    "new_query": refined_query,
                })
                logger.info("[AgenticRAG] 精化查询: '%s'", refined_query)
            else:
                # 没有更精确的查询，尝试分解问题
                sub_queries = self._decompose_query(question, state.accumulated_evidence)
                if sub_queries:
                    state.current_query = sub_queries[0]
                    state.reasoning_chain.append({
                        "step": state.step,
                        "action": ReasoningStep.REFINE.value,
                        "new_query": sub_queries[0],
                        "method": "decompose",
                    })
                else:
                    # 无法进一步精化，停止
                    state.answer = reasoning_result.get("answer", "")
                    state.reasoning_chain.append({
                        "step": state.step,
                        "action": ReasoningStep.STOP.value,
                        "reason": "无法进一步精化",
                    })
                    break

        # 5. SYNTHESIZE — 综合最终答案
        if not state.answer:
            state.answer = self._synthesize(question, state.accumulated_evidence)

        elapsed_ms = (time.time() - start_time) * 1000

        result = AgenticRAGResult(
            answer=state.answer,
            confidence=state.confidence,
            reasoning_chain=state.reasoning_chain,
            total_retrievals=sum(1 for s in state.reasoning_chain
                                if s["action"] == ReasoningStep.RETRIEVE.value),
            total_steps=state.step,
            evidence=state.accumulated_evidence,
            elapsed_ms=elapsed_ms,
        )

        logger.info("[AgenticRAG] 完成: %d 步, %d 次检索, confidence=%.2f, 耗时=%.0fms",
                    state.step, result.total_retrievals, state.confidence, elapsed_ms)

        return result

    def _retrieve(self, query: str, top_k: int) -> List[RetrievalResult]:
        """执行检索"""
        try:
            results = self.retrieve_fn(query, top_k)
            return results if results else []
        except Exception as e:
            logger.warning("[AgenticRAG] 检索失败: %s", e)
            return []

    def _default_reason(self, query: str, evidence: List[str]) -> Dict:
        """
        默认推理函数（规则引擎）。
        当没有 LLM 时使用，基于关键词匹配和证据数量判断。
        """
        if not evidence:
            return {
                "sufficient": False,
                "confidence": 0.0,
                "answer": "",
                "refined_query": query,
            }

        # 简单规则：证据越多，置信度越高
        evidence_count = len(evidence)
        unique_evidence = len(set(evidence))

        # 检查证据中是否包含查询关键词
        query_keywords = set(query.replace("？", "").replace("?", "").split())
        keyword_hits = 0
        for ev in evidence:
            for kw in query_keywords:
                if kw in ev:
                    keyword_hits += 1
                    break

        keyword_ratio = keyword_hits / max(1, len(query_keywords))
        confidence = min(1.0, (unique_evidence * 0.15) + (keyword_ratio * 0.5))

        sufficient = confidence >= self.confidence_threshold or evidence_count >= 5

        # 生成简单答案（取最相关的证据）
        answer = ""
        if evidence:
            answer = evidence[0]  # 取第一条（最相关）

        # 生成精化查询
        refined_query = ""
        if not sufficient and query_keywords:
            # 用未命中的关键词生成新查询
            unmatched = [kw for kw in query_keywords
                        if not any(kw in ev for ev in evidence)]
            if unmatched:
                refined_query = " ".join(unmatched)

        return {
            "sufficient": sufficient,
            "confidence": confidence,
            "answer": answer,
            "refined_query": refined_query,
        }

    def _decompose_query(self, query: str, evidence: List[str]) -> List[str]:
        """
        分解复杂问题为子问题。
        简单实现：按连接词分割。
        """
        separators = ["并且", "而且", "同时", "还有", "另外",
                      "and", "also", "additionally"]
        sub_queries = [query]
        for sep in separators:
            new_queries = []
            for q in sub_queries:
                parts = q.split(sep)
                new_queries.extend([p.strip() for p in parts if p.strip()])
            sub_queries = new_queries

        # 去掉原始查询
        return [q for q in sub_queries if q != query and len(q) > 2]

    def _synthesize(self, query: str, evidence: List[str]) -> str:
        """
        综合所有证据生成最终答案。
        简单实现：返回最相关的证据。
        """
        if not evidence:
            return "抱歉，未找到相关信息。"

        # 返回第一条证据作为答案
        return evidence[0]


class AgenticRAGWithLLM(AgenticRAG):
    """
    带 LLM 的 Agentic RAG。

    使用 LLM 进行推理和综合，而不是规则引擎。
    当 LLM 不可用时降级到父类的规则推理。
    """

    def __init__(self, retrieve_fn, llm_client=None, **kwargs):
        super().__init__(retrieve_fn, **kwargs)
        self.llm_client = llm_client

        if llm_client:
            # 用 LLM 推理函数替换默认的
            self.reason_fn = self._llm_reason

    def _llm_reason(self, query: str, evidence: List[str]) -> Dict:
        """使用 LLM 进行推理"""
        if not self.llm_client:
            return self._default_reason(query, evidence)

        try:
            evidence_text = "\n".join(f"[{i+1}] {ev}" for i, ev in enumerate(evidence[:10]))

            prompt = f"""基于以下证据，判断是否足以回答问题。

问题：{query}

证据：
{evidence_text if evidence else "（无证据）"}

请返回 JSON：
{{
  "sufficient": true/false,
  "confidence": 0.0-1.0,
  "answer": "如果证据充分，给出答案",
  "refined_query": "如果证据不充分，给出更精确的检索查询"
}}"""

            response = self.llm_client.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    break

            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]

            result = json.loads(text)
            return {
                "sufficient": result.get("sufficient", False),
                "confidence": result.get("confidence", 0),
                "answer": result.get("answer", ""),
                "refined_query": result.get("refined_query", ""),
            }

        except Exception as e:
            logger.warning("[AgenticRAG] LLM 推理失败: %s，降级到规则引擎", e)
            return self._default_reason(query, evidence)

    def _synthesize(self, query: str, evidence: List[str]) -> str:
        """使用 LLM 综合最终答案"""
        if not self.llm_client or not evidence:
            return super()._synthesize(query, evidence)

        try:
            evidence_text = "\n".join(f"[{i+1}] {ev}" for i, ev in enumerate(evidence[:10]))

            response = self.llm_client.messages.create(
                model="mimo-v2.5-pro",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": f"基于以下证据，简洁回答问题。\n\n问题：{query}\n\n证据：\n{evidence_text}"
                }],
            )

            for block in response.content:
                if hasattr(block, "text"):
                    return block.text.strip()

        except Exception as e:
            logger.warning("[AgenticRAG] LLM 综合失败: %s", e)

        return super()._synthesize(query, evidence)
