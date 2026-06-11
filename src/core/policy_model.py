"""
Policy Model — 基底神经节（Basal Ganglia）

核心思想：state → neural network → action id
不经过 LLM 的 JSON 输出，直接输出离散动作 ID。

这是系统中"快速反应"的通道：
- LLM（前额叶皮层）：慢思考，复杂推理
- Policy Model（基底神经节）：快思考，直觉反应

类比：
- 人类触摸热锅 → 脊髓反射（不经过大脑）
- 传感器触发紧急事件 → Policy Model 直接响应（不经过 LLM）

实现：
- 特征哈希：将状态向量映射到固定维度
- 线性策略：softmax(output_weights @ features)
- 在线学习：执行反馈更新权重（REINFORCE 风格）
"""

import json
import logging
import math
import os
import time
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StateVector:
    """
    状态向量 — 系统当前状态的数值表示。

    包含：
    - 传感器数据（距离、温度、光照等）
    - 设备状态（在线/离线、电量等）
    - 上下文特征（时间、最近动作等）
    """
    features: Dict[str, float]  # 特征名 → 值
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_vector(self, dim: int = 64) -> List[float]:
        """将特征字典转换为固定维度向量（特征哈希）"""
        vec = [0.0] * dim
        for key, value in self.features.items():
            # 特征哈希：key → 多个维度
            hash_val = self._hash(key)
            for i in range(3):
                idx = (hash_val + i * 2654435761) % dim
                sign = 1.0 if ((hash_val >> i) & 1) == 0 else -1.0
                vec[idx] += sign * value
        return vec

    def _hash(self, s: str) -> int:
        h = 2166136261
        for b in s.encode():
            h ^= b
            h = (h * 16777619) & 0xFFFFFFFF
        return h


@dataclass
class ActionSpace:
    """离散动作空间"""
    actions: List[str]  # 动作名称列表
    action_to_id: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.action_to_id:
            self.action_to_id = {a: i for i, a in enumerate(self.actions)}

    def get_id(self, action: str) -> int:
        return self.action_to_id.get(action, -1)

    def get_name(self, action_id: int) -> str:
        if 0 <= action_id < len(self.actions):
            return self.actions[action_id]
        return "unknown"

    @property
    def size(self) -> int:
        return len(self.actions)


@dataclass
class PolicyDecision:
    """策略决策结果"""
    action_id: int           # 选择的动作 ID
    action_name: str         # 动作名称
    probabilities: List[float]  # 动作概率分布
    confidence: float        # 选择的置信度
    latency_ms: float        # 推理延迟
    method: str              # "policy" / "random" / "fallback"


