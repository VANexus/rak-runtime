"""
文本语气情绪感知 — 从用户措辞推断情绪并融入六维情绪态（P2-4）。

纯词典法（<1ms、零外部依赖、禁 torch/本地推理），支持：
- 中英情绪关键词 → 六维增量
- 否定词削弱（"不太满意" ≠ 满意）
- 标点强度（感叹号/连续问号抬升强度）

设计原则（AGENTS.md）：
- 热路径不走 LLM（不加延迟）；perceive_llm() 供调用方显式复核
- 优雅降级：任何异常返回中性结果
"""

import logging
import re

logger = logging.getLogger("rak.emotion_perception")

# 情绪词典：关键词 → 情绪类别（命中即计分，多的为支配情绪）
_LEXICON = {
    "anger": ["滚", "烦死", "气死", "混蛋", "废物", "闭嘴", "恼火", "可恶",
              "讨厌", "荒谬", "angry", "fuck", "damn", "stupid"],
    "sadness": ["难过", "伤心", "失望", "沮丧", "悲痛", "郁闷", "心烦", "低落",
                "sad", "depressed", "upset"],
    "joy": ["谢谢", "太好了", "不错", "厉害", "真棒", "太棒", "开心", "高兴", "满意",
            "喜欢", " great", "thanks", "happy", "nice", "love it"],
    "fear": ["害怕", "担心", "紧张", "危险", "可怕", "不安", "焦虑",
             "scared", "afraid", "worried"],
    "surprise": ["怎么可能", "竟然", "居然", "没想到", "惊了", "什么？？",
                 "wow", "no way"],
    "trust": ["相信", "靠谱", "放心", "专业", "稳当", "trust", "reliable"],
}

# 否定词：出现在情绪词前方 2 字窗口内时削弱并翻转效价
# 注意：单字"非"不能收——"非常"是程度副词不是否定（曾致"非常谢谢"误判为消极）
_NEGATORS = ("不", "没", "别", "无", "not", "never")

# 感知情绪 → 六维增量（EmotionState 六维 0-1，中性 0.5；fear/sadness 中性 0.1）
_DIM_DELTAS = {
    "anger":    {"anger": +0.25, "joy": -0.15, "trust": -0.10},
    "sadness":  {"sadness": +0.25, "joy": -0.15},
    "joy":      {"joy": +0.25, "trust": +0.10},
    "fear":     {"fear": +0.20, "surprise": +0.10},
    "surprise": {"surprise": +0.30},
    "trust":    {"trust": +0.20},
}

_EXCLAIM_RE = re.compile(r"[!！]{1,}")
_QUESTION_RE = re.compile(r"[?？]{2,}")


class EmotionPerception:
    """文本语气情绪感知器"""

    def perceive(self, text: str) -> dict:
        """
        感知一句话的情绪。

        返回:
            {"emotion": 六维之一或 neutral, "intensity": 0-1,
             "method": "lexicon", "matched": [命中词]}
        """
        result = {"emotion": "neutral", "intensity": 0.0,
                  "method": "lexicon", "matched": []}
        if not text or len(text) < 2:
            return result

        try:
            # scores: emotion -> {"w": 总权重, "neg": 被否定权重}
            scores: dict[str, dict] = {}
            for emotion, keywords in _LEXICON.items():
                for kw in keywords:
                    kw = kw.strip()
                    if kw and kw in text:
                        idx = text.find(kw)
                        prefix = text[max(0, idx - 2):idx]
                        negated = any(neg in prefix for neg in _NEGATORS)
                        w = 0.3 if negated else 1.0
                        entry = scores.setdefault(emotion, {"w": 0.0, "neg": 0.0})
                        entry["w"] += w
                        if negated:
                            entry["neg"] += w
                        result["matched"].append(kw)

            if not scores:
                return result

            emotion = max(scores, key=lambda e: scores[e]["w"])
            intensity = min(1.0, 0.4 + 0.1 * (len(scores) - 1))
            # 标点强度
            if _EXCLAIM_RE.search(text):
                intensity = min(1.0, intensity + 0.2)
            if _QUESTION_RE.search(text) and emotion == "surprise":
                intensity = min(1.0, intensity + 0.2)

            # 否定占比过半 → 翻转效价（"不太满意"→轻度消极；仅对效价明确的类别）
            entry = scores[emotion]
            if entry["w"] > 0 and entry["neg"] / entry["w"] >= 0.5:
                if emotion == "joy":
                    emotion, intensity = "sadness", min(0.5, intensity * 0.6)
                elif emotion in ("anger", "sadness", "fear"):
                    intensity *= 0.3  # 否定的负面词 = 情绪缓和（"不生气"）

            result["emotion"] = emotion
            result["intensity"] = round(intensity, 2)
            return result
        except Exception as e:
            logger.warning("情绪感知失败（返回中性）: %s", e)
            return result

    def perceive_llm(self, text: str, llm_client) -> dict:
        """LLM 复核通道（显式调用，热路径不用）"""
        import json
        prompt = (
            "判断这句话的用户情绪，只输出 JSON："
            '{"emotion":"joy|sadness|anger|fear|surprise|trust|neutral",'
            '"intensity":0.0到1.0}。句子：' + text[:200]
        )
        try:
            resp = llm_client.messages.create(
                model=getattr(llm_client, "model_name", "") or "claude-3-haiku",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            data = json.loads(resp.content[0].text)
            emotion = data.get("emotion", "neutral")
            if emotion in _DIM_DELTAS or emotion == "neutral":
                return {"emotion": emotion,
                        "intensity": float(data.get("intensity", 0.0)),
                        "method": "llm", "matched": []}
        except Exception as e:
            logger.warning("LLM 情绪复核失败（回退词典）: %s", e)
        return self.perceive(text)

    def apply_to(self, emotion_engine, text: str) -> dict:
        """感知并融入情绪引擎的六维状态；中性/低强度时不动状态"""
        perception = self.perceive(text)
        emotion = perception["emotion"]
        intensity = perception["intensity"]

        if emotion == "neutral" or intensity < 0.3:
            return perception

        try:
            state = emotion_engine.state
            for dim, delta in _DIM_DELTAS[emotion].items():
                current = getattr(state, dim, 0.5)
                setattr(state, dim, max(0.0, min(1.0, current + delta * intensity)))
            if hasattr(state, "update_derived"):
                state.update_derived()
            log_event = getattr(emotion_engine, "_log_event", None)
            if log_event:
                log_event("perceived_emotion", f"{emotion}:{intensity:.2f}")
        except Exception as e:
            logger.warning("情绪状态更新失败: %s", e)

        return perception
