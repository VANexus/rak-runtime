"""
世界模型（World Model）— 环境状态的预测和建模

核心思想：系统不应该只对当前输入做被动反应，而应该：
1. 维护设备状态地图（哪些设备在线、当前状态）
2. 预测执行结果（执行动作 A 后，状态会如何变化）
3. 检测异常（实际状态 vs 预期状态）
4. 主动行为（根据预测主动执行）

数据来源：
- go-kernel 通过 gRPC 传入的设备状态
- rak-esp 通过 MQTT 上报的心跳和状态
- 记忆系统中的历史状态

类比：
- 人类的"空间感知"——知道周围物体的位置和状态
- 自动驾驶的"环境模型"——预测其他车辆的运动
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class DeviceState:
    """设备状态"""
    device_id: str
    online: bool = False
    last_seen: float = 0.0
    capabilities: List[str] = field(default_factory=list)
    current_action: str = ""
    position: Dict[str, float] = field(default_factory=dict)  # x, y, z
    sensors: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        """设备是否失联（超过 60 秒无心跳）"""
        return time.time() - self.last_seen > 60


@dataclass
class StatePrediction:
    """状态预测"""
    device_id: str
    predicted_state: Dict[str, Any]
    confidence: float
    action: str
    params: Dict[str, Any]


@dataclass
class AnomalyReport:
    """异常报告"""
    device_id: str
    expected: Dict[str, Any]
    actual: Dict[str, Any]
    severity: str  # "low", "medium", "high"
    description: str


class WorldModel:
    """
    世界模型 — 环境状态的预测和建模。

    维护：
    1. 设备状态地图（实时更新）
    2. 状态转移概率（动作 → 状态变化）
    3. 异常检测（预期 vs 实际）

    用途：
    - 动作规划：在执行前"想象"结果
    - 异常检测：实际状态偏离预期
    - 主动行为：根据预测主动执行
    """

    def __init__(self):
        # 设备状态地图
        self._devices: Dict[str, DeviceState] = {}

        # 状态转移记录：(device_id, action) → [结果状态列表]
        self._transitions: Dict[tuple, List[Dict]] = defaultdict(list)

        # 异常记录
        self._anomalies: List[AnomalyReport] = []

        # 统计
        self._total_updates = 0
        self._total_predictions = 0
        self._total_anomalies = 0

    def update_device(self, device_id: str, state: Dict[str, Any]):
        """
        更新设备状态。

        数据来源：go-kernel 转发的 rak-esp 状态上报。
        """
        self._total_updates += 1

        if device_id not in self._devices:
            self._devices[device_id] = DeviceState(device_id=device_id)

        device = self._devices[device_id]
        device.last_seen = time.time()
        device.online = state.get("online", True)

        if "capabilities" in state:
            device.capabilities = state["capabilities"]
        if "position" in state:
            device.position = state["position"]
        if "sensors" in state:
            device.sensors = state["sensors"]
        if "current_action" in state:
            device.current_action = state["current_action"]

        # 更新元数据
        for k, v in state.items():
            if k not in ("online", "capabilities", "position", "sensors", "current_action"):
                device.metadata[k] = v

        logger.debug(f"[WorldModel] 更新设备 {device_id}: {state}")

    def record_action_result(self, device_id: str, action: str, params: Dict,
                              result_state: Dict, success: bool):
        """
        记录动作执行结果（用于学习状态转移概率）。
        """
        key = (device_id, action)
        self._transitions[key].append({
            "params": params,
            "result_state": result_state,
            "success": success,
            "timestamp": time.time(),
        })

        # 限制记录数
        if len(self._transitions[key]) > 100:
            self._transitions[key] = self._transitions[key][-100:]

    def predict_next_state(self, device_id: str, action: str,
                            params: Dict = None) -> Optional[StatePrediction]:
        """
        预测执行动作后的下一个状态。

        基于历史状态转移概率。
        """
        self._total_predictions += 1

        device = self._devices.get(device_id)
        if device is None:
            return None

        key = (device_id, action)
        history = self._transitions.get(key, [])

        if not history:
            # 没有历史数据，返回默认预测
            return StatePrediction(
                device_id=device_id,
                predicted_state={"status": "unknown"},
                confidence=0.1,
                action=action,
                params=params or {},
            )

        # 统计最可能的结果状态
        success_count = sum(1 for h in history if h["success"])
        total = len(history)
        confidence = success_count / total if total > 0 else 0.5

        # 取最近的成功结果作为预测
        recent_success = [h for h in history if h["success"]]
        if recent_success:
            predicted = recent_success[-1]["result_state"]
        else:
            predicted = {"status": "predicted_failure"}

        return StatePrediction(
            device_id=device_id,
            predicted_state=predicted,
            confidence=confidence,
            action=action,
            params=params or {},
        )

    def detect_anomaly(self, device_id: str, expected: Dict,
                        actual: Dict) -> Optional[AnomalyReport]:
        """
        检测异常：实际状态偏离预期。
        """
        if not expected or not actual:
            return None

        # 检查关键字段是否匹配（数值类型用容差比较）
        mismatches = []
        for key in expected:
            if key not in actual:
                continue
            if isinstance(expected[key], (int, float)) and isinstance(actual[key], (int, float)):
                if abs(float(expected[key]) - float(actual[key])) > 0.01:
                    mismatches.append(key)
            elif expected[key] != actual[key]:
                mismatches.append(key)

        if not mismatches:
            return None

        # 判断严重程度
        severity = "low"
        if "status" in mismatches or "online" in mismatches:
            severity = "high"
        elif "position" in mismatches:
            severity = "medium"

        anomaly = AnomalyReport(
            device_id=device_id,
            expected=expected,
            actual=actual,
            severity=severity,
            description=f"字段不匹配: {', '.join(mismatches)}",
        )

        self._anomalies.append(anomaly)
        self._total_anomalies += 1

        # 限制异常记录数
        if len(self._anomalies) > 100:
            self._anomalies = self._anomalies[-100:]

        logger.warning(f"[WorldModel] 异常检测: {device_id} - {anomaly.description}")
        return anomaly

    def detect_all_anomalies(self) -> List:
        """检测所有设备的异常（基于最近的状态转换记录）"""
        all_anomalies = []
        for device_id, state in self._devices.items():
            # 检查设备是否长时间未更新
            if state.last_seen and (time.time() - state.last_seen) > 300:
                all_anomalies.append(AnomalyReport(
                    device_id=device_id,
                    expected={},
                    actual={},
                    severity="warning",
                    description=f"设备 {device_id} 超过5分钟未更新",
                ))
        return all_anomalies

    def get_device(self, device_id: str) -> Optional[DeviceState]:
        """获取设备状态"""
        return self._devices.get(device_id)

    def get_all_devices(self) -> Dict[str, DeviceState]:
        """获取所有设备"""
        return self._devices.copy()

    def get_online_devices(self) -> List[DeviceState]:
        """获取在线设备"""
        return [d for d in self._devices.values() if d.online and not d.stale]

    def get_device_capabilities(self, device_id: str) -> List[str]:
        """获取设备能力列表"""
        device = self._devices.get(device_id)
        return device.capabilities if device else []

    def format_device_state(self, device_id: str = "") -> str:
        """格式化设备状态为文本（用于注入 prompt）"""
        if device_id:
            device = self._devices.get(device_id)
            if device:
                return self._format_single_device(device)
            return f"设备 {device_id} 未知"

        # 返回所有设备状态
        parts = []
        for device in self._devices.values():
            parts.append(self._format_single_device(device))
        return "\n".join(parts) if parts else "无已知设备"

    def _format_single_device(self, device: DeviceState) -> str:
        status = "在线" if device.online and not device.stale else "离线"
        caps = ", ".join(device.capabilities[:5]) if device.capabilities else "未知"
        return (f"- {device.device_id}: {status}, "
                f"能力=[{caps}], "
                f"当前动作={device.current_action or '无'}")

    def stats(self) -> Dict:
        return {
            "total_devices": len(self._devices),
            "online_devices": len(self.get_online_devices()),
            "total_updates": self._total_updates,
            "total_predictions": self._total_predictions,
            "total_anomalies": self._total_anomalies,
            "transitions_recorded": sum(len(v) for v in self._transitions.values()),
        }