class PolicyModel:
    """
    策略模型 — 基底神经节。

    架构：单层线性网络（softmax 策略）
    - 输入：状态向量（特征哈希）
    - 输出：动作概率分布（softmax）
    - 学习：在线梯度更新（REINFORCE 风格）

    为什么用单层？
    1. 推理速度快（<1ms）
    2. 可在边缘设备运行
    3. 在线学习简单
    4. 足以处理低层反射动作

    复杂推理仍交给 LLM（前额叶皮层）。
    """

    def __init__(self,
                 action_space: ActionSpace,
                 feature_dim: int = 64,
                 learning_rate: float = 0.01,
                 exploration_rate: float = 0.1,
                 model_path: Optional[str] = None):
        """
        Args:
            action_space: 动作空间
            feature_dim: 特征维度
            learning_rate: 学习率
            exploration_rate: 探索率（ε-greedy）
            model_path: 模型保存路径
        """
        self.action_space = action_space
        self.feature_dim = feature_dim
        self.learning_rate = learning_rate
        self.exploration_rate = exploration_rate
        self.model_path = model_path

        # 权重矩阵：[action_dim, feature_dim]
        # 初始化为小随机值
        self.weights = self._init_weights(action_space.size, feature_dim)

        # 偏置
        self.bias = [0.0] * action_space.size

        # 经验缓冲（用于在线学习）
        self.experience_buffer: List[Dict] = []
        self.max_buffer_size = 1000

        # 统计
        self.total_decisions = 0
        self.total_updates = 0
        self.action_counts = [0] * action_space.size

        # 加载预训练模型
        if model_path and os.path.exists(model_path):
            self._load_model(model_path)
            logger.info("[PolicyModel] 加载模型: %s", model_path)
        else:
            logger.info("[PolicyModel] 初始化: actions=%s, features=%s, lr=%s, ε=%s",
                        action_space.size, feature_dim, learning_rate, exploration_rate)

    def _init_weights(self, rows: int, cols: int) -> List[List[float]]:
        """Xavier 初始化"""
        scale = math.sqrt(2.0 / (rows + cols))
        import random
        return [[random.gauss(0, scale) for _ in range(cols)] for _ in range(rows)]

    def decide(self, state: StateVector) -> PolicyDecision:
        """
        做出决策。

        Args:
            state: 当前状态

        Returns:
            PolicyDecision: 决策结果
        """
        start_time = time.time()
        self.total_decisions += 1

        # 1. 状态 → 特征向量
        features = state.to_vector(self.feature_dim)

        # 2. 前向传播：logits = weights @ features + bias
        logits = self._forward(features)

        # 3. softmax → 概率分布
        probabilities = self._softmax(logits)

        # 4. 选择动作（ε-greedy 探索）
        import random
        if random.random() < self.exploration_rate:
            # 探索：随机选择
            action_id = random.randint(0, self.action_space.size - 1)
            method = "random"
        else:
            # 利用：选择概率最高的
            action_id = probabilities.index(max(probabilities))
            method = "policy"

        self.action_counts[action_id] += 1
        latency_ms = (time.time() - start_time) * 1000

        return PolicyDecision(
            action_id=action_id,
            action_name=self.action_space.get_name(action_id),
            probabilities=probabilities,
            confidence=probabilities[action_id],
            latency_ms=latency_ms,
            method=method,
        )

    def _forward(self, features: List[float]) -> List[float]:
        """前向传播：logits = weights @ features + bias"""
        logits = []
        for i in range(self.action_space.size):
            logit = self.bias[i]
            for j in range(min(len(features), self.feature_dim)):
                logit += self.weights[i][j] * features[j]
            logits.append(logit)
        return logits

    def _softmax(self, logits: List[float]) -> List[float]:
        """Softmax 激活函数"""
        max_logit = max(logits)
        exp_logits = [math.exp(l - max_logit) for l in logits]
        sum_exp = sum(exp_logits)
        return [e / sum_exp for e in exp_logits]

    def update(self, state: StateVector, action_id: int, reward: float):
        """
        在线学习更新（REINFORCE 风格）。

        Args:
            state: 决策时的状态
            action_id: 选择的动作
            reward: 执行反馈（正=成功，负=失败）
        """
        self.total_updates += 1

        # 1. 状态 → 特征向量
        features = state.to_vector(self.feature_dim)

        # 2. 当前策略下的概率
        logits = self._forward(features)
        probs = self._softmax(logits)

        # 3. 策略梯度更新
        # ∇J ≈ (reward - baseline) * ∇log π(a|s)
        # 对于 softmax 策略：
        # ∇log π(a|s) = features * (1[a==chosen] - π(a|s))
        baseline = 0.0  # 可以用移动平均
        advantage = reward - baseline

        for i in range(self.action_space.size):
            indicator = 1.0 if i == action_id else 0.0
            grad = advantage * (indicator - probs[i])

            # 更新权重
            for j in range(min(len(features), self.feature_dim)):
                self.weights[i][j] += self.learning_rate * grad * features[j]

            # 更新偏置
            self.bias[i] += self.learning_rate * grad

        logger.debug("[PolicyModel] 更新: action=%s, reward=%.3f, advantage=%.3f",
                    action_id, reward, advantage)

    def store_experience(self, state: StateVector, action_id: int,
                         reward: float, next_state: Optional[StateVector] = None):
        """存储经验（用于批量学习）"""
        self.experience_buffer.append({
            "state": state,
            "action_id": action_id,
            "reward": reward,
            "next_state": next_state,
            "timestamp": time.time(),
        })

        # 缓冲区满时批量更新
        if len(self.experience_buffer) >= self.max_buffer_size:
            self._batch_update()

    def _batch_update(self):
        """批量更新（从经验缓冲区）"""
        if not self.experience_buffer:
            return

        logger.info("[PolicyModel] 批量更新: %s 条经验", len(self.experience_buffer))

        for exp in self.experience_buffer:
            self.update(exp["state"], exp["action_id"], exp["reward"])

        self.experience_buffer.clear()

    def save_model(self, path: Optional[str] = None):
        """保存模型"""
        save_path = path or self.model_path
        if not save_path:
            return

        model_data = {
            "weights": self.weights,
            "bias": self.bias,
            "action_space": self.action_space.actions,
            "feature_dim": self.feature_dim,
            "learning_rate": self.learning_rate,
            "exploration_rate": self.exploration_rate,
            "total_decisions": self.total_decisions,
            "total_updates": self.total_updates,
        }

        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(model_data, f, indent=2)

        logger.info("[PolicyModel] 模型已保存: %s", save_path)

    def _load_model(self, path: str):
        """加载模型"""
        try:
            with open(path) as f:
                data = json.load(f)

            self.weights = data["weights"]
            self.bias = data["bias"]
            self.total_decisions = data.get("total_decisions", 0)
            self.total_updates = data.get("total_updates", 0)
        except Exception as e:
            logger.warning("[PolicyModel] 模型加载失败: %s", e)

    def stats(self) -> Dict:
        """返回统计信息"""
        return {
            "total_decisions": self.total_decisions,
            "total_updates": self.total_updates,
            "action_counts": dict(zip(self.action_space.actions, self.action_counts)),
            "exploration_rate": self.exploration_rate,
            "buffer_size": len(self.experience_buffer),
            "feature_dim": self.feature_dim,
        }


# ========== 默认动作空间 ==========

DEFAULT_ACTION_SPACE = ActionSpace(actions=[
    "shake_head", "wave_hand", "nod", "dance",
    "move_forward", "move_back", "turn_left", "turn_right",
    "lock_open", "lock_close",
    "light_on", "light_off",
    "emergency_stop",
    "audio_play", "audio_record",
    "sensor_read", "camera_capture",
    "idle",  # 空闲动作
])


class PolicyModelManager:
    """
    策略模型管理器。

    管理多个策略模型：
    - 默认策略：通用反射动作
    - 专用策略：特定场景（如导航、交互）
    """

    def __init__(self, model_dir: str = "models/policy"):
        self.model_dir = model_dir
        self.models: Dict[str, PolicyModel] = {}

    def get_or_create(self, name: str = "default",
                      action_space: Optional[ActionSpace] = None) -> PolicyModel:
        """获取或创建策略模型"""
        if name not in self.models:
            space = action_space or DEFAULT_ACTION_SPACE
            model_path = os.path.join(self.model_dir, f"{name}.json")
            self.models[name] = PolicyModel(
                action_space=space,
                model_path=model_path,
            )
        return self.models[name]

    def save_all(self):
        """保存所有模型"""
        for name, model in self.models.items():
            model.save_model()

    def stats(self) -> Dict:
        """返回所有模型的统计"""
        return {name: model.stats() for name, model in self.models.items()}
